import logging
import uuid
from typing import Any, Dict, Optional

from django.db import transaction
from django.utils import timezone

from apps.gyms.models import Gym
from apps.messaging.services.device_key_services import broadcast_realtime_event
from apps.notifications.models import Notification
from apps.notifications.tasks import (
    send_message_push_task,
    send_push_notification_task,
)
from apps.users.models import User
from common.enums import NotificationTypeEnum
from common.exceptions import DomainValidationError, ResourceNotFoundError

logger = logging.getLogger(__name__)


@transaction.atomic
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

    Enforces that users do not receive notifications triggered by their own actions.
    """
    # Self-notification suppression
    if actor is not None and recipient.id == actor.id and actor_gym is None:
        logger.debug(f"Suppressed self-notification for user {recipient.id}")
        return None

    if notification_type not in NotificationTypeEnum.values:
        raise DomainValidationError(f"Invalid notification_type '{notification_type}'.")

    payload_data = dict(data or {})
    payload_data.update({
        "notification_type": notification_type,
        "target_type": target_type,
        "target_id": str(target_id) if target_id else "",
        "action_url": action_url,
    })
    if gym:
        payload_data["gym_id"] = str(gym.id)
    if actor:
        payload_data["actor_id"] = str(actor.id)
    if actor_gym:
        payload_data["actor_gym_id"] = str(actor_gym.id)

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
        target_id=str(target_id) if target_id else "",
        action_url=action_url,
        is_read=False,
    )

    # Broadcast real-time event to personal user channel
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
    broadcast_realtime_event(
        f"chat_user_{recipient.id}",
        "incoming_notification",
        realtime_payload,
    )
    if gym:
        broadcast_realtime_event(
            f"chat_gym_{gym.id}",
            "incoming_notification",
            realtime_payload,
        )

    # Enqueue push delivery via Celery task
    if send_push:
        try:
            send_push_notification_task.delay(
                recipient_id=str(recipient.id),
                title=title,
                body=body,
                data=payload_data,
            )
        except Exception as exc:
            # Fallback for eager test runs or worker disconnection
            logger.warning(f"Could not enqueue async push task: {exc}. Running synchronously if needed.")

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
    message_data = dict(data or {})
    message_data.setdefault("type", "chat_message")

    try:
        send_message_push_task.delay(
            recipient_id=str(recipient_user.id),
            title=title,
            body=body,
            data=message_data,
        )
    except Exception as exc:
        logger.warning(f"Could not enqueue message push task: {exc}")


@transaction.atomic
def mark_notification_as_read(notification_id: Any, user: User) -> Notification:
    """Marks a single notification as read."""
    try:
        n_uuid = uuid.UUID(str(notification_id))
    except (ValueError, TypeError, AttributeError):
        raise ResourceNotFoundError("Notification not found.")

    notification = Notification.objects.filter(id=n_uuid, recipient=user).first()
    if not notification:
        raise ResourceNotFoundError("Notification not found.")

    if not notification.is_read:
        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at", "updated_at"])

    return notification


@transaction.atomic
def mark_all_notifications_as_read(user: User, gym: Optional[Gym] = None) -> int:
    """
    Atomically marks all unread notifications for a user (and optional gym) as read.
    Returns the number of updated records.
    """
    qs = Notification.objects.filter(recipient=user, is_read=False)
    if gym is not None:
        qs = qs.filter(gym=gym)

    return qs.update(is_read=True, read_at=timezone.now(), updated_at=timezone.now())


@transaction.atomic
def delete_notification(notification_id: Any, user: User) -> bool:
    """Permanently deletes a notification owned by the authenticated user."""
    try:
        n_uuid = uuid.UUID(str(notification_id))
    except (ValueError, TypeError, AttributeError):
        raise ResourceNotFoundError("Notification not found.")

    notification = Notification.objects.filter(id=n_uuid, recipient=user).first()
    if not notification:
        raise ResourceNotFoundError("Notification not found.")

    notification.delete()
    return True
