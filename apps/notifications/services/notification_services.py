"""
Write-side business logic and services for In-App Notifications.
Handles transactional notification persistence, real-time WebSocket broadcasting,
background Celery FCM push dispatches, anti-spam debouncing, and privacy blocklists.
"""

import datetime
import logging
import uuid
from typing import Any, Dict, List, Optional

from django.db import models
from django.utils import timezone

from apps.gyms.models import Gym, GymBlockedUser
from apps.messaging.services.device_key_services import broadcast_realtime_event
from apps.notifications.models import Notification
from apps.notifications.tasks import (
    send_message_push_task,
    send_push_notification_task,
)
from apps.users.models import User, UserBlockedUser
from common.enums import NotificationTypeEnum
from common.exceptions import DomainValidationError, ResourceNotFoundError

logger = logging.getLogger(__name__)

# Anti-spam debouncing threshold: duplicate notifications for identical target
# within this window are debounced to prevent notification flooding.
DEBOUNCE_WINDOW_SECONDS = 5

# Notification types that represent user-to-user social interactions
SOCIAL_NOTIFICATION_TYPES = (
    NotificationTypeEnum.REACTION,
    NotificationTypeEnum.COMMENT,
    NotificationTypeEnum.FOLLOW,
    NotificationTypeEnum.MEMBER_REQUEST,
)


def _is_user_available_for_notifications(user: Optional[User]) -> bool:
    """
    Checks whether a user account is active, not soft-deleted, and not deactivated.
    Evaluates in-memory user columns directly to avoid extraneous database queries.
    """
    if not user:
        return False
    if not getattr(user, "is_active", True):
        return False
    if getattr(user, "status", None) in ("deleted", "deactivated"):
        return False
    return True


def _dispatch_push_task_safely(
    recipient_id: str,
    title: str,
    body: str,
    data: Dict[str, Any],
) -> None:
    """Helper to enqueue the Celery push notification task without crashing callers."""
    safe_title = str(title).strip()[:200]
    safe_body = str(body).strip()[:400]

    safe_data: Dict[str, str] = {}
    for k, v in data.items():
        if v is not None:
            safe_data[str(k)] = str(v)[:1024]

    try:
        send_push_notification_task.delay(
            recipient_id=recipient_id,
            title=safe_title,
            body=safe_body,
            data=safe_data,
        )
    except Exception as exc:
        logger.warning(
            "Could not enqueue async push notification task for recipient %s: %s",
            recipient_id,
            exc,
        )


def _dispatch_realtime_broadcast_safely(
    channels: List[str],
    event_type: str,
    payload: Dict[str, Any],
) -> None:
    """Dispatches Channels WebSocket event to all specified room groups."""
    for channel in channels:
        try:
            broadcast_realtime_event(channel, event_type, payload)
        except Exception as exc:
            logger.warning(
                "Could not broadcast realtime notification event on channel %s: %s",
                channel,
                exc,
            )


