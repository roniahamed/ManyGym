"""
Read-side queries and selectors for End-to-End Encrypted Messaging.
Provides optimized, N+1-safe queries for conversations, message histories, and public key bundles.
"""

from typing import Optional, List, Dict, Any
from django.db.models import Q, QuerySet

from apps.users.models import User
from apps.gyms.models import Gym
from apps.messaging.models import (
    UserDeviceKey,
    GymDeviceKey,
    Conversation,
    ConversationParticipant,
    EncryptedMessage,
)
from apps.messaging.permissions import assert_can_access_conversation
from common.exceptions import ResourceNotFoundError


def resolve_user_instance(identifier: str) -> User:
    """
    Seamlessly resolves a User whether the caller provides:
    - User.id (Account UUID)
    - UserProfile.id (Profile UUID)
    """
    import uuid
    from apps.users.models import UserProfile

    try:
        uuid_val = uuid.UUID(str(identifier))
    except (ValueError, TypeError, AttributeError):
        raise ResourceNotFoundError("Invalid user identifier format.")

    # 1. Match User by primary account id
    user = User.objects.filter(id=uuid_val).first()
    if user:
        return user

    # 2. Match User via linked UserProfile id
    profile = UserProfile.objects.select_related("user").filter(id=uuid_val).first()
    if profile and profile.user:
        return profile.user

    raise ResourceNotFoundError("User not found.")


def get_user_public_key_bundle(user_identifier: str) -> List[Dict[str, Any]]:
    """
    Returns active public cryptographic key bundles for all registered devices of a user.
    Supports either account user_id or profile_id.
    """
    user = resolve_user_instance(user_identifier)
    keys = UserDeviceKey.objects.filter(
        user=user,
        is_active=True,
    ).values(
        "device_id",
        "device_name",
        "algorithm",
        "identity_key",
        "signed_prekey",
        "signed_prekey_signature",
        "one_time_prekeys",
    )
    return list(keys)


def get_gym_public_key_bundle(gym_id: str) -> List[Dict[str, Any]]:
    """
    Returns active public cryptographic key bundles for a gym entity.
    Validates UUID format and verifies gym existence.
    """
    import uuid
    from django.core.exceptions import ValidationError as DjangoValidationError

    try:
        uuid_val = uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        raise ResourceNotFoundError("Invalid gym identifier format.")

    if not Gym.objects.filter(id=uuid_val).exists():
        raise ResourceNotFoundError("Gym not found.")

    keys = GymDeviceKey.objects.filter(
        gym_id=uuid_val,
        is_active=True,
    ).values(
        "device_id",
        "device_name",
        "algorithm",
        "identity_key",
        "signed_prekey",
        "signed_prekey_signature",
        "one_time_prekeys",
    )
    return list(keys)


def list_conversations_for_entity(
    user: User,
    gym: Optional[Gym] = None,
    limit: Optional[int] = None,
) -> QuerySet[Conversation]:
    """
    Retrieves all conversations for an entity with zero N+1 queries.
    Uses select_related for 1-to-1 relationships (user profiles) and
    prefetch_related for participants and their profiles.
    """
    base_filter = (
        Q(gym_a=gym) | Q(gym_b=gym) | Q(participants__gym=gym)
        if gym
        else Q(user_a=user) | Q(user_b=user) | Q(participants__user=user)
    )

    qs = (
        Conversation.objects.filter(base_filter)
        .distinct()
        .select_related(
            "user_a",
            "user_a__profile",
            "user_b",
            "user_b__profile",
            "gym_a",
            "gym_b",
        )
        .prefetch_related(
            "participants__user__profile",
            "participants__gym",
        )
        .order_by("-last_message_at", "-created_at")
    )

    if limit is not None and limit > 0:
        qs = qs[:limit]

    return qs


def get_conversation_by_id(
    conversation_id: str,
    user: User,
    gym: Optional[Gym] = None,
    prefetch_participants: bool = True,
) -> Conversation:
    """
    Retrieves a single conversation, verifying that the requesting user/gym has access.
    Handles UUID format validation safely.
    Allows skipping prefetching participants when only validating access or dispatching messages.
    """
    import uuid
    from django.core.exceptions import ValidationError as DjangoValidationError

    try:
        uuid_val = uuid.UUID(str(conversation_id))
    except (ValueError, TypeError, AttributeError):
        raise ResourceNotFoundError("Conversation not found.")

    try:
        qs = Conversation.objects.select_related("gym_a", "gym_b")
        if prefetch_participants:
            qs = qs.select_related(
                "user_a",
                "user_a__profile",
                "user_b",
                "user_b__profile",
            ).prefetch_related(
                "participants__user__profile",
                "participants__gym",
            )
        else:
            qs = qs.only("id", "conversation_type", "user_a_id", "user_b_id", "gym_a_id", "gym_b_id")

        conversation = qs.get(id=uuid_val)
    except (Conversation.DoesNotExist, DjangoValidationError, ValueError):
        raise ResourceNotFoundError("Conversation not found.")

    assert_can_access_conversation(user, conversation, gym_context=gym)
    return conversation


def list_conversation_messages(
    conversation_id: str,
    user: User,
    gym: Optional[Gym] = None,
    limit: int = 50,
) -> QuerySet[EncryptedMessage]:
    """
    Retrieves encrypted messages for a conversation, ordered chronologically for client decryption.
    Selects only needed fields and skips unneeded participant prefetching.
    """
    conversation = get_conversation_by_id(conversation_id, user, gym=gym, prefetch_participants=False)

    return (
        EncryptedMessage.objects.filter(conversation=conversation)
        .select_related("sender_user", "sender_gym")
        .only(
            "id",
            "conversation_id",
            "sender_type",
            "sender_user_id",
            "sender_user__id",
            "sender_user__first_name",
            "sender_user__last_name",
            "sender_gym_id",
            "sender_gym__id",
            "sender_gym__name",
            "sender_device_id",
            "ciphertext",
            "nonce",
            "ephemeral_public_key",
            "recipient_key_fingerprint",
            "encrypted_keys",
            "delivery_status",
            "sent_at",
            "delivered_at",
            "read_at",
        )
        .order_by("sent_at")[:limit]
    )
