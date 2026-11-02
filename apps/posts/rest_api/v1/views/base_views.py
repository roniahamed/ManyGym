import uuid
from django.db.models import Q
from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from apps.members.models import Member
from common.enums import StaffStatus
from common.exceptions import DomainValidationError, ResourceNotFoundError, PermissionDeniedError


def resolve_post_gym(request) -> Gym:
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


def check_user_is_member_or_staff(request, gym: Gym) -> bool:
    """Returns True if the requesting user is the gym owner, staff member, or active member."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return False

    if gym.owner_user_id == user.id or user.is_superuser:
        return True

    # Active staff check
    if GymStaffAssignment.objects.filter(gym=gym, user=user, status=StaffStatus.ACTIVE).exists():
        return True

    # Active gym member check
    if Member.objects.filter(gym=gym).filter(Q(email=user.email) | Q(user=user)).exists():
        return True

    return False


def check_post_management_permission(request, gym: Gym) -> None:
    """Enforces that only gym owner, superuser, or staff with 'posts:manage' scope can mutate posts."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        raise PermissionDeniedError("Authentication credentials were not provided.")

    if gym.owner_user_id == user.id or user.is_superuser:
        return

    assignment = GymStaffAssignment.objects.filter(
        gym=gym,
        user=user,
        status=StaffStatus.ACTIVE,
    ).first()

    if not assignment:
        raise PermissionDeniedError("You are not an active staff member of this gym.")

    if not assignment.role:
        raise PermissionDeniedError("You do not have permission to manage community posts.")

    has_perm = assignment.role.permissions.filter(scope_code="posts:manage").exists()
    if not has_perm:
        raise PermissionDeniedError("Missing required permission scope 'posts:manage'.")
