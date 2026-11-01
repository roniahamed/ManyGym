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
    """
    keys = GymDeviceKey.objects.filter(
        gym_id=gym_id,
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


def list_conversations_for_entity(user: User, gym: Optional[Gym] = None) -> QuerySet[Conversation]:
    """
    Retrieves all conversations where either:
    - In Personal mode: the user is user_a or user_b, or has a user participant record.
    - In Gym mode: the gym is gym_a or gym_b, or has a gym participant record.
    """
    if gym:
        return (
            Conversation.objects.filter(
                Q(gym_a=gym) | Q(gym_b=gym) | Q(participants__gym=gym)
            )
            .distinct()
            .select_related("user_a", "user_b", "gym_a", "gym_b")
            .prefetch_related("participants__user", "participants__gym")
            .order_by("-last_message_at", "-created_at")
        )

    return (
        Conversation.objects.filter(
            Q(user_a=user) | Q(user_b=user) | Q(participants__user=user)
        )
        .distinct()
        .select_related("user_a", "user_b", "gym_a", "gym_b")
        .prefetch_related("participants__user", "participants__gym")
        .order_by("-last_message_at", "-created_at")
    )


def get_conversation_by_id(conversation_id: str, user: User, gym: Optional[Gym] = None) -> Conversation:
    """
    Retrieves a single conversation, verifying that the requesting user/gym has access.
    """
    try:
        conversation = (
            Conversation.objects.select_related("user_a", "user_b", "gym_a", "gym_b")
            .prefetch_related("participants__user", "participants__gym")
            .get(id=conversation_id)
        )
    except (Conversation.DoesNotExist, ValueError):
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
    """
    conversation = get_conversation_by_id(conversation_id, user, gym=gym)

    return (
        EncryptedMessage.objects.filter(conversation=conversation)
        .select_related("sender_user", "sender_gym")
        .order_by("sent_at")[:limit]
    )
