import uuid
from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)


def resolve_member_gym(request, gym_id=None) -> Gym:
    """Helper to determine target gym from explicit arg, URL kwarg, query param, active JWT context, or request body."""
    cached = getattr(request, "_resolved_gym", None)
    if cached is not None and (gym_id is None or str(cached.id) == str(gym_id)):
        return cached

    url_kwarg_gym_id = None
    if hasattr(request, "parser_context") and isinstance(request.parser_context, dict):
        url_kwarg_gym_id = request.parser_context.get("kwargs", {}).get("gym_id")

    body_gym_id = None
    if getattr(request, "method", "") in ("POST", "PUT", "PATCH"):
        try:
            if hasattr(request, "data") and isinstance(request.data, dict):
                body_gym_id = request.data.get("gym_id")
        except Exception:
            body_gym_id = None

    target_id = (
        gym_id
        or url_kwarg_gym_id
        or (request.query_params.get("gym_id") if hasattr(request, "query_params") else None)
        or getattr(request, "gym_id", None)
        or body_gym_id
    )
    if not target_id:
        raise DomainValidationError("An active Gym context token or 'gym_id' parameter is required.")
    try:
        uuid.UUID(str(target_id))
        gym = Gym.objects.only("id", "owner_user_id", "name", "timezone").get(id=target_id)
    except (Gym.DoesNotExist, ValueError, AttributeError):
        raise ResourceNotFoundError("Gym not found.")
    request._resolved_gym = gym
    return gym


def check_member_permission(request, gym: Gym, required_scope: str = None) -> None:
    """Enforces gym owner or required permission scope."""
    if gym.owner_user_id == request.user.id or request.user.is_superuser:
        return
    scopes = getattr(request, "scopes", None)
    if not scopes:
        staff = (
            GymStaffAssignment.objects.filter(gym=gym, user=request.user, status="active")
            .select_related("role")
            .first()
        )
        if staff and staff.role:
            scopes = list(staff.role.permissions.values_list("scope_code", flat=True))
        else:
            scopes = []
        request.scopes = scopes

    if required_scope and required_scope not in scopes:
        raise PermissionDeniedError(f"You do not possess the required '{required_scope}' scope for this gym operation.")
