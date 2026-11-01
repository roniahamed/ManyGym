from typing import List, Dict, Any, Optional, Iterator
from apps.gyms.models import Gym, GymSetting, GymBlockedUser
from apps.access_control.models import GymStaffAssignment


def stream_accessible_gyms_for_user(user) -> Iterator[Dict[str, Any]]:
    """
    Generator streaming all gyms accessible to the user (owned or staff),
    yielding items lazily with optimized queries, field projections, and iterator().
    """
    seen_gym_ids = set()

    # 1. Owned gyms
    owned_gyms = (
        Gym.objects.filter(owner_user=user)
        .only("id", "name", "primary_type", "profile_picture_url")
        .distinct()
        .iterator()
    )
    for g in owned_gyms:
        gid = str(g.id)
        seen_gym_ids.add(gid)
        yield {
            "gym_id": gid,
            "name": g.name,
            "role": "Owner",
            "is_owner": True,
            "primary_type": g.primary_type,
            "profile_picture_url": g.profile_picture_url,
        }

    # 2. Staff assignments
    staff_assignments = (
        GymStaffAssignment.objects.filter(
            user=user,
            status="active",
        )
        .select_related("gym", "role")
        .only(
            "id",
            "gym__id",
            "gym__name",
            "gym__primary_type",
            "gym__profile_picture_url",
            "role__name",
        )
        .iterator()
    )
    for assignment in staff_assignments:
        gid = str(assignment.gym.id)
        if gid not in seen_gym_ids:
            seen_gym_ids.add(gid)
            yield {
                "gym_id": gid,
                "name": assignment.gym.name,
                "role": assignment.role.name,
                "is_owner": False,
                "primary_type": assignment.gym.primary_type,
                "profile_picture_url": assignment.gym.profile_picture_url,
            }


def get_accessible_gyms_for_user(user) -> List[Dict[str, Any]]:
    """
    Returns all gyms accessible to the user, identifying their role/relation.
    Consumes the stream_accessible_gyms_for_user generator.
    """
    return list(stream_accessible_gyms_for_user(user))


def get_gym_by_id(gym_id: str) -> Optional[Gym]:
    """Retrieve gym by UUID or None with owner user selected."""
    try:
        import uuid
        uuid.UUID(str(gym_id))
        return Gym.objects.select_related("owner_user").filter(id=gym_id).first()
    except Exception:
        return None


def get_gym_overview(gym_id: str) -> Optional[Gym]:
    """
    Retrieves complete gym profile overview with primary location preloaded
    and count aggregations for opening hours and gallery assets to prevent N+1 queries.
    """
    import uuid
    from django.db.models import Count, Prefetch
    from apps.gyms.models import GymLocation

    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return None

    return (
        Gym.objects.select_related("owner_user")
        .prefetch_related(
            Prefetch(
                "locations",
                queryset=GymLocation.objects.filter(is_primary=True),
                to_attr="prefetched_primary_locations",
            )
        )
        .annotate(
            annotated_opening_hours_count=Count("opening_hours", distinct=True),
            annotated_gallery_count=Count("gallery_items", distinct=True),
        )
        .filter(id=gym_id)
        .first()
    )


def get_gym_location(gym_id: str):
    """Retrieves the primary map location of the gym with field projections."""
    import uuid
    from apps.gyms.models import GymLocation

    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return None

    return (
        GymLocation.objects.filter(gym_id=gym_id, is_primary=True)
        .only("id", "address", "latitude", "longitude", "city", "country", "postal_code", "is_primary", "updated_at", "gym_id")
        .first()
    )


def get_opening_hours(gym_id: str):
    """Retrieves full 7-day operating schedule ordered by day_of_week with field projection."""
    import uuid
    from apps.gyms.models import GymOpeningHours

    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return GymOpeningHours.objects.none()

    return (
        GymOpeningHours.objects.filter(gym_id=gym_id)
        .only("id", "day_of_week", "start_time", "end_time", "is_closed", "gym_id")
        .order_by("day_of_week")
    )


def list_gallery_items(gym_id: str, category: str = None):
    """Retrieves gallery assets filtered by category with field projections."""
    import uuid
    from apps.gyms.models import GymGallery

    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return GymGallery.objects.none()

    queryset = (
        GymGallery.objects.filter(gym_id=gym_id)
        .only(
            "id",
            "gym_id",
            "media_url",
            "original_url",
            "optimized_url",
            "thumbnail_url",
            "media_type",
            "category",
            "caption",
            "order_index",
            "processing_status",
            "width",
            "height",
            "size_bytes",
            "optimized_size_bytes",
            "created_at",
        )
    )
    if category:
        queryset = queryset.filter(category=category)
    return queryset.order_by("order_index", "-created_at")


def get_gym_settings(gym_id: str) -> Optional[GymSetting]:
    """Retrieves gym settings, auto-creating default settings if not present."""
    import uuid
    from apps.gyms.models import GymSetting

    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return None

    settings_obj = GymSetting.objects.select_related("gym").filter(gym_id=gym_id).first()
    if not settings_obj:
        gym = Gym.objects.filter(id=gym_id).first()
        if gym:
            settings_obj, _ = GymSetting.objects.get_or_create(gym=gym)
    return settings_obj


def list_blocked_users_for_gym(gym_id: str):
    """Lists all users blocked by the given gym."""
    import uuid
    from apps.gyms.models import GymBlockedUser

    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return GymBlockedUser.objects.none()

    return (
        GymBlockedUser.objects.filter(gym_id=gym_id)
        .select_related("user", "user__profile", "blocked_by")
        .order_by("-created_at")
    )


def search_users_to_block_for_gym(gym_id: str, query: str = None, limit: int = 20):
    """Searches Manygym users who can be blocked (excluding gym owner and already blocked users)."""
    import uuid
    from django.db.models import Q
    from apps.users.models import User
    from apps.gyms.models import GymBlockedUser

    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return User.objects.none()

    gym = Gym.objects.filter(id=gym_id).only("id", "owner_user_id").first()
    if not gym:
        return User.objects.none()

    blocked_user_ids = GymBlockedUser.objects.filter(gym_id=gym_id).values_list("user_id", flat=True)

    qs = (
        User.objects.filter(is_active=True)
        .exclude(id=gym.owner_user_id)
        .exclude(id__in=blocked_user_ids)
        .select_related("profile")
    )

    if query and query.strip():
        q = query.strip()
        qs = qs.filter(
            Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )

    return qs.order_by("first_name", "last_name", "email")[:limit]


