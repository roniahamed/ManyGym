import logging
from typing import Optional, Dict, Any, List
from django.db import transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

from apps.users.models import User
from apps.gyms.models import Gym
from apps.messaging.models import (
    Conversation,
    ConversationParticipant,
    EncryptedMessage,
    MessageSearchToken,
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
    ResourceNotFoundError,
)


def _normalize_token_list(raw_tokens: Optional[List[str]], max_tokens: int = 200) -> List[str]:
    """Validates and deduplicates blinded HMAC search token strings."""
    if not raw_tokens:
        return []
    cleaned: List[str] = []
    seen = set()
    for tok in raw_tokens:
        if not isinstance(tok, str):
            raise DomainValidationError("Each search token must be a string.")
        val = tok.strip()
        if not val or len(val) > 128:
            raise DomainValidationError("Each search token must be between 1 and 128 characters.")
        if val not in seen:
            seen.add(val)
            cleaned.append(val)
        if len(cleaned) >= max_tokens:
            break
    return cleaned


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
    search_tokens: Optional[List[str]] = None,
    shared_search_tokens: Optional[List[str]] = None,
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

    # Persist optional blinded HMAC search tokens for zero-knowledge chat history search
    owner_tokens = _normalize_token_list(search_tokens)
    shared_tokens = _normalize_token_list(shared_search_tokens)
    if owner_tokens or shared_tokens:
        token_objs = [
            MessageSearchToken(
                message=message,
                conversation=conversation,
                owner_user=None if sender_type == MessageSenderTypeEnum.GYM else sender_user,
                owner_gym=sender_gym if sender_type == MessageSenderTypeEnum.GYM else None,
                token_hash=tok,
            )
            for tok in owner_tokens
        ] + [
            MessageSearchToken(
                message=message,
                conversation=conversation,
                owner_user=None,
                owner_gym=None,
                token_hash=tok,
            )
            for tok in shared_tokens
        ]
        MessageSearchToken.objects.bulk_create(token_objs, ignore_conflicts=True)

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

    # Dispatch real-time FCM push notification (WITHOUT persisting generic in-app notification)
    try:
        from apps.notifications.services import send_message_push_notification
        sender_title = payload.get("sender_gym_name") or "New Message"
        if sender_type == MessageSenderTypeEnum.USER and sender_user:
            sender_title = f"{sender_user.first_name} {sender_user.last_name}".strip() or sender_user.email

        for user_id, gym_id in other_targets:
            if user_id:
                target_user = User.objects.filter(id=user_id).first()
                if target_user:
                    send_message_push_notification(
                        recipient_user=target_user,
                        title=sender_title,
                        body="Sent you an encrypted message.",
                        data={
                            "conversation_id": str(conversation.id),
                            "message_id": str(message.id),
                            "sender_id": str(sender_user.id) if sender_user else "",
                            "sender_type": message.sender_type,
                            "sent_at": message.sent_at.isoformat(),
                        },
                    )
            elif gym_id:
                from apps.access_control.models import GymStaffAssignment, StaffStatus
                staff_user_ids = list(
                    GymStaffAssignment.objects.filter(gym_id=gym_id, status=StaffStatus.ACTIVE).values_list("user_id", flat=True)
                )
                from apps.gyms.models import Gym
                gym_obj = Gym.objects.filter(id=gym_id).first()
                if gym_obj and getattr(gym_obj, "owner_user_id", None):
                    staff_user_ids.append(gym_obj.owner_user_id)

                for s_uid in set(staff_user_ids):
                    staff_user = User.objects.filter(id=s_uid).first()
                    if staff_user and staff_user.id != (sender_user.id if sender_user else None):
                        send_message_push_notification(
                            recipient_user=staff_user,
                            title=sender_title,
                            body="New incoming customer message.",
                            data={
                                "conversation_id": str(conversation.id),
                                "message_id": str(message.id),
                                "sender_id": str(sender_user.id) if sender_user else "",
                                "gym_id": str(gym_id),
                                "sender_type": message.sender_type,
                                "sent_at": message.sent_at.isoformat(),
                            },
                        )
    except Exception as exc:
        logger.warning(f"Failed to dispatch FCM message push notification: {exc}")

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


@transaction.atomic
def index_message_search_tokens(
    user: User,
    items: List[Dict[str, Any]],
    gym: Optional[Gym] = None,
) -> int:
    """
    Batch-indexes blinded HMAC search tokens for messages decrypted on the user's client device.
    Validates conversation access for every referenced message in minimal queries.
    """
    if not items:
        return 0

    msg_ids = [item["message_id"] for item in items]
    messages = list(
        EncryptedMessage.objects.filter(id__in=msg_ids)
        .select_related("conversation", "conversation__gym_a", "conversation__gym_b")
    )
    msg_map = {str(m.id): m for m in messages}

    if len(msg_map) != len(set(str(mid) for mid in msg_ids)):
        raise ResourceNotFoundError("One or more referenced messages were not found.")

    # Verify access once per unique conversation
    checked_convs = set()
    for msg in messages:
        if msg.conversation_id not in checked_convs:
            assert_can_access_conversation(user, msg.conversation, gym_context=gym)
            checked_convs.add(msg.conversation_id)

    token_objs: List[MessageSearchToken] = []
    for item in items:
        msg = msg_map[str(item["message_id"])]
        tokens = _normalize_token_list(item.get("tokens", []))
        for tok in tokens:
            token_objs.append(
                MessageSearchToken(
                    message=msg,
                    conversation=msg.conversation,
                    owner_user=None if gym else user,
                    owner_gym=gym,
                    token_hash=tok,
                )
            )

    if token_objs:
        MessageSearchToken.objects.bulk_create(token_objs, ignore_conflicts=True)

    return len(token_objs)
