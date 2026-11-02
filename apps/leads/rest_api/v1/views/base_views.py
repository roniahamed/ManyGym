import uuid
from apps.gyms.models import Gym
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)


def resolve_lead_gym(request) -> Gym:
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


def check_lead_permission(request, gym: Gym, required_scope: str = None) -> None:
    """Enforces gym owner or required permission scope for Leads CRM."""
    if gym.owner_user_id == request.user.id or request.user.is_superuser:
        return
    scopes = getattr(request, "scopes", [])
    # 'leads:manage' supersedes 'leads:read'
    if required_scope == "leads:read":
        if "leads:read" in scopes or "leads:manage" in scopes:
            return
    elif required_scope and required_scope in scopes:
        return

    raise PermissionDeniedError(f"You do not possess the required '{required_scope}' scope for this gym operation.")
