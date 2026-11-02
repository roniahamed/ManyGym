import uuid
from apps.gyms.models import Gym
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
)


def resolve_request_gym(request) -> Gym:
    """Helper to determine the target gym from active context or query param."""
    gym_id = request.query_params.get("gym_id") or getattr(request, "gym_id", None)
    if not gym_id:
        raise DomainValidationError("An active Gym context token or 'gym_id' parameter is required for this operation.")
    try:
        uuid.UUID(str(gym_id))
        gym = Gym.objects.select_related("owner_user").get(id=gym_id)
    except Exception:
        raise ResourceNotFoundError("Gym not found.")
    return gym
