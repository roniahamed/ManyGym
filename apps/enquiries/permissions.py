import uuid
from typing import Union, List

from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from common.enums import StaffStatus
from common.exceptions import PermissionDeniedError


def is_gym_staff_or_owner(user, gym: Union[Gym, str, uuid.UUID]) -> bool:
    """
    Checks if user is superuser, gym owner, or an active staff member of the specified gym.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    if isinstance(gym, Gym):
        gym_obj = gym
    else:
        try:
            gym_uuid = gym if isinstance(gym, uuid.UUID) else uuid.UUID(str(gym))
            gym_obj = Gym.objects.only("id", "owner_user_id").filter(id=gym_uuid).first()
        except (ValueError, TypeError, AttributeError):
            return False

    if not gym_obj:
        return False

    if gym_obj.owner_user_id == user.id:
        return True

    return GymStaffAssignment.objects.filter(
        gym=gym_obj, user=user, status=StaffStatus.ACTIVE
    ).exists()


def get_user_staff_gym_ids(user) -> List[uuid.UUID]:
    """
    Returns list of Gym IDs where the user is an owner or active staff member.
    Superusers receive all gym IDs.
    """
    if not user or not user.is_authenticated:
        return []

    if user.is_superuser:
        return list(Gym.objects.values_list("id", flat=True))

    owned_gym_ids = set(Gym.objects.filter(owner_user=user).values_list("id", flat=True))
    staff_gym_ids = set(
        GymStaffAssignment.objects.filter(
            user=user, status=StaffStatus.ACTIVE
        ).values_list("gym_id", flat=True)
    )
    return list(owned_gym_ids | staff_gym_ids)


def check_enquiry_gym_access(user, gym: Union[Gym, str, uuid.UUID], action: str = "view") -> None:
    """
    Raises PermissionDeniedError (403 Forbidden) if user is not an owner or active staff member.
    """
    if not is_gym_staff_or_owner(user, gym):
        raise PermissionDeniedError(
            f"You do not possess staff permission to {action} enquiries for this gym."
        )

