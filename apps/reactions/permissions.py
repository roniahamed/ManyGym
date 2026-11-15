from typing import Optional
from rest_framework.permissions import BasePermission

from apps.access_control.models import GymStaffAssignment
from apps.gyms.models import Gym
from apps.users.models import User
from common.enums import StaffStatus
from common.exceptions import PermissionDeniedError


class CanReactAsGymPermission(BasePermission):
    """
    Ensures that when a user attempts to react on behalf of a Gym,
    they are either the owner, a superuser, or an active staff member of that gym.
    """

    def has_object_permission(self, request, view, obj) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if hasattr(obj, "gym") and obj.gym:
            return self.check_gym_staff_or_owner(user, obj.gym)
        return True

    @staticmethod
    def check_gym_staff_or_owner(user: User, gym: Gym) -> bool:
        if gym.owner_user_id == user.id or user.is_superuser:
            return True
        return GymStaffAssignment.objects.filter(
            gym=gym,
            user=user,
            status=StaffStatus.ACTIVE,
        ).exists()


def check_reaction_actor_permission(actor_user: User, gym: Optional[Gym] = None) -> None:
    """Helper function to validate actor authorization before writing a reaction."""
    if not actor_user or not actor_user.is_authenticated:
        raise PermissionDeniedError("Authentication credentials were not provided.")

    setting = actor_user.get_settings()
    if setting.is_deleted or setting.is_deactivated:
        raise PermissionDeniedError("Your account is deactivated or deleted.")

    if gym is not None:
        if not CanReactAsGymPermission.check_gym_staff_or_owner(actor_user, gym):
            raise PermissionDeniedError("You do not have permission to act on behalf of this gym.")

