import uuid
import logging
from typing import Optional, Any
from django.db import transaction
from apps.gyms.models import Gym, GymSetting, GymBlockedUser, GymFollow
from apps.users.models import User
from common.exceptions import DomainValidationError, ResourceNotFoundError

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

    target_user = User.objects.filter(id=user_id).first()
    if not target_user:
        raise ResourceNotFoundError("User to block not found.")

    if target_user.id == gym.owner_user_id:
        raise DomainValidationError("Gym owner cannot be blocked.")

    blocked_obj, created = GymBlockedUser.objects.get_or_create(
        gym=gym,
        user=target_user,
        defaults={
            "blocked_by": blocked_by_user,
            "reason": reason.strip() if reason else None,
        },
    )
    # Remove follow relationship if user was following the gym
    GymFollow.objects.filter(gym=gym, user=target_user).delete()

    if created:
        logger.info("Blocked user %s on gym %s by %s", target_user.email, gym.name, blocked_by_user)
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
    return True


@transaction.atomic
def apply_access_control_action(gym: Gym, action: str, user: User) -> GymSetting:
    """
    Applies an administrative lifecycle state transition to the gym.
    """
    settings_obj = get_or_create_gym_settings(gym)

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
    return settings_obj
