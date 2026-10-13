from typing import List, Dict, Any, Optional, Iterator
from apps.gyms.models import Gym
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
    """Retrieves complete gym profile overview with primary location preloaded."""
    return (
        Gym.objects.select_related("owner_user")
        .prefetch_related("locations")
        .filter(id=gym_id)
        .first()
    )


def get_gym_location(gym_id: str):
    """Retrieves the primary map location of the gym."""
    from apps.gyms.models import GymLocation
    return GymLocation.objects.filter(gym_id=gym_id, is_primary=True).first()


def get_opening_hours(gym_id: str):
    """Retrieves full 7-day operating schedule ordered by day_of_week."""
    from apps.gyms.models import GymOpeningHours
    return GymOpeningHours.objects.filter(gym_id=gym_id).order_by("day_of_week")


def list_gallery_items(gym_id: str, category: str = None):
    """Retrieves gallery assets filtered by category and ordered by order_index."""
    from apps.gyms.models import GymGallery
    queryset = GymGallery.objects.filter(gym_id=gym_id)
    if category:
        queryset = queryset.filter(category=category)
    return queryset.order_by("order_index", "-created_at")


