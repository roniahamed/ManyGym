from typing import List, Dict, Any, Iterator
from apps.access_control.models import Permission, Role, GymStaffAssignment
from apps.gyms.models import Gym


def stream_permissions() -> Iterator[Permission]:
    """
    Generator yielding system permissions using queryset iterator to minimize memory overhead.
    """
    yield from (
        Permission.objects.all()
        .only("id", "topic", "scope_code", "name", "description")
        .order_by("topic", "name")
        .iterator(chunk_size=100)
    )


def list_permissions_by_topic() -> Dict[str, List[Dict[str, Any]]]:
    """
    Returns system permissions organized by topic for UI checkboxes.
    Uses generator iterator to stream results without loading all model instances into query cache.
    """
    result: Dict[str, List[Dict[str, Any]]] = {}
    for perm in stream_permissions():
        if perm.topic not in result:
            result[perm.topic] = []
        result[perm.topic].append({
            "id": str(perm.id),
            "scope_code": perm.scope_code,
            "name": perm.name,
            "description": perm.description,
        })
    return result


def models_q_gym(gym_id: str):
    from django.db.models import Q
    import uuid
    try:
        uuid_obj = uuid.UUID(str(gym_id))
        return Q(gym__isnull=True) | Q(gym_id=uuid_obj)
    except (ValueError, TypeError, AttributeError):
        return Q(gym__isnull=True)


def list_gym_roles(gym_id: str = None):
    """
    Returns global system standard roles plus gym-specific custom roles.
    Uses select_related('gym') to prevent N+1 queries when accessing role.gym (e.g. in RoleSerializer).
    Uses prefetch_related('permissions') to efficiently batch load ManyToMany permissions.
    """
    qs = Role.objects.select_related("gym").prefetch_related("permissions")
    if gym_id:
        return qs.filter(models_q_gym(gym_id)).order_by("is_custom", "name")
    return qs.filter(gym__isnull=True).order_by("name")


def list_gym_staff(gym_id: str):
    """
    Returns all staff members assigned to a gym with user, profile, role, gym, and permissions preloaded.
    Eliminates N+1 query overhead during nested StaffAssignmentSerializer serialization.
    """
    return (
        GymStaffAssignment.objects.filter(gym_id=gym_id)
        .select_related("user__profile", "role__gym", "gym")
        .prefetch_related("role__permissions")
        .order_by("-invited_at")
    )


def get_user_gym_scopes(user, gym: Gym) -> List[str]:
    """
    Calculates active permission scope codes for a user in the given gym context.
    - If user is the Gym Owner: returns ALL system scopes via single values_list.
    - If user has staff assignment: returns distinct scopes via a single optimized SQL join.
    """
    if gym.owner_user_id == user.id or user.is_superuser:
        return list(Permission.objects.values_list("scope_code", flat=True))

    scopes = (
        Permission.objects.filter(
            roles__staff_assignments__user=user,
            roles__staff_assignments__gym=gym,
            roles__staff_assignments__status="active",
        )
        .distinct()
        .values_list("scope_code", flat=True)
    )

    return list(scopes)

