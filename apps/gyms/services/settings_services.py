import uuid
import logging
from typing import Optional, Any
from django.db import transaction
from apps.gyms.models import Gym, GymSetting, GymBlockedUser, GymFollow
from apps.users.models import User
from common.exceptions import DomainValidationError, ResourceNotFoundError, PermissionDeniedError

logger = logging.getLogger(__name__)


def get_or_create_gym_settings(gym: Gym) -> GymSetting:
    """
    Retrieves existing settings or auto-provisions default settings for the gym.
    """
    settings_obj, _ = GymSetting.objects.get_or_create(gym=gym)
    return settings_obj


@transaction.atomic
def update_gym_settings(gym: Gym, **data: Any) -> GymSetting:
    """
    Updates gym configuration fields across Display, Alerts, Audience, and Access & Control.
    Delegates lifecycle transitions to GymSetting domain methods.
    """
    settings_obj = get_or_create_gym_settings(gym)

    allowed_fields = {
        "language",
        "video_autoplay",
        "dark_mode",
        "admin_logs_alerts",
        "issues_alerts",
        "who_can_message",
        "who_can_send_joining_request",
        "who_can_see_members",
        "who_can_see_followers",
        "who_can_see_following",
        "posts_age_restriction",
        "is_deactivated",
        "is_published",
        "is_deleted",
    }

    for field, val in data.items():
        if field not in allowed_fields or val is None:
            continue

        if field == "is_deactivated":
            settings_obj.deactivate() if val else settings_obj.reactivate()
        elif field == "is_published":
            settings_obj.publish() if val else settings_obj.unpublish()
        elif field == "is_deleted":
            settings_obj.soft_delete() if val else settings_obj.restore()
        else:
            setattr(settings_obj, field, val)

    settings_obj.save()
    logger.info("Updated settings for gym %s (%s)", gym.name, gym.id)
    return settings_obj


@transaction.atomic
def block_user_for_gym(
    gym: Gym,
    user_id: str,
    blocked_by_user: Optional[User] = None,
    reason: Optional[str] = None,
) -> GymBlockedUser:
    """
    Blocks a user from interacting with the gym.
    Validates user existence, enforces that the gym owner cannot be blocked,
    and creates the block record idempotently.
    """
    try:
        uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid user_id.")

    target_user = User.objects.filter(id=user_id).select_related("profile").first()
    if not target_user:
        raise ResourceNotFoundError("User to block not found.")

    if target_user.id == gym.owner_user_id:
        raise DomainValidationError("Gym owner cannot be blocked.")

    cleaned_reason = None
    if reason is not None:
        if not isinstance(reason, str):
            raise DomainValidationError("Reason must be a valid string.")
        cleaned_reason = reason.strip()
        if "\x00" in cleaned_reason:
            raise DomainValidationError("Null characters are not allowed.")
        if len(cleaned_reason) > 255:
            raise DomainValidationError("Reason cannot exceed 255 characters.")

    blocked_obj, created = GymBlockedUser.objects.get_or_create(
        gym=gym,
        user=target_user,
        defaults={
            "blocked_by": blocked_by_user,
            "reason": cleaned_reason,
        },
    )
    blocked_obj.user = target_user
    if blocked_by_user:
        blocked_obj.blocked_by = blocked_by_user
    blocked_obj.gym = gym

    # Remove follow relationship if user was following the gym
    GymFollow.objects.filter(gym=gym, user=target_user).delete()

    if created:
        logger.info("Blocked user %s on gym %s by %s", target_user.email, gym.name, blocked_by_user)
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        log_admin_action(
            gym=gym,
            actor=blocked_by_user,
            action="Blocked a user",
            action_type=AdminLogActionType.BLOCK_USER,
            details=f"Blocked {target_user.email}{f': {cleaned_reason}' if cleaned_reason else ''}",
            category=AdminLogCategory.SETTINGS,
            target_type="user",
            target_id=str(target_user.id),
        )
    return blocked_obj


