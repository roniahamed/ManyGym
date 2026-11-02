from typing import Optional, Dict, Any
from django.db import transaction
from django.utils import timezone

from apps.users.models import User
from apps.gyms.models import Gym
from apps.messaging.models import (
    Conversation,
    ConversationParticipant,
)
from apps.messaging.permissions import (
    can_user_message_gym,
    is_user_authorized_for_gym,
    assert_can_access_conversation,
)
from apps.messaging.services.device_keys import broadcast_realtime_event
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
def initiate_conversation(
    initiator_user: User,
    validated_data: Dict[str, Any],
    gym_context: Optional[Gym] = None,
) -> Conversation:
    """
    Orchestrates conversation creation and entity channel resolution.
    Supports user_to_user, user_to_gym, gym_to_user, and gym_to_gym channels.
    Auto-detects channel type if omitted based on provided target identifiers.
    """
    from apps.messaging.selectors import resolve_user_instance

    source_gym_id = validated_data.get("source_gym_id") or getattr(gym_context, "id", None)
    target_user_id = validated_data.get("target_user_id")
    target_gym_id = validated_data.get("target_gym_id")
    conv_type = validated_data.get("conversation_type", "")

    # Auto-detect conversation_type if omitted
    if not conv_type:
        if source_gym_id and target_gym_id:
            conv_type = ConversationTypeEnum.GYM_TO_GYM
        elif (source_gym_id and target_user_id) or target_gym_id:
            conv_type = ConversationTypeEnum.USER_TO_GYM
        elif target_user_id:
            conv_type = ConversationTypeEnum.USER_TO_USER
        else:
            raise DomainValidationError("Please provide target_user_id or target_gym_id to start a conversation.")

    if conv_type == ConversationTypeEnum.USER_TO_USER:
        if not target_user_id:
            raise DomainValidationError("target_user_id is required for User to User messaging.")
        target_user = resolve_user_instance(target_user_id)
        return get_or_create_user_to_user_conversation(initiator_user, target_user)

    elif conv_type == ConversationTypeEnum.USER_TO_GYM:
        if source_gym_id and target_user_id:
            # Gym initiating chat with User (Gym -> User)
            try:
                source_gym = Gym.objects.get(id=source_gym_id)
            except Gym.DoesNotExist:
                raise ResourceNotFoundError("Gym not found.")
            target_user = resolve_user_instance(target_user_id)
            return get_or_create_user_to_gym_conversation(
                user=target_user,
                gym=source_gym,
                initiated_by="gym",
                initiator_user=initiator_user,
            )
        elif target_gym_id:
            # User initiating chat with Gym (User -> Gym)
            try:
                target_gym = Gym.objects.get(id=target_gym_id)
            except Gym.DoesNotExist:
                raise ResourceNotFoundError("Target gym not found.")
            return get_or_create_user_to_gym_conversation(
                user=initiator_user,
                gym=target_gym,
                initiated_by="user",
                initiator_user=initiator_user,
            )
        else:
            raise DomainValidationError(
                "Either 'target_gym_id' (for User -> Gym) or 'source_gym_id' with 'target_user_id' (for Gym -> User) must be provided."
            )

    elif conv_type == ConversationTypeEnum.GYM_TO_GYM:
        if not source_gym_id or not target_gym_id:
            raise DomainValidationError("source_gym_id and target_gym_id are required for Gym to Gym messaging.")

        try:
            source_gym = Gym.objects.get(id=source_gym_id)
            target_gym = Gym.objects.get(id=target_gym_id)
        except Gym.DoesNotExist:
            raise ResourceNotFoundError("Gym not found.")

        return get_or_create_gym_to_gym_conversation(initiator_user, source_gym, target_gym)

    else:
        raise DomainValidationError(f"Unsupported conversation type: {conv_type}")


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