def send_notification(
    recipient: User,
    notification_type: str,
    title: str,
    body: str,
    actor: Optional[User] = None,
    actor_gym: Optional[Gym] = None,
    gym: Optional[Gym] = None,
    target_type: str = "",
    target_id: str = "",
    action_url: str = "",
    data: Optional[Dict[str, Any]] = None,
    send_push: bool = True,
) -> Optional[Notification]:
    """
    Universal in-app and push notification dispatcher.
    Persists notification to database, triggers realtime WebSocket broadcast,
    and enqueues background push notification delivery via FCM.

    Enforces:
    - Self-notification suppression.
    - Inactive / deactivated / soft-deleted account suppression.
    - Social privacy blocklist filtering (bidirectional user blocking & gym user blocking).
    - Rapid duplicate spam debouncing for social actions.
    """
    # 1. Recipient availability check
    if not _is_user_available_for_notifications(recipient):
        logger.debug("Suppressed notification: recipient %s is inactive, deleted, or deactivated.", recipient.id)
        return None

    # 2. Self-notification suppression: do not notify user of their own actions
    if actor is not None and recipient.id == actor.id and actor_gym is None:
        logger.debug("Suppressed self-notification for user %s", recipient.id)
        return None

    # 3. Actor availability check
    if actor is not None and not _is_user_available_for_notifications(actor):
        logger.debug("Suppressed notification: actor %s is inactive, deleted, or deactivated.", actor.id)
        return None

    # 4. Social Privacy Blocklist Checks (applies to user social actions and join requests)
    if actor is not None and notification_type in SOCIAL_NOTIFICATION_TYPES:
        is_blocked = UserBlockedUser.objects.filter(
            models.Q(blocker=recipient, blocked_user=actor) |
            models.Q(blocker=actor, blocked_user=recipient)
        ).exists()
        if is_blocked:
            logger.debug(
                "Suppressed notification due to blocklist between recipient %s and actor %s",
                recipient.id,
                actor.id,
            )
            return None

        # Check gym blocklist if gym workspace is present
        target_gym = gym or actor_gym
        if target_gym is not None and getattr(target_gym, "owner_user_id", None) != actor.id:
            if GymBlockedUser.objects.filter(gym=target_gym, user=actor).exists():
                logger.debug("Suppressed notification: actor %s is blocked by gym %s", actor.id, target_gym.id)
                return None

    # 5. Validate notification type enum
    if notification_type not in NotificationTypeEnum.values:
        raise DomainValidationError(f"Invalid notification_type '{notification_type}'.")

    # 6. Anti-Spam Debouncing: Only for high-frequency social actions (reactions and comments)
    target_id_str = str(target_id) if target_id else ""
    if (
        target_type
        and target_id_str
        and notification_type in (NotificationTypeEnum.REACTION, NotificationTypeEnum.COMMENT)
    ):
        recent_threshold = timezone.now() - datetime.timedelta(seconds=DEBOUNCE_WINDOW_SECONDS)
        existing_recent = Notification.objects.filter(
            recipient=recipient,
            actor=actor,
            notification_type=notification_type,
            target_type=target_type,
            target_id=target_id_str,
            is_read=False,
            created_at__gte=recent_threshold,
        ).first()
        if existing_recent:
            logger.debug(
                "Debounced duplicate notification within %ds window for recipient %s",
                DEBOUNCE_WINDOW_SECONDS,
                recipient.id,
            )
            return existing_recent

    # 7. Build rich payload data dictionary
    payload_data = dict(data or {})
    payload_data.update({
        "notification_type": notification_type,
        "target_type": target_type,
        "target_id": target_id_str,
        "action_url": action_url,
    })
    if gym:
        payload_data["gym_id"] = str(gym.id)
    if actor:
        payload_data["actor_id"] = str(actor.id)
    if actor_gym:
        payload_data["actor_gym_id"] = str(actor_gym.id)

    # 8. Persist in-app notification record (single atomic INSERT, no nested savepoint)
    notification = Notification.objects.create(
        recipient=recipient,
        actor=actor,
        actor_gym=actor_gym,
        gym=gym,
        notification_type=notification_type,
        title=title.strip(),
        body=body.strip(),
        data=payload_data,
        target_type=target_type,
        target_id=target_id_str,
        action_url=action_url,
        is_read=False,
    )

    # 9. Prepare realtime payload
    realtime_payload = {
        "id": str(notification.id),
        "notification_type": notification.notification_type,
        "title": notification.title,
        "body": notification.body,
        "target_type": notification.target_type,
        "target_id": notification.target_id,
        "action_url": notification.action_url,
        "data": notification.data,
        "is_read": False,
        "created_at": notification.created_at.isoformat(),
    }

    # 10. Channels to notify
    channels_to_notify = [f"chat_user_{recipient.id}"]
    if gym:
        channels_to_notify.append(f"chat_gym_{gym.id}")

    _dispatch_realtime_broadcast_safely(
        channels=channels_to_notify,
        event_type="incoming_notification",
        payload=realtime_payload,
    )

    # 11. Asynchronously dispatch mobile FCM push notification via Celery
    if send_push:
        _dispatch_push_task_safely(
            recipient_id=str(recipient.id),
            title=title,
            body=body,
            data=payload_data,
        )

    return notification


