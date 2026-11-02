from apps.gyms.models import Gym
from common.exceptions import DomainValidationError, ResourceNotFoundError, PermissionDeniedError


def resolve_gym_context(request) -> Gym:
    """Helper to determine the target gym from active token context or query param, with request-level caching."""
    cached = getattr(request, "_resolved_gym", None)
    if cached is not None:
        return cached

    gym_id = getattr(request, "gym_id", None) or request.query_params.get("gym_id")
    if not gym_id:
        raise DomainValidationError("An active Gym context token or 'gym_id' query parameter is required.")
    try:
        import uuid
        uuid.UUID(str(gym_id))
        gym = Gym.objects.only("id", "owner_user_id", "name", "timezone").get(id=gym_id)
    except (Gym.DoesNotExist, ValueError, AttributeError):
        raise ResourceNotFoundError("Gym not found.")
    request._resolved_gym = gym
    return gym


def check_gym_permission(request, gym: Gym, required_scope: str = None) -> None:
    """Enforces owner or scope-based authorization."""
    if gym.owner_user_id == request.user.id or request.user.is_superuser:
        return
    scopes = getattr(request, "scopes", [])
    if required_scope and required_scope not in scopes:
        raise PermissionDeniedError(f"You do not possess the required '{required_scope}' scope for this gym operation.")
