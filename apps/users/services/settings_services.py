import uuid
import logging
from typing import Optional, Any
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from apps.users.models import User, UserSetting, UserBlockedUser, UserFollow
from apps.authentication.models import AuthToken
from common.enums import UserStatus
from common.exceptions import DomainValidationError, ResourceNotFoundError, PermissionDeniedError

logger = logging.getLogger(__name__)


def get_or_create_user_settings(user: User) -> UserSetting:
    """
    Retrieves existing settings or auto-provisions default settings for the user.
    """
    settings_obj, _ = UserSetting.objects.get_or_create(user=user)
    return settings_obj


@transaction.atomic
def update_user_settings(user: User, **data: Any) -> UserSetting:
    """
    Updates user configuration fields across Display Preferences, Audience Visibility,
    and Profile Privacy.
    """
    settings_obj = get_or_create_user_settings(user)

    if "who_can_follow_me" in data and ("who_can_follow" not in data or data["who_can_follow"] is None):
        data["who_can_follow"] = data["who_can_follow_me"]
    data.pop("who_can_follow_me", None)

    allowed_fields = {
        "language",
        "video_autoplay",
        "dark_mode",
        "who_can_follow",
        "who_can_message",
        "who_can_see_followers",
        "who_can_see_following",
        "require_follow_approval",
        "is_private",
    }

    settings_dirty = False
    for field, val in data.items():
        if field not in allowed_fields or val is None:
            continue

        if field == "is_private":
            if hasattr(user, "profile") and user.profile:
                user.profile.is_private = bool(val)
                user.profile.save(update_fields=["is_private"])
        else:
            setattr(settings_obj, field, val)
            settings_dirty = True

    if settings_dirty:
        update_fields = [f for f in data if f in allowed_fields and f != "is_private" and data[f] is not None]
        update_fields.append("updated_at")
        settings_obj.save(update_fields=update_fields)
    else:
        settings_obj.save(update_fields=["updated_at"])

    logger.info("Updated settings for user %s (%s)", user.email, user.id)

    # Re-fetch with select_related to avoid N+1 lazy loads in response serializer
    return (
        UserSetting.objects.select_related("user", "user__profile")
        .get(pk=settings_obj.pk)
    )


@transaction.atomic
def block_user_for_user(
    blocker: User,
    user_id: str,
    reason: Optional[str] = None,
) -> UserBlockedUser:
    """
    Blocks another user from interacting with the current user.
    Validates user existence, prevents self-blocking, and deletes mutual follow records.
    """
    try:
        uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid user_id.")

    target_user = User.objects.filter(id=user_id).select_related("profile").first()
    if not target_user:
        raise ResourceNotFoundError("User to block not found.")

    if target_user.id == blocker.id:
        raise DomainValidationError("You cannot block yourself.")

    cleaned_reason = None
    if reason is not None:
        if not isinstance(reason, str):
            raise DomainValidationError("Reason must be a valid string.")
        cleaned_reason = reason.strip()
        if "\x00" in cleaned_reason:
            raise DomainValidationError("Null characters are not allowed.")
        if len(cleaned_reason) > 255:
            raise DomainValidationError("Reason cannot exceed 255 characters.")

    blocked_obj, created = UserBlockedUser.objects.get_or_create(
        blocker=blocker,
        blocked_user=target_user,
        defaults={
            "reason": cleaned_reason,
        },
    )
    blocked_obj.blocked_user = target_user

    # Automatically remove follow relations in both directions in a single query
    UserFollow.objects.filter(
        Q(follower=blocker, followed_user=target_user)
        | Q(follower=target_user, followed_user=blocker)
    ).delete()

    if created:
        logger.info("User %s blocked user %s", blocker.email, target_user.email)
    return blocked_obj


@transaction.atomic
def unblock_user_for_user(blocker: User, user_id: str) -> bool:
    """
    Unblocks a previously blocked user account.
    """
    try:
        uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid user_id.")

    deleted_count, _ = UserBlockedUser.objects.filter(blocker=blocker, blocked_user_id=user_id).delete()
    if deleted_count == 0:
        raise ResourceNotFoundError("Blocked user not found.")

    logger.info("User %s unblocked user %s", blocker.email, user_id)
    return True


@transaction.atomic
def apply_user_access_control_action(
    user: User,
    action: str,
    password: Optional[str] = None,
    confirmation: Optional[str] = None,
) -> UserSetting:
    """
    Executes profile lifecycle transitions (deactivate, reactivate, delete, restore).
    For 'delete':
    - Requires password verification.
    - Requires confirmation text 'delete'.
    - Marks user as soft-deleted and revokes all active auth sessions.
    For 'deactivate':
    - Marks user as deactivated and revokes auth sessions.
    For 'reactivate' / 'restore':
    - Restores account to active status.
    """
    settings_obj = get_or_create_user_settings(user)

    if action == "delete":
        if not password or not user.check_password(password):
            raise DomainValidationError("Invalid password confirmation.")
        if not confirmation or confirmation.strip().lower() != "delete":
            raise DomainValidationError("Please type 'delete' to confirm deletion.")

        settings_obj.soft_delete()
        settings_obj.save()

        user.status = UserStatus.DELETED
        user.is_active = False
        user.save(update_fields=["status", "is_active", "updated_at"])

        # Revoke all session tokens
        AuthToken.objects.filter(user=user).delete()
        logger.info("Soft-deleted user account %s (%s)", user.email, user.id)
        return UserSetting.objects.select_related("user", "user__profile").get(pk=settings_obj.pk)

    elif action == "restore":
        if not password or not user.check_password(password):
            raise DomainValidationError("Invalid password confirmation.")

        if settings_obj.deleted_at:
            from datetime import timedelta
            if timezone.now() - settings_obj.deleted_at > timedelta(hours=24):
                raise DomainValidationError("This account has been permanently deleted and cannot be restored.")

        settings_obj.restore()
        settings_obj.save()

        user.status = UserStatus.ACTIVE
        user.is_active = True
        user.save(update_fields=["status", "is_active", "updated_at"])
        logger.info("Restored user account %s (%s)", user.email, user.id)
        return UserSetting.objects.select_related("user", "user__profile").get(pk=settings_obj.pk)

    elif action == "deactivate":
        settings_obj.deactivate()
        settings_obj.save()

        user.status = UserStatus.DEACTIVATED
        user.is_active = False
        user.save(update_fields=["status", "is_active", "updated_at"])

        # Invalidate active auth sessions
        AuthToken.objects.filter(user=user).delete()
        logger.info("Deactivated user account %s (%s)", user.email, user.id)
        return UserSetting.objects.select_related("user", "user__profile").get(pk=settings_obj.pk)

    elif action == "reactivate":
        settings_obj.reactivate()
        settings_obj.save()

        user.status = UserStatus.ACTIVE
        user.is_active = True
        user.save(update_fields=["status", "is_active", "updated_at"])
        logger.info("Reactivated user account %s (%s)", user.email, user.id)
        return UserSetting.objects.select_related("user", "user__profile").get(pk=settings_obj.pk)

    else:
        raise DomainValidationError(f"Invalid access control action '{action}'.")

