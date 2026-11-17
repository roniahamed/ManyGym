from typing import List, Optional
from django.db.models import QuerySet
from apps.notifications.models import DeviceToken
from apps.users.models import User


def get_user_device_tokens(user: User) -> QuerySet[DeviceToken]:
    """Returns all device tokens registered for a specific user, ordered by most recently seen."""
    return DeviceToken.objects.filter(user=user).order_by("-updated_at")


def get_active_device_tokens_for_user(user: User) -> List[str]:
    """Returns list of active FCM token strings for a user."""
    return list(
        DeviceToken.objects.filter(user=user, is_active=True).values_list("token", flat=True)
    )
