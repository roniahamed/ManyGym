import logging
import uuid
import zoneinfo
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple, Union

from django.conf import settings
from django.db import connection
from django.db.models import (
    Q,
    Count,
    Prefetch,
    Case,
    When,
    Value,
    IntegerField,
)
from django.db.models.expressions import RawSQL
from django.utils import timezone

from apps.gyms.models import (
    Gym,
    GymLocation,
    GymOpeningHours,
    GymGallery,
    GymFollow,
    GymBlockedUser,
)
from apps.amenities.models import GymAmenity
from apps.memberships.models import MembershipPlan
from apps.gyms.services.geo_services import (
    search_nearby_gym_ids_redis,
    sync_gym_location_to_redis,
)
from common.enums import PlanStatusEnum

logger = logging.getLogger(__name__)

_POSTGIS_AVAILABLE: Optional[bool] = None


def is_postgis_available() -> bool:
    """
    Checks if the PostGIS spatial extension is installed on the active PostgreSQL database.
    Caches result in memory to avoid repeated metadata lookups.
    """
    global _POSTGIS_AVAILABLE
    if _POSTGIS_AVAILABLE is not None:
        return _POSTGIS_AVAILABLE

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'postgis';")
            row = cursor.fetchone()
            _POSTGIS_AVAILABLE = row is not None
    except Exception as exc:
        logger.debug("Could not verify PostGIS extension: %s", exc)
        _POSTGIS_AVAILABLE = False

    return _POSTGIS_AVAILABLE


def get_distance_expression(latitude: float, longitude: float) -> RawSQL:
    """
    Constructs a SQL expression computing spherical distance in kilometers.
    Utilizes PostGIS ST_DistanceSphere if available, else falls back to Haversine.
    """
    lat = float(latitude)
    lon = float(longitude)

    if is_postgis_available():
        return RawSQL(
            """
            ST_DistanceSphere(
                ST_MakePoint("gym_locations"."longitude", "gym_locations"."latitude"),
                ST_MakePoint(%s, %s)
            ) / 1000.0
            """,
            (lon, lat),
        )

    # Standard PostgreSQL Spherical Law of Cosines / Haversine formula
    return RawSQL(
        """
        6371.0 * acos(
            least(1.0, greatest(-1.0,
                sin(radians(%s)) * sin(radians("gym_locations"."latitude")) +
                cos(radians(%s)) * cos(radians("gym_locations"."latitude")) *
                cos(radians("gym_locations"."longitude") - radians(%s))
            ))
        )
        """,
        (lat, lat, lon),
    )


def compute_today_opening_hours(gym: Gym) -> Tuple[bool, str]:
    """
    Evaluates current open/closed status and returns (is_open_now, today_hours_str)
    taking into account the gym's specific timezone and 7-day schedule.
    """
    try:
        tz = zoneinfo.ZoneInfo(gym.timezone or "UTC")
        local_now = timezone.now().astimezone(tz)
    except Exception:
        local_now = timezone.now()

    # In GymOpeningHours: 0=Sunday, 1=Monday, ..., 6=Saturday
    # In Python weekday: 0=Monday, ..., 6=Sunday
    today_dow = (local_now.weekday() + 1) % 7
    current_time = local_now.time()

    hours_records = getattr(gym, "prefetched_opening_hours", None)
    if hours_records is None:
        hours_records = list(gym.opening_hours.all())

    today_record = None
    for h in hours_records:
        if h.day_of_week == today_dow:
            today_record = h
            break

    if not today_record or today_record.is_closed:
        return False, "Closed"

    if today_record.start_time and today_record.end_time:
        start_str = today_record.start_time.strftime("%H:%M")
        end_str = today_record.end_time.strftime("%H:%M")
        is_open = today_record.start_time <= current_time <= today_record.end_time
        return is_open, f"{start_str} - {end_str}"

    return False, "Closed"