def send_message_push_notification(
    recipient_user: User,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Dispatches a real-time message notification via FCM.
    Crucially: DOES NOT create an in-app Notification database record,
    because messages already have dedicated encrypted storage in the messaging domain.
    """
    if not _is_user_available_for_notifications(recipient_user):
        logger.debug("Suppressed message push: recipient %s is inactive or deleted.", recipient_user.id)
        return

    message_data = dict(data or {})
    message_data.setdefault("type", "chat_message")

    safe_title = str(title).strip()[:200]
    safe_body = str(body).strip()[:400]
    safe_data: Dict[str, str] = {str(k): str(v)[:1024] for k, v in message_data.items() if v is not None}

    try:
        send_message_push_task.delay(
            recipient_id=str(recipient_user.id),
            title=safe_title,
            body=safe_body,
            data=safe_data,
        )
    except Exception as exc:
        logger.warning("Could not enqueue message push task: %s", exc)


def mark_notification_as_read(
    notification_id: Any,
    user: User,
    gym: Optional[Gym] = None,
) -> Notification:
    """Marks a single notification as read."""
    try:
        n_uuid = uuid.UUID(str(notification_id))
    except (ValueError, TypeError, AttributeError):
        raise ResourceNotFoundError("Notification not found or access denied.")

    qs = Notification.objects.filter(id=n_uuid)
    if gym is not None:
        qs = qs.filter(models.Q(recipient=user) | models.Q(gym=gym))
    else:
        qs = qs.filter(recipient=user)

    notification = qs.first()
    if not notification:
        raise ResourceNotFoundError("Notification not found or access denied.")

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at", "updated_at"])

    return notification


def mark_notifications_batch_as_read(
    notification_ids: List[Any],
    user: User,
    gym: Optional[Gym] = None,
) -> int:
    """
    Atomically marks a specific batch of notification UUIDs as read.
    Validates tenant ownership and ignores UUIDs not belonging to the caller.
    """
    if not notification_ids:
        return 0

    valid_uuids: List[uuid.UUID] = []
    for nid in notification_ids:
        try:
            valid_uuids.append(uuid.UUID(str(nid)))
        except (ValueError, TypeError, AttributeError):
            continue

    if not valid_uuids:
        return 0

    qs = Notification.objects.filter(id__in=valid_uuids, is_read=False)
    if gym is not None:
        qs = qs.filter(models.Q(recipient=user) | models.Q(gym=gym))
    else:
        qs = qs.filter(recipient=user)

    now = timezone.now()
    return qs.update(is_read=True, read_at=now, updated_at=now)


def mark_all_notifications_as_read(user: User, gym: Optional[Gym] = None) -> int:
    """
    Atomically marks all unread notifications for a user (and optional gym) as read.
    Returns the number of updated records.
    """
    qs = Notification.objects.filter(recipient=user, is_read=False)
    if gym is not None:
        qs = qs.filter(gym=gym)

    now = timezone.now()
    return qs.update(is_read=True, read_at=now, updated_at=now)


def clear_read_notifications(user: User, gym: Optional[Gym] = None) -> int:
    """
    Permanently purges all read notifications for a user (or active gym workspace).
    Returns the count of purged records.
    """
    qs = Notification.objects.filter(recipient=user, is_read=True)
    if gym is not None:
        qs = qs.filter(gym=gym)

    deleted_count, _ = qs.delete()
    return deleted_count


def delete_notification(
    notification_id: Any,
    user: User,
    gym: Optional[Gym] = None,
) -> bool:
    """Permanently deletes a notification owned by the authenticated user or gym."""
    try:
        n_uuid = uuid.UUID(str(notification_id))
    except (ValueError, TypeError, AttributeError):
        raise ResourceNotFoundError("Notification not found or access denied.")

    qs = Notification.objects.filter(id=n_uuid)
    if gym is not None:
        qs = qs.filter(models.Q(recipient=user) | models.Q(gym=gym))
    else:
        qs = qs.filter(recipient=user)

    notification = qs.first()
    if not notification:
        raise ResourceNotFoundError("Notification not found or access denied.")

    notification.delete()
    return True