@transaction.atomic
def unblock_user_for_gym(gym: Gym, user_id: str) -> bool:
    """
    Unblocks a previously restricted user account from the gym.
    """
    try:
        uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid user_id.")

    deleted_count, _ = GymBlockedUser.objects.filter(gym=gym, user_id=user_id).delete()
    if deleted_count == 0:
        raise ResourceNotFoundError("Blocked user not found for this gym.")

    logger.info("Unblocked user %s from gym %s", user_id, gym.name)
    from apps.gyms.services.admin_log_services import log_admin_action
    from common.enums import AdminLogCategory, AdminLogActionType
    log_admin_action(
        gym=gym,
        action="Unblocked a user",
        action_type=AdminLogActionType.UNBLOCK_USER,
        details=f"Unblocked user {user_id}",
        category=AdminLogCategory.SETTINGS,
        target_type="user",
        target_id=str(user_id),
    )
    return True


@transaction.atomic
def apply_access_control_action(
    gym: Gym,
    action: str,
    user: User,
    password: Optional[str] = None,
    confirmation: Optional[str] = None,
) -> GymSetting:
    """
    Applies an administrative lifecycle state transition to the gym.
    For 'delete' action:
    - Enforces gym owner or superuser permission.
    - Validates user password.
    - Validates confirmation text matches 'delete'.
    """
    settings_obj = get_or_create_gym_settings(gym)

    if action == "delete":
        if gym.owner_user_id != user.id and not user.is_superuser:
            raise PermissionDeniedError("Only the gym owner can delete this gym account.")

        if not password or not user.check_password(password):
            raise DomainValidationError("Invalid password confirmation.")

        if not confirmation or confirmation.strip().lower() != "delete":
            raise DomainValidationError("Please type 'delete' to confirm deletion.")

    action_handlers = {
        "deactivate": settings_obj.deactivate,
        "reactivate": settings_obj.reactivate,
        "unpublish": settings_obj.unpublish,
        "publish": settings_obj.publish,
        "delete": settings_obj.soft_delete,
        "restore": settings_obj.restore,
    }

    handler = action_handlers.get(action)
    if not handler:
        raise DomainValidationError(f"Invalid access control action '{action}'.")

    handler()
    settings_obj.save()
    logger.info("Applied access control '%s' to gym %s by user %s", action, gym.name, user.email)

    from apps.gyms.services.admin_log_services import log_admin_action
    from common.enums import AdminLogCategory, AdminLogActionType

    log_details_map = {
        "unpublish": ("Changed page visibility", AdminLogActionType.CHANGE_PAGE_VISIBILITY, "Public → Unpublished", AdminLogCategory.VISIBILITY),
        "publish": ("Changed page visibility", AdminLogActionType.CHANGE_PAGE_VISIBILITY, "Unpublished → Public", AdminLogCategory.VISIBILITY),
        "deactivate": ("Deactivated gym workspace", AdminLogActionType.UPDATE_SETTINGS, "Suspended gym operations", AdminLogCategory.VISIBILITY),
        "reactivate": ("Reactivated gym workspace", AdminLogActionType.UPDATE_SETTINGS, "Restored gym operations", AdminLogCategory.VISIBILITY),
        "delete": ("Deleted gym workspace", AdminLogActionType.UPDATE_SETTINGS, "Soft-deleted gym workspace", AdminLogCategory.VISIBILITY),
        "restore": ("Restored gym workspace", AdminLogActionType.UPDATE_SETTINGS, "Restored soft-deleted gym workspace", AdminLogCategory.VISIBILITY),
    }

    if action in log_details_map:
        act_title, act_type, act_desc, act_cat = log_details_map[action]
        log_admin_action(
            gym=gym,
            actor=user,
            action=act_title,
            action_type=act_type,
            details=act_desc,
            category=act_cat,
            target_type="gym",
            target_id=str(gym.id),
        )

    return settings_obj
