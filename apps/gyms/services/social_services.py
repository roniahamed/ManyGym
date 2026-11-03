import uuid
from typing import Optional, Tuple
from django.db import transaction
from apps.gyms.models import Gym, GymFollow, GymBlockedUser
from apps.access_control.models import GymStaffAssignment
from apps.users.models import User
from common.enums import StaffStatus
from common.exceptions import DomainValidationError, ResourceNotFoundError, PermissionDeniedError


@transaction.atomic
def follow_gym(user: User, gym_id) -> Tuple[GymFollow, bool]:
    """
    Enables an authenticated user to follow a Gym entity.
    Checks:
    - Target gym exists, is not deleted, and is not deactivated.
    - User is not blocked by the gym.
    Returns:
    - (GymFollow instance, created: bool)
    """
    if isinstance(gym_id, Gym):
        gym = gym_id
    else:
        try:
            gym_uuid = uuid.UUID(str(gym_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid gym ID.")

        try:
            gym = Gym.objects.select_related("settings").get(id=gym_uuid)
        except Gym.DoesNotExist:
            raise ResourceNotFoundError("Gym not found.")

    settings_obj = gym.get_settings()
    if settings_obj.is_deleted:
        raise ResourceNotFoundError("Gym not found.")
    if settings_obj.is_deactivated:
        raise DomainValidationError("This gym is currently inactive or unavailable.")

    is_owner_or_staff = (
        gym.owner_user_id == user.id
        or user.is_superuser
        or GymStaffAssignment.objects.filter(gym=gym, user=user, status=StaffStatus.ACTIVE).exists()
    )
    if not settings_obj.is_published and not is_owner_or_staff:
        raise ResourceNotFoundError("Gym not found.")

    # Check if user is blocked by gym
    if GymBlockedUser.objects.filter(gym=gym, user=user).exists():
        raise PermissionDeniedError("You are blocked from following this gym.")

    follow_instance, created = GymFollow.objects.get_or_create(
        user=user,
        gym=gym,
    )
    return follow_instance, created


@transaction.atomic
def unfollow_gym(user: User, gym_id) -> bool:
    """
    Unfollows a gym previously followed by user.
    """
    if isinstance(gym_id, Gym):
        gym_uuid = gym_id.id
    else:
        try:
            gym_uuid = uuid.UUID(str(gym_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid gym ID.")

    deleted_count, _ = GymFollow.objects.filter(user=user, gym_id=gym_uuid).delete()
    if deleted_count == 0:
        raise ResourceNotFoundError("You are not currently following this gym.")

    return True


def auto_follow_gym_for_member(user: User, gym: Gym) -> Optional[GymFollow]:
    """
    Automatically follows a gym when a member connects their user account.
    Gym members can unfollow later at their own discretion.
    Uses single-query atomic insert with ON CONFLICT DO NOTHING to eliminate savepoints and extra queries.
    """
    if not user or not gym:
        return None
    created = GymFollow.objects.bulk_create([GymFollow(user=user, gym=gym)], ignore_conflicts=True)
    return created[0] if created else None


@transaction.atomic
def send_member_joining_request(
    user: User,
    gym_id,
    interested_plan_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """
    Submits a member joining request from an authenticated Manygym user to a gym.
    Delegates to the central member request service.
    """
    from apps.members.services.request_services import create_member_request
    return create_member_request(
        user=user,
        gym_id=gym_id,
        interested_plan_id=interested_plan_id,
        notes=notes,
    )


def get_member_joining_request_status(user: User, gym_id) -> dict:
    """
    Returns user eligibility and current status for joining the specified gym.
    """
    from apps.members.services.request_services import get_member_joining_request_status as _get_status
    return _get_status(user=user, gym_id=gym_id)
