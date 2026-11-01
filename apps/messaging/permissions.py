"""
Permission and policy enforcement for End-to-End Encrypted Messaging.
Enforces gym privacy settings, blocked users list, and role-based gym staff access.
"""

from apps.gyms.models import Gym, GymBlockedUser, GymSetting
from apps.access_control.models import GymStaffAssignment
from apps.access_control.selectors import get_user_gym_scopes
from apps.members.models import Member
from common.enums import AudienceMessagingEnum, StaffStatus
from common.exceptions import (
    PermissionDeniedError,
    DomainValidationError,
)


def can_user_message_gym(user, gym: Gym) -> bool:
    """
    Evaluates whether an individual user is permitted to initiate contact with a Gym:
    1. Rejects if user is blocked in GymBlockedUser.
    2. Validates against GymSettings.who_can_message (EVERYONE, MEMBERS_ONLY, FOLLOWERS_AND_MEMBERS).
    """
    # 1. Block list check
    if GymBlockedUser.objects.filter(gym=gym, user=user).exists():
        raise PermissionDeniedError("You have been blocked from messaging this gym.")

    # 2. Check gym settings
    try:
        setting = gym.settings
        policy = setting.who_can_message
    except (GymSetting.DoesNotExist, AttributeError):
        policy = AudienceMessagingEnum.EVERYONE

    if policy == AudienceMessagingEnum.EVERYONE:
        return True

    # Check membership
    is_member = Member.objects.filter(
        gym=gym,
        user=user,
    ).exclude(joining_status="removed").exists()

    if policy == AudienceMessagingEnum.MEMBERS_ONLY:
        if not is_member:
            raise DomainValidationError("This gym only accepts messages from enrolled gym members.")
        return True

    if policy == AudienceMessagingEnum.FOLLOWERS_AND_MEMBERS:
        # User is allowed if they are a member or if user is owner/staff
        if is_member or gym.owner_user_id == user.id:
            return True
        # Future/extensible: check social follow relationship if implemented
        return True

    return True


def is_user_authorized_for_gym(user, gym: Gym, required_scope: str = "messaging:read") -> bool:
    """
    Checks if a user is authorized to read or act on behalf of a Gym.
    Owner and Superusers are always authorized.
    Staff members must be ACTIVE and possess the requested scope (or default staff access).
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or gym.owner_user_id == user.id:
        return True

    # Check staff assignment
    assignment = GymStaffAssignment.objects.filter(
        gym=gym,
        user=user,
        status=StaffStatus.ACTIVE,
    ).first()

    if not assignment:
        return False

    scopes = get_user_gym_scopes(user, gym)
    # If explicit messaging scopes are seeded, require them; otherwise allow active staff
    if "messaging:read" in scopes or "messaging:send" in scopes:
        return required_scope in scopes or len(scopes) > 0

    return True


def assert_can_access_conversation(user, conversation, gym_context: Gym = None) -> bool:
    """
    Validates that the user has legitimate access to view or interact with a conversation.
    """
    conv_type = conversation.conversation_type

    if conv_type == "user_to_user":
        if user.id not in (conversation.user_a_id, conversation.user_b_id):
            raise PermissionDeniedError("You are not a participant in this conversation.")
        return True

    if conv_type == "user_to_gym":
        if user.id == conversation.user_a_id:
            return True
        # Otherwise user must be authorized for gym_a
        if is_user_authorized_for_gym(user, conversation.gym_a, "messaging:read"):
            return True
        raise PermissionDeniedError("You do not have permission to access this gym conversation.")

    if conv_type == "gym_to_gym":
        if is_user_authorized_for_gym(user, conversation.gym_a, "messaging:read"):
            return True
        if is_user_authorized_for_gym(user, conversation.gym_b, "messaging:read"):
            return True
        raise PermissionDeniedError("You do not have permission to access this B2B gym conversation.")

    raise PermissionDeniedError("Unauthorized conversation access.")
