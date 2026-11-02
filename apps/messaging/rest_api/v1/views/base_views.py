from typing import Optional
import uuid

from apps.gyms.models import Gym


def resolve_gym_context(request) -> Optional[Gym]:
    """Helper to determine target gym from gym context header, query parameter, or request body."""
    gym_id = (
        request.query_params.get("gym_id")
        or getattr(request, "gym_id", None)
        or (request.data.get("gym_id") if isinstance(request.data, dict) else None)
    )
    if not gym_id:
        return None
    try:
        uuid_obj = uuid.UUID(str(gym_id))
        return Gym.objects.filter(id=uuid_obj).first()
    except (ValueError, TypeError, AttributeError):
        return None
