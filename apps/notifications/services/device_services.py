"""
Write-side business logic and services for client FCM Device Tokens.
Handles token registration, upserts, deactivation upon logout, and pruning of stale devices.
"""

import logging
from typing import List
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import DeviceToken
from apps.users.models import User
from common.enums import DevicePlatformEnum
from common.exceptions import DomainValidationError

logger = logging.getLogger(__name__)

# Configurable threshold to prevent infinite accumulation of dead/inactive device tokens
MAX_ACTIVE_DEVICES_PER_USER = 10


@transaction.atomic
def register_device_token(
    user: User,
    token: str,
    device_id: str = "",
    device_name: str = "",
    platform: str = DevicePlatformEnum.ANDROID,
) -> DeviceToken:
    """
    Registers or updates an FCM device token for an authenticated user.
    Reactivates existing tokens and enforces the max concurrent active device threshold.
    """
    cleaned_token = str(token).strip() if token else ""
    if not cleaned_token:
        raise DomainValidationError("A valid non-empty FCM device token is required.")

    if platform not in DevicePlatformEnum.values:
        platform = DevicePlatformEnum.ANDROID

    # Check if token exists across any user (e.g. app reinstalled or user switched accounts on same device)
    device_token = DeviceToken.objects.filter(token=cleaned_token).first()

    if device_token:
        device_token.user = user
        device_token.is_active = True
        device_token.device_id = device_id.strip() if device_id else device_token.device_id
        device_token.device_name = device_name.strip() if device_name else device_token.device_name
        device_token.platform = platform
        device_token.last_seen_at = timezone.now()
        device_token.save()
    else:
        device_token = DeviceToken.objects.create(
            user=user,
            token=cleaned_token,
            device_id=device_id.strip() if device_id else "",
            device_name=device_name.strip() if device_name else "",
            platform=platform,
            is_active=True,
        )

    # Enforce active device threshold per user
    active_tokens_qs = DeviceToken.objects.filter(user=user, is_active=True).order_by("-updated_at")
    total_active = active_tokens_qs.count()
    if total_active > MAX_ACTIVE_DEVICES_PER_USER:
        stale_ids = list(active_tokens_qs.values_list("id", flat=True)[MAX_ACTIVE_DEVICES_PER_USER:])
        DeviceToken.objects.filter(id__in=stale_ids).update(is_active=False)

    return device_token


@transaction.atomic
def unregister_device_token(user: User, token: str) -> bool:
    """
    Deactivates an active device token belonging to the user upon logout or toggle off.
    """
    cleaned_token = str(token).strip() if token else ""
    if not cleaned_token:
        raise DomainValidationError("Device token is required to unregister.")

    updated_count = DeviceToken.objects.filter(
        user=user,
        token=cleaned_token,
    ).update(is_active=False, updated_at=timezone.now())

    return updated_count > 0


def deactivate_invalid_tokens(tokens: List[str]) -> int:
    """Deactivates a list of dead/unregistered FCM tokens returned by the provider."""
    if not tokens:
        return 0
    return DeviceToken.objects.filter(token__in=tokens).update(is_active=False)
