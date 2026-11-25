from typing import Any, Dict, List, Optional
from django.db.models import Count, Prefetch, Q, QuerySet, Value
from django.db.models.functions import Concat

from apps.amenities.models import GymAmenity
from apps.gyms.models import GymLocation
from apps.gyms.selectors.geo_selectors import search_nearby_gyms
from apps.memberships.models import MembershipPlan
from apps.posts.models import GymPost
from apps.posts.selectors import get_user_social_context, list_gym_feed
from apps.users.models import FollowRequestStatus, User, UserFollowRequest
from common.enums import PlanStatusEnum
from common.exceptions import DomainValidationError

SEARCH_FILTER_ALL = "all"
SEARCH_FILTER_GYM = "gym"
SEARCH_FILTER_PEOPLE = "people"
SEARCH_FILTER_POST = "post"
SEARCH_FILTER_PLAN = "plan"
SEARCH_FILTER_AMENITY = "amenity"

VALID_CANONICAL_FILTERS = (
    SEARCH_FILTER_ALL,
    SEARCH_FILTER_GYM,
    SEARCH_FILTER_PEOPLE,
    SEARCH_FILTER_POST,
    SEARCH_FILTER_PLAN,
    SEARCH_FILTER_AMENITY,
)

FILTER_ALIASES: Dict[str, str] = {
    "all": SEARCH_FILTER_ALL,
    "gym": SEARCH_FILTER_GYM,
    "gyms": SEARCH_FILTER_GYM,
    "people": SEARCH_FILTER_PEOPLE,
    "person": SEARCH_FILTER_PEOPLE,
    "user": SEARCH_FILTER_PEOPLE,
    "users": SEARCH_FILTER_PEOPLE,
    "post": SEARCH_FILTER_POST,
    "posts": SEARCH_FILTER_POST,
    "plan": SEARCH_FILTER_PLAN,
    "plans": SEARCH_FILTER_PLAN,
    "membership_plan": SEARCH_FILTER_PLAN,
    "membership_plans": SEARCH_FILTER_PLAN,
    "amenity": SEARCH_FILTER_AMENITY,
    "amenities": SEARCH_FILTER_AMENITY,
}


def normalize_search_filter(raw_filter: Optional[str]) -> str:
    """Normalizes filter/tab aliases to canonical search filter values."""
    if raw_filter is None or not str(raw_filter).strip():
        return SEARCH_FILTER_ALL
    key = str(raw_filter).strip().lower().replace("-", "_").replace(" ", "_")
    canonical = FILTER_ALIASES.get(key)
    if not canonical:
        raise DomainValidationError(
            f"Invalid search filter '{raw_filter}'. Allowed values: {', '.join(VALID_CANONICAL_FILTERS)}."
        )
    return canonical


def validate_search_query(query: Optional[str]) -> str:
    """Validates and normalizes a raw search keyword."""
    if query is None:
        return ""
    raw = str(query)
    if "\x00" in raw:
        raise DomainValidationError("Null characters are not allowed in search query.")
    return raw.strip()


def get_central_search_context(user: User) -> Dict[str, Any]:
    """
    Computes social, membership, blocklist, and pending follow-request context
    once per request for zero-N+1 central search queries and serialization.
    """
    ctx = dict(get_user_social_context(user))
    if user and getattr(user, "is_authenticated", False):
        ctx["pending_follow_request_user_ids"] = set(
            UserFollowRequest.objects.filter(
                requester=user,
                status=FollowRequestStatus.PENDING,
            ).values_list("target_user_id", flat=True)
        )
    else:
        ctx["pending_follow_request_user_ids"] = set()
    return ctx


def _apply_gym_relation_filters(
    qs: QuerySet,
    *,
    city: Optional[str],
    gym_category: Optional[str],
    blocked_gym_ids: set,
) -> QuerySet:
    """
    Shared visibility, blocklist, city, and category filter helper for gym-owned
    searchable entities (MembershipPlan and GymAmenity).
    """
    visibility_q = Q(gym__settings__isnull=True) | (
        Q(gym__settings__is_published=True)
        & Q(gym__settings__is_deactivated=False)
        & Q(gym__settings__is_deleted=False)
    )
    qs = qs.filter(visibility_q)

    if blocked_gym_ids:
        qs = qs.exclude(gym_id__in=blocked_gym_ids)

    if city:
        qs = qs.filter(
            gym__locations__city__icontains=city,
            gym__locations__is_primary=True,
        )

    if gym_category:
        qs = qs.filter(
            Q(gym__primary_type=gym_category) | Q(gym__secondary_type=gym_category)
        )

    return qs


def _primary_gym_location_prefetch() -> Prefetch:
    return Prefetch(
        "gym__locations",
        queryset=GymLocation.objects.filter(is_primary=True),
        to_attr="prefetched_primary_locations",
    )


