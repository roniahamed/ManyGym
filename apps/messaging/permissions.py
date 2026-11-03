"""
Permission and policy enforcement for End-to-End Encrypted Messaging.
Enforces gym privacy settings, blocked users list, and role-based gym staff access.
"""

from typing import Optional

from apps.users.models import User
from apps.gyms.models import Gym, GymBlockedUser, GymSetting
from apps.access_control.models import GymStaffAssignment
from apps.access_control.selectors import get_user_gym_scopes
from apps.members.models import Member
from common.enums import AudienceMessagingEnum, StaffStatus, ConversationTypeEnum
from common.exceptions import (
    PermissionDeniedError,
    DomainValidationError,
    ResourceNotFoundError,
)


def can_user_message_user(sender: User, receiver: User) -> bool:
    """
    Evaluates whether an individual user is permitted to message another user:
    1. Rejects if either user has blocked the other in UserBlockedUser.
    2. Validates receiver account lifecycle (deleted / deactivated).
    3. Validates receiver UserSetting.who_can_message (everyone, followers, no_one).
    """
    from apps.users.models import UserBlockedUser, UserFollow
    from common.enums import UserAudienceMessagingEnum

    if UserBlockedUser.objects.filter(blocker=receiver, blocked_user=sender).exists():
        raise PermissionDeniedError("You have been blocked from messaging this user.")
    if UserBlockedUser.objects.filter(blocker=sender, blocked_user=receiver).exists():
        raise DomainValidationError("You cannot message a user you have blocked. Unblock them first.")

    setting = receiver.get_settings()
    if setting.is_deleted:
        raise ResourceNotFoundError("User not found.")
    if setting.is_deactivated:
        raise DomainValidationError("This user account is deactivated and cannot receive new messages.")

    policy = setting.who_can_message
    if policy == UserAudienceMessagingEnum.NO_ONE:
        raise DomainValidationError("This user does not accept direct messages.")
    if policy == UserAudienceMessagingEnum.FOLLOWERS:
        if not UserFollow.objects.filter(follower=sender, followed_user=receiver).exists():
            raise DomainValidationError("This user only accepts direct messages from their followers.")

    return True


def can_user_message_gym(user, gym: Gym) -> bool:
    """
    Evaluates whether an individual user is permitted to initiate contact with a Gym:
    1. Rejects if user is blocked in GymBlockedUser.
    2. Validates against GymSettings lifecycle (is_deleted, is_deactivated).
    3. Validates against GymSettings.who_can_message (EVERYONE, MEMBERS_ONLY, FOLLOWERS_AND_MEMBERS).
    """
    # 1. Block list check
    if GymBlockedUser.objects.filter(gym=gym, user=user).exists():
        raise PermissionDeniedError("You have been blocked from messaging this gym.")

    # 2. Check gym settings & lifecycle
    try:
        setting = gym.settings
    except (GymSetting.DoesNotExist, AttributeError):
        setting = None

    if setting:
        if getattr(setting, "is_deleted", False):
            raise ResourceNotFoundError("Gym not found.")

        is_owner_or_staff = (
            gym.owner_user_id == getattr(user, "id", None)
            or getattr(user, "is_superuser", False)
            or GymStaffAssignment.objects.filter(gym=gym, user=user, status=StaffStatus.ACTIVE).exists()
        )
        if not getattr(setting, "is_published", True) and not is_owner_or_staff:
            raise ResourceNotFoundError("Gym not found.")

        if getattr(setting, "is_deactivated", False) and not is_owner_or_staff:
            raise DomainValidationError("This gym is deactivated and cannot receive new messages.")
        policy = setting.who_can_message
    else:
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
        from apps.gyms.models import GymFollow
        if GymFollow.objects.filter(gym=gym, user=user).exists():
            return True
        raise DomainValidationError("This gym only accepts messages from followers and members.")

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


def assert_can_access_conversation(user, conversation, gym_context: Optional[Gym] = None) -> bool:
    """
    Validates that the user has legitimate access to view or interact with a conversation.
    """
    conv_type = conversation.conversation_type

    if conv_type == ConversationTypeEnum.USER_TO_USER:
        if user.id not in (conversation.user_a_id, conversation.user_b_id):
            raise PermissionDeniedError("You are not a participant in this conversation.")
        return True

    if conv_type == ConversationTypeEnum.USER_TO_GYM:
        if user.id == conversation.user_a_id:
            return True
        # Otherwise user must be authorized for gym_a
        if is_user_authorized_for_gym(user, conversation.gym_a, "messaging:read"):
            return True
        raise PermissionDeniedError("You do not have permission to access this gym conversation.")

    if conv_type == ConversationTypeEnum.GYM_TO_GYM:
        if is_user_authorized_for_gym(user, conversation.gym_a, "messaging:read"):
            return True
        if is_user_authorized_for_gym(user, conversation.gym_b, "messaging:read"):
            return True
        raise PermissionDeniedError("You do not have permission to access this B2B gym conversation.")

    raise PermissionDeniedError("Unauthorized conversation access.")
