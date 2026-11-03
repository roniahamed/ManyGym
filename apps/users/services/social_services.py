import uuid
from django.db import transaction

from apps.users.models import User, UserFollow
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)


@transaction.atomic
def follow_user(follower: User, target_user_id) -> tuple[UserFollow, bool]:
    """
    Follows a target user if target user is active, not self, and not private.
    Returns (UserFollow, created: bool).
    """
    if isinstance(target_user_id, User):
        target_user = target_user_id
        target_uuid = target_user.id
    else:
        try:
            target_uuid = uuid.UUID(str(target_user_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid target user ID.")

        if follower.id == target_uuid:
            raise DomainValidationError("You cannot follow yourself.")

        try:
            target_user = User.objects.select_related("profile").get(id=target_uuid, is_active=True)
        except User.DoesNotExist:
            raise ResourceNotFoundError("Target user not found or is inactive.")

    if follower.id == target_uuid:
        raise DomainValidationError("You cannot follow yourself.")

    if not getattr(target_user, "is_active", True):
        raise ResourceNotFoundError("Target user not found or is inactive.")

    setting = target_user.get_settings()
    if setting.is_deleted:
        raise ResourceNotFoundError("Target user not found.")
    if setting.is_deactivated:
        raise DomainValidationError("This user account is deactivated.")

    from apps.users.models import UserBlockedUser
    if UserBlockedUser.objects.filter(blocker=target_user, blocked_user=follower).exists():
        raise PermissionDeniedError("You have been blocked by this user.")
    if UserBlockedUser.objects.filter(blocker=follower, blocked_user=target_user).exists():
        raise DomainValidationError("You cannot follow a user you have blocked. Unblock them first.")

    profile = getattr(target_user, "profile", None)
    if profile and profile.is_private:
        raise PermissionDeniedError("This user account is private.")

    follow_instance, created = UserFollow.objects.get_or_create(
        follower=follower,
        followed_user=target_user,
    )
    return follow_instance, created


@transaction.atomic
def unfollow_user(follower: User, target_user_id) -> bool:
    """
    Unfollows a target user.
    """
    try:
        target_uuid = uuid.UUID(str(target_user_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid target user ID.")

    deleted_count, _ = UserFollow.objects.filter(
        follower=follower,
        followed_user_id=target_uuid,
    ).delete()

    if deleted_count == 0:
        raise ResourceNotFoundError("You are not currently following this user.")

    return True
