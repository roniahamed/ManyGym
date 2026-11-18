"""
Read-side queries and selectors for In-App Notifications.
Provides optimized, N+1-safe queries for user notifications and badge counts.
"""

import uuid
from typing import Any, Optional

from django.db import models
from django.db.models import QuerySet

from apps.gyms.models import Gym
from apps.notifications.models import Notification
from apps.users.models import User


def list_notifications(
    user: User,
    gym: Optional[Gym] = None,
    is_read: Optional[bool] = None,
    notification_type: Optional[str] = None,
) -> QuerySet[Notification]:
    """
    Returns an optimized QuerySet of notifications for a user or active gym context.
    Pre-fetches actor, actor profiles, and related gyms to eliminate N+1 queries.
    """
    qs = (
        Notification.objects.select_related(
            "actor",
            "actor__profile",
            "actor_gym",
            "gym",
        )
        .filter(recipient=user)
    )

    if gym is not None:
        qs = qs.filter(gym=gym)

    if is_read is not None:
        qs = qs.filter(is_read=is_read)

    if notification_type:
        qs = qs.filter(notification_type=notification_type)

    return qs.order_by("-created_at")


def get_unread_notification_count(user: User, gym: Optional[Gym] = None) -> int:
    """
    Returns total count of unread notifications for the user.
    Leverages compound database index on (recipient, is_read, -created_at).
    """
    qs = Notification.objects.filter(recipient=user, is_read=False)
    if gym is not None:
        qs = qs.filter(gym=gym)
    return qs.count()


def get_notification_by_id(
    notification_id: Any,
    user: User,
    gym: Optional[Gym] = None,
) -> Optional[Notification]:
    """
    Retrieves a single notification by UUID, scoped strictly to the recipient user
    or their active gym workspace. Returns None if invalid or not found.
    """
    try:
        n_uuid = uuid.UUID(str(notification_id))
    except (ValueError, TypeError, AttributeError):
        return None

    qs = Notification.objects.select_related(
        "actor",
        "actor__profile",
        "actor_gym",
        "gym",
    ).filter(id=n_uuid)

    if gym is not None:
        qs = qs.filter(models.Q(recipient=user) | models.Q(gym=gym))
    else:
        qs = qs.filter(recipient=user)

    return qs.first()
