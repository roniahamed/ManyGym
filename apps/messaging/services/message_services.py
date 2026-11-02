from typing import Optional, Dict, Any, List
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.users.models import User
from apps.gyms.models import Gym
from apps.messaging.models import (
    Conversation,
    ConversationParticipant,
    EncryptedMessage,
    MessageDeliveryStatusEnum,
    MessageSenderTypeEnum,
    ConversationTypeEnum,
)
from apps.messaging.permissions import (
    assert_can_access_conversation,
    is_user_authorized_for_gym,
    can_user_message_gym,
)
from apps.messaging.services.device_key_services import broadcast_realtime_event
from common.exceptions import (
    DomainValidationError,
    PermissionDeniedError,
)


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
