"""
Services package for Notifications domain.
Exposes write services for notifications and device tokens with clean interfaces.
"""

from .device_services import (
    MAX_ACTIVE_DEVICES_PER_USER,
    deactivate_invalid_tokens,
    register_device_token,
    unregister_device_token,
)
from .notification_services import (
    clear_read_notifications,
    delete_notification,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    mark_notifications_batch_as_read,
    send_message_push_notification,
    send_notification,
)

__all__ = [
    "MAX_ACTIVE_DEVICES_PER_USER",
    "clear_read_notifications",
    "deactivate_invalid_tokens",
    "delete_notification",
    "mark_all_notifications_as_read",
    "mark_notification_as_read",
    "mark_notifications_batch_as_read",
    "register_device_token",
    "send_message_push_notification",
    "send_notification",
    "unregister_device_token",
]
