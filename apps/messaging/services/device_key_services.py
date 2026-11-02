from typing import Optional, Dict, Any, List
from django.db import transaction
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from apps.users.models import User
from apps.gyms.models import Gym
from apps.messaging.models import UserDeviceKey, GymDeviceKey
from apps.messaging.permissions import is_user_authorized_for_gym
from common.exceptions import (
    DomainValidationError,
    PermissionDeniedError,
)


def broadcast_realtime_event(group_name: str, event_type: str, data: Dict[str, Any]) -> None:
    """Helper to safely broadcast a real-time event to a Channels group."""
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    "type": event_type,
                    "data": data,
                },
            )
    except Exception:
        # Prevent Celery/request failure if Redis or Channel layer is temporarily degraded
        pass


@transaction.atomic
def register_user_device_key(
    user: User,
    device_id: str,
    identity_key: str,
    signed_prekey: str,
    signed_prekey_signature: str = "",
    one_time_prekeys: Optional[List[str]] = None,
    device_name: str = "",
) -> UserDeviceKey:
    """
    Registers or updates the public E2EE key bundle for a user's client device.
    """
    if not device_id or not identity_key or not signed_prekey:
        raise DomainValidationError("device_id, identity_key, and signed_prekey are required.")

    key_obj, _ = UserDeviceKey.objects.update_or_create(
        user=user,
        device_id=device_id,
        defaults={
            "identity_key": identity_key,
            "signed_prekey": signed_prekey,
            "signed_prekey_signature": signed_prekey_signature or "",
            "one_time_prekeys": one_time_prekeys or [],
            "device_name": device_name or "",
            "is_active": True,
        },
    )
    return key_obj


@transaction.atomic
def register_gym_device_key(
    gym: Gym,
    user: User,
    device_id: str,
    identity_key: str,
    signed_prekey: str,
    signed_prekey_signature: str = "",
    one_time_prekeys: Optional[List[str]] = None,
    device_name: str = "",
) -> GymDeviceKey:
    """
    Registers or updates an E2EE public key bundle for a Gym tenant identity.
    Only authorized gym staff/owner can register keys.
    """
    if not is_user_authorized_for_gym(user, gym, "messaging:send"):
        raise PermissionDeniedError("You are not authorized to register cryptographic keys for this gym.")

    if not device_id or not identity_key or not signed_prekey:
        raise DomainValidationError("device_id, identity_key, and signed_prekey are required.")

    key_obj, _ = GymDeviceKey.objects.update_or_create(
        gym=gym,
        device_id=device_id,
        defaults={
            "identity_key": identity_key,
            "signed_prekey": signed_prekey,
            "signed_prekey_signature": signed_prekey_signature or "",
            "one_time_prekeys": one_time_prekeys or [],
            "registered_by": user,
            "device_name": device_name or "",
            "is_active": True,
        },
    )
    return key_obj
