"""
Selectors package for Notifications domain.
Exposes notification and device selector functions with clean interfaces.
"""

from .device_selectors import (
    get_active_device_tokens_for_user,
    get_user_device_tokens,
)
from .notification_selectors import (
    get_notification_by_id,
    get_unread_notification_count,
    list_notifications,
)

__all__ = [
    "get_active_device_tokens_for_user",
    "get_user_device_tokens",
    "get_notification_by_id",
    "get_unread_notification_count",
    "list_notifications",
]
