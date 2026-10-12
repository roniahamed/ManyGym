from typing import List, Dict, Any
from apps.access_control.models import Permission, Role, GymStaffAssignment
from apps.gyms.models import Gym


def list_permissions_by_topic() -> Dict[str, List[Dict[str, Any]]]:
    """
    Returns system permissions organized by topic for UI checkboxes.
    """
    permissions = Permission.objects.all().order_by("topic", "name")
    result: Dict[str, List[Dict[str, Any]]] = {}
    for perm in permissions:
        if perm.topic not in result:
            result[perm.topic] = []
        result[perm.topic].append({
            "id": str(perm.id),
            "scope_code": perm.scope_code,
            "name": perm.name,
            "description": perm.description,
        })
    return result


def list_gym_roles(gym_id: str = None):
    """
    Returns global system standard roles plus gym-specific custom roles.
    """
    if gym_id:
        return Role.objects.filter(models_q_gym(gym_id)).prefetch_related("permissions").order_by("is_custom", "name")
    return Role.objects.filter(gym__isnull=True).prefetch_related("permissions").order_by("name")


def models_q_gym(gym_id: str):
    from django.db.models import Q
    return Q(gym__isnull=True) | Q(gym_id=gym_id)


def list_gym_staff(gym_id: str):
    """
    Returns all staff members assigned to a gym with user and role details.
    """
    return (
        GymStaffAssignment.objects.filter(gym_id=gym_id)
        .select_related("user", "role", "gym")
        .order_by("-invited_at")
    )


def get_user_gym_scopes(user, gym: Gym) -> List[str]:
    """
    Calculates active permission scope codes for a user in the given gym context.
    - If user is the Gym Owner: returns ALL system scopes.
    - If user has staff assignment: returns union of scopes for their assigned active roles.
    """
    if gym.owner_user_id == user.id or user.is_superuser:
        return list(Permission.objects.values_list("scope_code", flat=True))

    assignments = GymStaffAssignment.objects.filter(
        user=user,
        gym=gym,
        status="active",
    ).prefetch_related("role__permissions")

    scopes = set()
    for assignment in assignments:
        for perm in assignment.role.permissions.all():
            scopes.add(perm.scope_code)

    return list(scopes)