def search_nearby_gyms(
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius_km: float = 20.0,
    category: Optional[str] = None,
    city: Optional[str] = None,
    search: Optional[str] = None,
    requesting_user: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    Primary geospatial and multi-filter discovery selector for gyms.
    - Uses Redis GEO when coordinates are present (<1ms lookup).
    - Falls back to PostgreSQL / PostGIS Haversine calculation on cache miss.
    - Filters by category, city, keyword search, and visibility states.
    - Excludes soft-deleted, deactivated, or unpublished gyms.
    - Excludes gyms that have blocked the requesting user.
    """
    # Base filter: Only published, non-deactivated, non-deleted gyms
    visibility_filter = Q(settings__isnull=True) | (
        Q(settings__is_published=True)
        & Q(settings__is_deactivated=False)
        & Q(settings__is_deleted=False)
    )

    base_qs = Gym.objects.filter(visibility_filter).select_related(
        "owner_user",
        "settings",
    ).prefetch_related(
        Prefetch(
            "locations",
            queryset=GymLocation.objects.filter(is_primary=True),
            to_attr="prefetched_primary_locations",
        ),
        Prefetch(
            "opening_hours",
            queryset=GymOpeningHours.objects.order_by("day_of_week"),
            to_attr="prefetched_opening_hours",
        ),
        Prefetch(
            "gym_amenities",
            queryset=GymAmenity.objects.select_related("amenity")[:10],
            to_attr="prefetched_amenities",
        ),
    ).annotate(
        followers_count_annotated=Count("followers", distinct=True)
    )

    # Exclude gyms where user is blocked
    if requesting_user and requesting_user.is_authenticated:
        base_qs = base_qs.exclude(
            blocked_users__user=requesting_user
        )

    # Category filter (matches primary or secondary type)
    if category and category.strip():
        cat = category.strip()
        base_qs = base_qs.filter(
            Q(primary_type=cat) | Q(secondary_type=cat)
        )

    # City filter
    if city and city.strip():
        c = city.strip()
        base_qs = base_qs.filter(
            locations__city__icontains=c,
            locations__is_primary=True,
        )

    # Keyword search filter
    if search and search.strip():
        s = search.strip()
        base_qs = base_qs.filter(
            Q(name__icontains=s)
            | Q(short_description__icontains=s)
            | Q(locations__address__icontains=s)
            | Q(locations__city__icontains=s)
        ).distinct()

    has_coords = latitude is not None and longitude is not None
    redis_distances: Dict[str, float] = {}

    if has_coords:
        lat = float(latitude)
        lon = float(longitude)
        radius = float(radius_km)

        # 1. Fast Path: Redis Geospatial Search
        redis_results = search_nearby_gym_ids_redis(lat, lon, radius)
        if redis_results:
            redis_distances = {gid: dist for gid, dist in redis_results}
            # Filter DB query to only the IDs returned by Redis
            gyms_qs = base_qs.filter(id__in=list(redis_distances.keys()))
            gym_instances = list(gyms_qs)

            # Sort by distance from Redis
            gym_instances.sort(
                key=lambda g: redis_distances.get(str(g.id), float("inf"))
            )
        else:
            # 2. Fallback Path: PostgreSQL Haversine / PostGIS Query
            dist_expr = get_distance_expression(lat, lon)
            matching_locations = (
                GymLocation.objects.filter(is_primary=True)
                .annotate(calculated_distance=dist_expr)
                .filter(calculated_distance__lte=radius)
                .only("gym_id", "latitude", "longitude")
                .order_by("calculated_distance")
            )

            loc_distances = {}
            for loc in matching_locations:
                gid = str(loc.gym_id)
                loc_distances[gid] = float(loc.calculated_distance)
                # Warm Redis Geo cache
                sync_gym_location_to_redis(gid, loc.latitude, loc.longitude)

            if loc_distances:
                gyms_qs = base_qs.filter(id__in=list(loc_distances.keys()))
                gym_instances = list(gyms_qs)
                gym_instances.sort(
                    key=lambda g: loc_distances.get(str(g.id), float("inf"))
                )
                redis_distances = loc_distances
            else:
                gym_instances = []
    else:
        # Non-geospatial search (e.g. by city or category only)
        gym_instances = list(base_qs.order_by("-created_at"))

    # Resolve follow status for requesting user
    following_gym_ids = set()
    if requesting_user and requesting_user.is_authenticated and gym_instances:
        user_gym_ids = [g.id for g in gym_instances]
        following_gym_ids = set(
            GymFollow.objects.filter(
                user=requesting_user,
                gym_id__in=user_gym_ids,
            ).values_list("gym_id", flat=True)
        )

    results = []
    for gym in gym_instances:
        primary_loc = getattr(gym, "prefetched_primary_locations", None)
        loc_obj = primary_loc[0] if primary_loc else gym.locations.filter(is_primary=True).first()

        is_open, today_hours = compute_today_opening_hours(gym)

        amenities = getattr(gym, "prefetched_amenities", None)
        if amenities is None:
            amenities = list(gym.gym_amenities.select_related("amenity")[:5])
        amenities_preview = [a.amenity.name for a in amenities if getattr(a, "amenity", None)]

        dist = redis_distances.get(str(gym.id))
        distance_km = round(dist, 2) if dist is not None else None

        results.append({
            "id": gym.id,
            "name": gym.name,
            "profile_picture_url": gym.profile_picture_url,
            "cover_photo_url": gym.cover_photo_url,
            "short_description": gym.short_description,
            "primary_type": gym.primary_type,
            "primary_type_display": gym.get_primary_type_display(),
            "secondary_type": gym.secondary_type,
            "secondary_type_display": gym.get_secondary_type_display() if gym.secondary_type else None,
            "gender_required": gym.gender_required,
            "gender_required_display": gym.get_gender_required_display(),
            "min_age": gym.min_age,
            "timezone": gym.timezone,
            "location": loc_obj,
            "distance_km": distance_km,
            "is_open_now": is_open,
            "today_opening_hours": today_hours,
            "amenities_preview": amenities_preview,
            "followers_count": getattr(gym, "followers_count_annotated", 0),
            "is_following": gym.id in following_gym_ids,
            "created_at": gym.created_at,
        })

    return results


def get_gym_public_details(
    gym_id: Union[str, uuid.UUID],
    requesting_user: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """
    Retrieves full public view details for a specific gym:
    - Overview information
    - All locations (with primary pinned)
    - 7-day schedule with human-readable names and live open/closed status
    - Categorized amenities (complimentary vs paid)
    - Gallery media items with optimized URLs and thumbnails
    - Social statistics (followers, members count)
    - Active membership plans preview
    - User relationship state (is_following)
    """
    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return None

    gym = (
        Gym.objects.filter(id=gym_id)
        .select_related("owner_user", "settings")
        .prefetch_related(
            Prefetch("locations", queryset=GymLocation.objects.order_by("-is_primary", "city")),
            Prefetch("opening_hours", queryset=GymOpeningHours.objects.order_by("day_of_week")),
            Prefetch("gallery_items", queryset=GymGallery.objects.order_by("order_index", "-created_at")),
            Prefetch("gym_amenities", queryset=GymAmenity.objects.select_related("amenity").order_by("is_paid", "amenity__name")),
            Prefetch("membership_plans", queryset=MembershipPlan.objects.filter(plan_status=PlanStatusEnum.ACTIVE).order_by("price")),
        )
        .first()
    )

    if not gym:
        return None

    # Check settings visibility: return None if deleted, deactivated, or unpublished
    settings_obj = getattr(gym, "settings", None)
    if settings_obj and (
        settings_obj.is_deleted
        or settings_obj.is_deactivated
        or not settings_obj.is_published
    ):
        # Allow owner to view their own unpublished gym
        if not (requesting_user and requesting_user.is_authenticated and gym.owner_user_id == requesting_user.id):
            return None

    # Check if user is blocked by gym
    if requesting_user and requesting_user.is_authenticated:
        if GymBlockedUser.objects.filter(gym=gym, user=requesting_user).exists():
            return None

    # Locations
    locations_list = list(gym.locations.all())
    primary_location = next((loc for loc in locations_list if loc.is_primary), locations_list[0] if locations_list else None)

    # Operating hours
    is_open_now, today_hours = compute_today_opening_hours(gym)
    hours_data = []
    days_map = dict(GymOpeningHours.DAYS_OF_WEEK)
    for h in gym.opening_hours.all():
        hours_data.append({
            "id": h.id,
            "day_of_week": h.day_of_week,
            "day_name": days_map.get(h.day_of_week, str(h.day_of_week)),
            "start_time": h.start_time,
            "end_time": h.end_time,
            "is_closed": h.is_closed,
        })

    # Amenities breakdown
    free_amenities = []
    paid_amenities = []
    for ga in gym.gym_amenities.all():
        item = {
            "id": str(ga.id),
            "amenity_id": str(ga.amenity.id),
            "name": ga.amenity.name,
            "group_name": ga.amenity.group_name,
            "group_display": ga.amenity.get_group_name_display(),
            "is_paid": ga.is_paid,
            "default_price": str(ga.default_price),
        }
        if ga.is_paid:
            paid_amenities.append(item)
        else:
            free_amenities.append(item)

    # Gallery media items
    gallery_data = []
    for item in gym.gallery_items.all():
        gallery_data.append({
            "id": item.id,
            "media_url": item.media_url,
            "media_type": item.media_type,
            "category": item.category,
            "category_display": item.get_category_display(),
            "caption": item.caption,
            "order_index": item.order_index,
            "original_url": getattr(item, "original_url", None) or item.media_url,
            "optimized_url": getattr(item, "optimized_url", None),
            "thumbnail_url": getattr(item, "thumbnail_url", None),
            "processing_status": getattr(item, "processing_status", "completed"),
        })

    # Active membership plans
    plans_data = []
    for p in gym.membership_plans.all():
        plans_data.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "plan_type": p.plan_type,
            "plan_type_display": p.get_plan_type_display(),
            "price": str(p.price),
            "duration_value": p.duration_value,
            "duration_unit": p.duration_unit,
            "duration_unit_display": p.get_duration_unit_display(),
            "joining_fee": str(p.joining_fee),
        })

    # Social stats
    followers_count = gym.followers.count()
    members_count = getattr(gym, "members", None).count() if hasattr(gym, "members") else 0
    is_following = False
    if requesting_user and requesting_user.is_authenticated:
        is_following = GymFollow.objects.filter(user=requesting_user, gym=gym).exists()

    return {
        "id": gym.id,
        "name": gym.name,
        "profile_picture_url": gym.profile_picture_url,
        "cover_photo_url": gym.cover_photo_url,
        "short_description": gym.short_description,
        "primary_type": gym.primary_type,
        "primary_type_display": gym.get_primary_type_display(),
        "secondary_type": gym.secondary_type,
        "secondary_type_display": gym.get_secondary_type_display() if gym.secondary_type else None,
        "gender_required": gym.gender_required,
        "gender_required_display": gym.get_gender_required_display(),
        "min_age": gym.min_age,
        "timezone": gym.timezone,
        "created_at": gym.created_at,
        "owner_public": {
            "id": gym.owner_user.id,
            "name": f"{gym.owner_user.first_name} {gym.owner_user.last_name}".strip() or gym.owner_user.username,
        },
        "location": primary_location,
        "locations": locations_list,
        "today_status": {
            "is_open_now": is_open_now,
            "today_hours": today_hours,
        },
        "operating_hours": hours_data,
        "amenities": {
            "free_amenities": free_amenities,
            "paid_amenities": paid_amenities,
            "total_count": len(free_amenities) + len(paid_amenities),
        },
        "gallery": gallery_data,
        "membership_plans": plans_data,
        "social": {
            "followers_count": followers_count,
            "members_count": members_count,
            "is_following": is_following,
        },
    }