def search_gyms_central(
    *,
    query: str,
    requesting_user: User,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius_km: float = 20.0,
    gym_category: Optional[str] = None,
    city: Optional[str] = None,
    gender_required: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Searches visible gyms reusing the geospatial & directory selector."""
    has_coords = latitude is not None and longitude is not None
    has_criteria = bool(query or city or gym_category or gender_required or has_coords)
    if not has_criteria:
        return []

    return search_nearby_gyms(
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        category=gym_category,
        city=city,
        search=query or None,
        gender_required=gender_required,
        requesting_user=requesting_user,
    )


def search_people_central(
    *,
    query: str,
    requesting_user: User,
    social_ctx: Dict[str, Any],
    city: Optional[str] = None,
    gender: Optional[str] = None,
    is_following: Optional[bool] = None,
) -> QuerySet[User]:
    """
    Searches active, non-deleted, non-deactivated users excluding self and mutually blocked users.
    Private profiles can be discovered by name only and never leak hidden city/bio fields in search.
    """
    has_criteria = bool(query or city or gender or is_following is not None)
    if not has_criteria:
        return User.objects.none()

    blocked_user_ids = social_ctx.get("blocked_user_ids", set())
    followed_user_ids = social_ctx.get("followed_user_ids", set())

    qs = (
        User.objects.filter(is_active=True)
        .exclude(id=requesting_user.id)
        .exclude(settings__is_deleted=True)
        .exclude(settings__is_deactivated=True)
        .select_related("profile", "settings")
    )

    if blocked_user_ids:
        qs = qs.exclude(id__in=blocked_user_ids)

    is_public_or_followed_q = (
        Q(profile__isnull=True)
        | Q(profile__is_private=False)
        | Q(id__in=followed_user_ids)
    )

    if query:
        qs = qs.annotate(
            full_name_concat=Concat("first_name", Value(" "), "last_name"),
        )
        name_match_q = (
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(full_name_concat__icontains=query)
        )
        public_profile_match_q = is_public_or_followed_q & (
            Q(profile__city__icontains=query)
            | Q(profile__home_town__icontains=query)
            | Q(profile__about_you__icontains=query)
        )
        qs = qs.filter(name_match_q | public_profile_match_q)

    if city:
        qs = qs.filter(
            is_public_or_followed_q
            & (Q(profile__city__icontains=city) | Q(profile__home_town__icontains=city))
        )

    if gender:
        qs = qs.filter(is_public_or_followed_q & Q(profile__gender=gender))

    if is_following is True:
        qs = qs.filter(id__in=followed_user_ids)
    elif is_following is False:
        qs = qs.exclude(id__in=followed_user_ids)

    return (
        qs.annotate(followers_count_annotated=Count("follower_relations", distinct=True))
        .distinct()
        .order_by("first_name", "last_name", "-created_at")
    )


def search_posts_central(
    *,
    query: str,
    requesting_user: User,
    social_ctx: Dict[str, Any],
    owner_type: Optional[str] = None,
    is_repost: Optional[bool] = None,
) -> QuerySet[GymPost]:
    """
    Searches visible community posts and reposts reusing list_gym_feed visibility,
    privacy, blocklist, and age-restriction enforcement.
    """
    has_criteria = bool(query or owner_type or is_repost is not None)
    if not has_criteria:
        return GymPost.objects.none()

    return list_gym_feed(
        search=query or None,
        requesting_user=requesting_user,
        owner_type=owner_type,
        is_repost=is_repost,
        social_ctx=social_ctx,
    )


def search_plans_central(
    *,
    query: str,
    social_ctx: Dict[str, Any],
    city: Optional[str] = None,
    gym_category: Optional[str] = None,
    plan_type: Optional[str] = None,
) -> QuerySet[MembershipPlan]:
    """
    Searches active membership plans belonging to published, active, non-blocking gyms.
    """
    has_criteria = bool(query or city or gym_category or plan_type)
    if not has_criteria:
        return MembershipPlan.objects.none()

    qs = (
        MembershipPlan.objects.filter(plan_status=PlanStatusEnum.ACTIVE)
        .select_related("gym", "gym__settings")
        .prefetch_related(_primary_gym_location_prefetch())
    )
    qs = _apply_gym_relation_filters(
        qs,
        city=city,
        gym_category=gym_category,
        blocked_gym_ids=social_ctx.get("blocked_gym_ids", set()),
    )

    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(gym__name__icontains=query)
        )

    if plan_type:
        qs = qs.filter(plan_type=plan_type)

    return (
        qs.annotate(annotated_amenities_count=Count("included_amenities", distinct=True))
        .distinct()
        .order_by("-created_at")
    )


def search_amenities_central(
    *,
    query: str,
    social_ctx: Dict[str, Any],
    city: Optional[str] = None,
    gym_category: Optional[str] = None,
    amenity_group: Optional[str] = None,
    is_paid: Optional[bool] = None,
) -> QuerySet[GymAmenity]:
    """
    Searches configured gym amenities belonging to published, active, non-blocking gyms.
    """
    has_criteria = bool(query or city or gym_category or amenity_group or is_paid is not None)
    if not has_criteria:
        return GymAmenity.objects.none()

    qs = (
        GymAmenity.objects.all()
        .select_related("amenity", "gym", "gym__settings")
        .prefetch_related(_primary_gym_location_prefetch())
    )
    qs = _apply_gym_relation_filters(
        qs,
        city=city,
        gym_category=gym_category,
        blocked_gym_ids=social_ctx.get("blocked_gym_ids", set()),
    )

    if query:
        qs = qs.filter(
            Q(amenity__name__icontains=query)
            | Q(amenity__group_name__icontains=query)
            | Q(gym__name__icontains=query)
        )

    if amenity_group:
        qs = qs.filter(amenity__group_name=amenity_group)

    if is_paid is not None:
        qs = qs.filter(is_paid=bool(is_paid))

    return qs.distinct().order_by("is_paid", "amenity__name", "-created_at")


def execute_central_search(
    *,
    requesting_user: User,
    params: Dict[str, Any],
    social_ctx: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Executes central search across Gyms, People, Posts, Membership Plans, and Amenities,
    returning live per-category tab counts and either grouped top results (filter='all')
    or the full target collection for pagination on the dedicated search result page.
    """
    query = validate_search_query(params.get("q"))
    search_filter = normalize_search_filter(params.get("filter"))
    limit = int(params.get("limit") or 5)

    city = (params.get("city") or "").strip() or None
    gym_category = (params.get("gym_category") or "").strip() or None
    gender_required = (params.get("gender_required") or "").strip() or None
    latitude = params.get("latitude")
    longitude = params.get("longitude")
    radius = params.get("radius", 20.0)
    gender = (params.get("gender") or "").strip() or None
    is_following = params.get("is_following")
    owner_type = (params.get("owner_type") or "").strip() or None
    is_repost = params.get("is_repost")
    plan_type = (params.get("plan_type") or "").strip() or None
    amenity_group = (params.get("amenity_group") or "").strip() or None
    is_paid = params.get("is_paid")

    if social_ctx is None:
        social_ctx = get_central_search_context(requesting_user)

    gyms_list = search_gyms_central(
        query=query,
        requesting_user=requesting_user,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius,
        gym_category=gym_category,
        city=city,
        gender_required=gender_required,
    )
    people_qs = search_people_central(
        query=query,
        requesting_user=requesting_user,
        social_ctx=social_ctx,
        city=city,
        gender=gender,
        is_following=is_following,
    )
    posts_qs = search_posts_central(
        query=query,
        requesting_user=requesting_user,
        social_ctx=social_ctx,
        owner_type=owner_type,
        is_repost=is_repost,
    )
    plans_qs = search_plans_central(
        query=query,
        social_ctx=social_ctx,
        city=city,
        gym_category=gym_category,
        plan_type=plan_type,
    )
    amenities_qs = search_amenities_central(
        query=query,
        social_ctx=social_ctx,
        city=city,
        gym_category=gym_category,
        amenity_group=amenity_group,
        is_paid=is_paid,
    )

    gyms_count = len(gyms_list)
    people_count = people_qs.count()
    posts_count = posts_qs.count()
    plans_count = plans_qs.count()
    amenities_count = amenities_qs.count()

    counts = {
        "gyms": gyms_count,
        "people": people_count,
        "posts": posts_count,
        "membership_plans": plans_count,
        "amenities": amenities_count,
        "total": gyms_count + people_count + posts_count + plans_count + amenities_count,
    }

    if search_filter == SEARCH_FILTER_ALL:
        return {
            "query": query,
            "filter": search_filter,
            "counts": counts,
            "social_ctx": social_ctx,
            "results": {
                "gyms": gyms_list[:limit],
                "people": list(people_qs[:limit]),
                "posts": list(posts_qs[:limit]),
                "membership_plans": list(plans_qs[:limit]),
                "amenities": list(amenities_qs[:limit]),
            },
        }

    target_map = {
        SEARCH_FILTER_GYM: gyms_list,
        SEARCH_FILTER_PEOPLE: people_qs,
        SEARCH_FILTER_POST: posts_qs,
        SEARCH_FILTER_PLAN: plans_qs,
        SEARCH_FILTER_AMENITY: amenities_qs,
    }

    return {
        "query": query,
        "filter": search_filter,
        "counts": counts,
        "social_ctx": social_ctx,
        "target_results": target_map[search_filter],
    }
