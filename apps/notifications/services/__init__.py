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
    delete_notification,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    send_message_push_notification,
    send_notification,
)

__all__ = [
    "MAX_ACTIVE_DEVICES_PER_USER",
    "deactivate_invalid_tokens",
    "register_device_token",
    "unregister_device_token",
    "delete_notification",
    "mark_all_notifications_as_read",
    "mark_notification_as_read",
    "send_message_push_notification",
    "send_notification",
]
