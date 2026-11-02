import uuid

from apps.gyms.models import Gym
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)


def resolve_routine_gym(request) -> Gym:
    """Helper to determine target gym from query param, active JWT context, or request body."""
    cached = getattr(request, "_resolved_gym", None)
    if cached is not None:
        return cached

    gym_id = (
        request.query_params.get("gym_id")
        or getattr(request, "gym_id", None)
        or (request.data.get("gym_id") if isinstance(request.data, dict) else None)
    )
    if not gym_id:
        raise DomainValidationError("An active Gym context token or 'gym_id' parameter is required.")
    try:
        uuid.UUID(str(gym_id))
        gym = Gym.objects.only("id", "owner_user_id", "name", "timezone").get(id=gym_id)
    except (Gym.DoesNotExist, ValueError, AttributeError):
        raise ResourceNotFoundError("Gym not found.")
    request._resolved_gym = gym
    return gym


def check_routine_permission(request, gym: Gym, required_scopes: list[str]) -> None:
    """Enforces gym owner, superuser, or required permission scopes for Routine Templates & Workouts."""
    if gym.owner_user_id == request.user.id or request.user.is_superuser:
        return
    scopes = getattr(request, "scopes", [])

    # 'routines:manage' supersedes all routine operations
    if "routines:manage" in scopes:
        return

    # Check if any of the accepted scopes are in user's granted scopes
    for req_scope in required_scopes:
        if req_scope in scopes:
            return

    scope_names = " or ".join(f"'{s}'" for s in required_scopes)
    raise PermissionDeniedError(f"You do not possess the required {scope_names} scope for this gym operation.")
