import logging
from typing import Any, Dict, List, Optional
from celery import shared_task
from django.db import transaction

from apps.notifications.models import DeviceToken
from integrations.fcm import FCMClient

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def send_push_notification_task(
    self,
    recipient_id: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Asynchronously delivers a push notification to all active devices of a recipient user.
    Automatically deactivates stale/unregistered tokens.
    """
    try:
        active_tokens = list(
            DeviceToken.objects.filter(user_id=recipient_id, is_active=True).values_list("token", flat=True)
        )
        if not active_tokens:
            return {"status": "skipped", "reason": "No active device tokens found for user."}

        result = FCMClient.send_multicast(
            tokens=active_tokens,
            title=title,
            body=body,
            data=data,
            high_priority=True,
        )

        if result.deactivated_tokens:
            DeviceToken.objects.filter(token__in=result.deactivated_tokens).update(is_active=False)
            logger.info(
                f"Deactivated {len(result.deactivated_tokens)} unregistered token(s) for user {recipient_id}."
            )

        return result.to_dict()

    except Exception as exc:
        logger.error(f"Failed to dispatch push notification task for recipient {recipient_id}: {exc}", exc_info=True)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def send_message_push_task(
    self,
    recipient_id: str,
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Asynchronously delivers a real-time message push notification via FCM.
    Does NOT write to the in-app notifications database table.
    """
    try:
        active_tokens = list(
            DeviceToken.objects.filter(user_id=recipient_id, is_active=True).values_list("token", flat=True)
        )
        if not active_tokens:
            return {"status": "skipped", "reason": "No active device tokens found for user."}

        result = FCMClient.send_multicast(
            tokens=active_tokens,
            title=title,
            body=body,
            data=data,
            high_priority=True,
        )

        if result.deactivated_tokens:
            DeviceToken.objects.filter(token__in=result.deactivated_tokens).update(is_active=False)

        return result.to_dict()

    except Exception as exc:
        logger.error(f"Failed to dispatch message push notification for recipient {recipient_id}: {exc}", exc_info=True)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def bulk_send_push_task(
    self,
    recipient_ids: List[str],
    title: str,
    body: str,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Dispatches a bulk push notification across multiple recipient users.
    """
    try:
        active_tokens = list(
            DeviceToken.objects.filter(user_id__in=recipient_ids, is_active=True).values_list("token", flat=True)
        )
        if not active_tokens:
            return {"status": "skipped", "reason": "No active device tokens found."}

        result = FCMClient.send_multicast(
            tokens=active_tokens,
            title=title,
            body=body,
            data=data,
            high_priority=True,
        )

        if result.deactivated_tokens:
            DeviceToken.objects.filter(token__in=result.deactivated_tokens).update(is_active=False)

        return result.to_dict()

    except Exception as exc:
        logger.error(f"Failed to dispatch bulk push notification: {exc}", exc_info=True)
        raise self.retry(exc=exc)
