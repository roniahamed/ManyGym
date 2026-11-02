"""
Write-side domain services for End-to-End Encrypted Messaging.
Orchestrates conversations, E2EE key registration, encrypted message dispatch, and read receipts.
"""

from typing import Optional, Dict, Any, List
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from apps.users.models import User
from apps.gyms.models import Gym
from apps.messaging.models import (
    UserDeviceKey,
    GymDeviceKey,
    Conversation,
    ConversationParticipant,
    EncryptedMessage,
    MessageDeliveryReceipt,
)
from apps.messaging.permissions import (
    can_user_message_gym,
    is_user_authorized_for_gym,
    assert_can_access_conversation,
)
from common.enums import (
    ConversationTypeEnum,
    MessageSenderTypeEnum,
    MessageDeliveryStatusEnum,
)
from common.exceptions import (
    DomainValidationError,
    PermissionDeniedError,
    ResourceNotFoundError,
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


@transaction.atomic
def get_or_create_user_to_user_conversation(user_a: User, user_b: User) -> Conversation:
    """
    Initiates or retrieves a 1-on-1 User-to-User conversation.
    Enforces canonical ordering (min UUID, max UUID) to ensure uniqueness.
    """
    if user_a.id == user_b.id:
        raise DomainValidationError("Cannot create a conversation with yourself.")

    # Canonical order
    first_user, second_user = (user_a, user_b) if user_a.id < user_b.id else (user_b, user_a)

    conversation, created = Conversation.objects.get_or_create(
        conversation_type=ConversationTypeEnum.USER_TO_USER,
        user_a=first_user,
        user_b=second_user,
    )

    if created:
        ConversationParticipant.objects.create(
            conversation=conversation,
            participant_type=MessageSenderTypeEnum.USER,
            user=first_user,
        )
        ConversationParticipant.objects.create(
            conversation=conversation,
            participant_type=MessageSenderTypeEnum.USER,
            user=second_user,
        )

    return conversation


@transaction.atomic
def get_or_create_user_to_gym_conversation(
    user: User,
    gym: Gym,
    initiated_by: str = "user",
    initiator_user: Optional[User] = None,
) -> Conversation:
    """
    Initiates or retrieves a conversation between an individual User and a Gym (User <-> Gym).
    - If initiated_by == 'user': validates gym messaging policy (EVERYONE, MEMBERS_ONLY) and blocklist.
    - If initiated_by == 'gym': validates initiator_user has staff/owner authorization for the gym.
    """
    if initiated_by == "gym":
        if initiator_user and not is_user_authorized_for_gym(initiator_user, gym, "messaging:send"):
            raise PermissionDeniedError("You are not authorized to initiate conversations for this gym.")
    else:
        can_user_message_gym(user, gym)

    conversation, created = Conversation.objects.get_or_create(
        conversation_type=ConversationTypeEnum.USER_TO_GYM,
        user_a=user,
        gym_a=gym,
    )

    if created:
        ConversationParticipant.objects.create(
            conversation=conversation,
            participant_type=MessageSenderTypeEnum.USER,
            user=user,
        )
        ConversationParticipant.objects.create(
            conversation=conversation,
            participant_type=MessageSenderTypeEnum.GYM,
            gym=gym,
        )

    return conversation


@transaction.atomic
def get_or_create_gym_to_gym_conversation(sender_user: User, gym_a: Gym, gym_b: Gym) -> Conversation:
    """
    Initiates or retrieves a B2B Gym-to-Gym conversation.
    Enforces that sender is authorized for gym_a and gyms are distinct.
    """
    if gym_a.id == gym_b.id:
        raise DomainValidationError("Cannot initiate conversation between the same gym.")

    if not is_user_authorized_for_gym(sender_user, gym_a, "messaging:send"):
        raise PermissionDeniedError("You are not authorized to initiate messaging for Gym A.")

    # Canonical order
    first_gym, second_gym = (gym_a, gym_b) if gym_a.id < gym_b.id else (gym_b, gym_a)

    conversation, created = Conversation.objects.get_or_create(
        conversation_type=ConversationTypeEnum.GYM_TO_GYM,
        gym_a=first_gym,
        gym_b=second_gym,
    )

    if created:
        ConversationParticipant.objects.create(
            conversation=conversation,
            participant_type=MessageSenderTypeEnum.GYM,
            gym=first_gym,
        )
        ConversationParticipant.objects.create(
            conversation=conversation,
            participant_type=MessageSenderTypeEnum.GYM,
            gym=second_gym,
        )

    return conversation


@transaction.atomic
def send_encrypted_message(
    conversation: Conversation,
    sender_user: User,
    sender_type: str,
    ciphertext: str,
    nonce: str,
    ephemeral_public_key: str = "",
    recipient_key_fingerprint: str = "",
    sender_device_id: str = "",
    encrypted_keys: Optional[Dict[str, Any]] = None,
    sender_gym: Optional[Gym] = None,
) -> EncryptedMessage:
    """
    Creates and records an E2EE encrypted message and dispatches real-time broadcast events.
    """
    if not ciphertext or not nonce:
        raise DomainValidationError("Ciphertext and nonce are required for E2EE messages.")

    # Validate sender access to the conversation
    assert_can_access_conversation(sender_user, conversation, gym_context=sender_gym)

    # If sending on behalf of a gym, verify authorization
    if sender_type == MessageSenderTypeEnum.GYM:
        if not sender_gym:
            raise DomainValidationError("sender_gym must be specified when sender_type is 'gym'.")
        if not is_user_authorized_for_gym(sender_user, sender_gym, "messaging:send"):
            raise PermissionDeniedError("You are not authorized to send messages on behalf of this gym.")
    else:
        # Individual user sender
        if conversation.conversation_type == ConversationTypeEnum.USER_TO_GYM:
            can_user_message_gym(sender_user, conversation.gym_a)

    # Create the encrypted message record
    message = EncryptedMessage.objects.create(
        conversation=conversation,
        sender_type=sender_type,
        sender_user=sender_user,
        sender_gym=sender_gym if sender_type == MessageSenderTypeEnum.GYM else None,
        sender_device_id=sender_device_id or "",
        ciphertext=ciphertext,
        nonce=nonce,
        ephemeral_public_key=ephemeral_public_key or "",
        recipient_key_fingerprint=recipient_key_fingerprint or "",
        encrypted_keys=encrypted_keys or {},
        delivery_status=MessageDeliveryStatusEnum.SENT,
        sent_at=timezone.now(),
    )

    # Update conversation metadata
    conversation.last_message_at = message.sent_at
    conversation.last_message_preview = "🔒 Encrypted Message"
    conversation.save(update_fields=["last_message_at", "last_message_preview", "updated_at"])

    # Update unread count for other participants using atomic DB-level F expression
    other_qs = ConversationParticipant.objects.filter(conversation=conversation)
    if sender_type == MessageSenderTypeEnum.USER:
        other_qs = other_qs.exclude(user=sender_user)
    elif sender_type == MessageSenderTypeEnum.GYM:
        other_qs = other_qs.exclude(gym=sender_gym)

    other_targets = list(other_qs.values_list("user_id", "gym_id"))
    other_qs.update(unread_count=F("unread_count") + 1, updated_at=timezone.now())

    # Real-time WebSockets dispatch payload
    payload = {
        "id": str(message.id),
        "conversation_id": str(conversation.id),
        "sender_type": message.sender_type,
        "sender_user_id": str(message.sender_user_id) if message.sender_user_id else None,
        "sender_gym_id": str(message.sender_gym_id) if message.sender_gym_id else None,
        "sender_gym_name": message.sender_gym.name if message.sender_gym else None,
        "sender_device_id": message.sender_device_id,
        "ciphertext": message.ciphertext,
        "nonce": message.nonce,
        "ephemeral_public_key": message.ephemeral_public_key,
        "recipient_key_fingerprint": message.recipient_key_fingerprint,
        "encrypted_keys": message.encrypted_keys,
        "delivery_status": message.delivery_status,
        "sent_at": message.sent_at.isoformat(),
    }

    # Broadcast to conversation room
    broadcast_realtime_event(
        f"chat_conversation_{conversation.id}",
        "chat_message",
        payload,
    )

    # Also notify recipient personal/gym channels for push notifications / badge counts
    for user_id, gym_id in other_targets:
        if user_id:
            broadcast_realtime_event(f"chat_user_{user_id}", "chat_incoming", payload)
        elif gym_id:
            broadcast_realtime_event(f"chat_gym_{gym_id}", "chat_incoming", payload)

    return message


@transaction.atomic
def mark_conversation_as_read(
    conversation: Conversation,
    user: User,
    gym: Optional[Gym] = None,
    up_to_message_id: Optional[str] = None,
) -> int:
    """
    Marks messages in a conversation as read by the user (or gym context).
    Resets participant unread count and creates delivery receipts.
    Broadcasts real-time read receipt to conversation participants.
    """
    assert_can_access_conversation(user, conversation, gym_context=gym)

    now = timezone.now()

    # Find the participant record directly
    if gym:
        participant = ConversationParticipant.objects.filter(conversation=conversation, gym=gym).first()
    else:
        participant = ConversationParticipant.objects.filter(conversation=conversation, user=user).first()

    if participant:
        participant.unread_count = 0
        participant.last_read_at = now
        if up_to_message_id:
            participant.last_read_message_id = up_to_message_id
        participant.save(update_fields=["unread_count", "last_read_at", "last_read_message_id", "updated_at"])

    # Update unread messages sent by others
    messages_qs = conversation.messages.filter(delivery_status__in=[MessageDeliveryStatusEnum.SENT, MessageDeliveryStatusEnum.DELIVERED])
    if gym:
        messages_qs = messages_qs.exclude(sender_gym=gym)
    else:
        messages_qs = messages_qs.exclude(sender_user=user)

    updated_count = messages_qs.update(
        delivery_status=MessageDeliveryStatusEnum.READ,
        read_at=now,
    )

    # Realtime notification of read receipt
    receipt_data = {
        "conversation_id": str(conversation.id),
        "read_by_user_id": str(user.id),
        "read_by_gym_id": str(gym.id) if gym else None,
        "timestamp": now.isoformat(),
        "read_count": updated_count,
    }
    broadcast_realtime_event(
        f"chat_conversation_{conversation.id}",
        "chat_read_receipt",
        receipt_data,
    )

    return updated_count
