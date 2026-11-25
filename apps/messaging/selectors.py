"""
Read-side queries and selectors for End-to-End Encrypted Messaging.
Provides optimized, N+1-safe queries for conversations, message histories, and public key bundles.
"""

import uuid
from typing import Optional, List, Dict, Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q, QuerySet, Value, Count, Max
from django.db.models.functions import Concat
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.users.models import User, UserProfile, UserFollow, UserBlockedUser
from apps.gyms.models import Gym
from apps.messaging.models import (
    UserDeviceKey,
    GymDeviceKey,
    UserE2EEBackup,
    Conversation,
    EncryptedMessage,
    MessageSearchToken,
)
from apps.messaging.permissions import assert_can_access_conversation
from common.enums import ConversationTypeEnum, UserAudienceMessagingEnum
from common.exceptions import DomainValidationError, PermissionDeniedError, ResourceNotFoundError


def resolve_user_instance(identifier: str) -> User:
    """
    Seamlessly resolves a User whether the caller provides:
    - User.id (Account UUID)
    - UserProfile.id (Profile UUID)
    """
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


def get_user_e2ee_backup_public_key(user_identifier: str) -> Optional[Dict[str, Any]]:
    """
    Returns the user's active E2EE Master/Backup public key metadata (if configured),
    allowing senders to wrap message session keys so the recipient's future new devices can decrypt history.
    """
    user = resolve_user_instance(user_identifier)
    backup = (
        UserE2EEBackup.objects.filter(user=user, is_active=True)
        .values("backup_public_key", "backup_key_fingerprint", "key_version")
        .first()
    )
    return backup


def get_user_e2ee_backup_status(user: User) -> Dict[str, Any]:
    """
    Returns Messenger-style E2EE PIN/password backup status and KDF parameters (without encrypted blob).
    """
    backup = UserE2EEBackup.objects.filter(user=user, is_active=True).first()
    if not backup:
        return {
            "has_backup": False,
            "secret_type": None,
            "pin_length": 5,
            "kdf_algorithm": None,
            "kdf_iterations": None,
            "cipher_algorithm": None,
            "salt": None,
            "backup_public_key": None,
            "backup_key_fingerprint": None,
            "key_version": 0,
            "failed_attempts": 0,
            "max_attempts": 10,
            "remaining_attempts": 10,
            "is_locked": False,
            "locked_until": None,
            "requires_auth_proof": False,
            "has_recovery_bundle": False,
            "last_restored_at": None,
        }

    now = timezone.now()
    is_locked = bool(backup.locked_until and backup.locked_until > now)
    remaining = 0 if is_locked else max(0, backup.max_attempts - backup.failed_attempts)
    return {
        "has_backup": True,
        "secret_type": backup.secret_type,
        "pin_length": backup.pin_length,
        "kdf_algorithm": backup.kdf_algorithm,
        "kdf_iterations": backup.kdf_iterations,
        "cipher_algorithm": backup.cipher_algorithm,
        "salt": backup.salt,
        "backup_public_key": backup.backup_public_key,
        "backup_key_fingerprint": backup.backup_key_fingerprint,
        "key_version": backup.key_version,
        "failed_attempts": backup.failed_attempts,
        "max_attempts": backup.max_attempts,
        "remaining_attempts": remaining,
        "is_locked": is_locked,
        "locked_until": backup.locked_until,
        "requires_auth_proof": bool(backup.verifier_hash),
        "has_recovery_bundle": bool(backup.recovery_encrypted_bundle),
        "last_restored_at": backup.last_restored_at,
    }


def get_user_e2ee_backup_for_fetch(user: User) -> UserE2EEBackup:
    """
    Fetches the user's active E2EE backup record, enforcing lockout checks.
    """
    backup = UserE2EEBackup.objects.filter(user=user, is_active=True).first()
    if not backup:
        raise ResourceNotFoundError("No active E2EE backup found for this account.")
    if backup.locked_until and backup.locked_until > timezone.now():
        raise PermissionDeniedError(
            "E2EE backup is temporarily locked due to too many failed attempts.",
            details={
                "is_locked": True,
                "locked_until": backup.locked_until.isoformat(),
            },
        )
    return backup


def search_people_to_message(
    user: User,
    query: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Searches people to message strictly from the authenticated user's Follows + Followers.
    Deduplicates mutual connections, excludes self, blocked users, and deleted/deactivated accounts,
    and enriches results with existing conversation IDs and E2EE readiness in constant queries.
    """
    if query is not None and "\x00" in query:
        raise DomainValidationError("Null characters are not allowed in search query.")

    safe_limit = min(max(int(limit or 20), 1), 50)

    follow_pairs = UserFollow.objects.filter(
        Q(follower=user) | Q(followed_user=user)
    ).values_list("follower_id", "followed_user_id")

    following_ids = set()
    follower_ids = set()
    for f_id, t_id in follow_pairs:
        if f_id == user.id and t_id != user.id:
            following_ids.add(t_id)
        if t_id == user.id and f_id != user.id:
            follower_ids.add(f_id)

    candidate_ids = following_ids | follower_ids

    if not candidate_ids:
        return []

    blocked_pairs = UserBlockedUser.objects.filter(
        Q(blocker=user, blocked_user_id__in=candidate_ids)
        | Q(blocked_user=user, blocker_id__in=candidate_ids)
    ).values_list("blocker_id", "blocked_user_id")
    blocked_ids = set()
    for blocker_id, blocked_user_id in blocked_pairs:
        if blocker_id != user.id:
            blocked_ids.add(blocker_id)
        if blocked_user_id != user.id:
            blocked_ids.add(blocked_user_id)

    allowed_ids = candidate_ids - blocked_ids
    if not allowed_ids:
        return []

    qs = (
        User.objects.filter(id__in=allowed_ids, is_active=True)
        .exclude(settings__is_deleted=True)
        .exclude(settings__is_deactivated=True)
        .select_related("profile", "settings")
        .only(
            "id",
            "email",
            "first_name",
            "last_name",
            "profile__id",
            "profile__avatar_url",
            "profile__is_private",
            "settings__id",
            "settings__who_can_message",
        )
    )

    if query and query.strip():
        q = query.strip()
        qs = qs.annotate(
            full_name_concat=Concat("first_name", Value(" "), "last_name")
        ).filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(full_name_concat__icontains=q)
            | Q(email__icontains=q)
        )

    matched_users = list(qs.order_by("first_name", "last_name")[:safe_limit])
    if not matched_users:
        return []

    matched_ids = [u.id for u in matched_users]

    # Batch-resolve existing 1-on-1 conversations
    conv_rows = Conversation.objects.filter(
        conversation_type=ConversationTypeEnum.USER_TO_USER
    ).filter(
        Q(user_a=user, user_b_id__in=matched_ids)
        | Q(user_b=user, user_a_id__in=matched_ids)
    ).values_list("id", "user_a_id", "user_b_id")

    conv_by_peer: Dict[uuid.UUID, str] = {}
    for conv_id, ua_id, ub_id in conv_rows:
        peer_id = ub_id if ua_id == user.id else ua_id
        conv_by_peer[peer_id] = str(conv_id)

    # Batch-resolve E2EE readiness (device key or backup public key)
    device_key_user_ids = set(
        UserDeviceKey.objects.filter(user_id__in=matched_ids, is_active=True)
        .values_list("user_id", flat=True)
    )
    backup_key_user_ids = set(
        UserE2EEBackup.objects.filter(user_id__in=matched_ids, is_active=True)
        .values_list("user_id", flat=True)
    )

    results: List[Dict[str, Any]] = []
    for target in matched_users:
        is_following = target.id in following_ids
        is_follower = target.id in follower_ids
        if is_following and is_follower:
            relationship = "mutual"
        elif is_following:
            relationship = "following"
        else:
            relationship = "follower"

        setting = getattr(target, "settings", None)
        policy = getattr(setting, "who_can_message", UserAudienceMessagingEnum.FOLLOWERS)
        if policy == UserAudienceMessagingEnum.NO_ONE:
            can_message = False
        elif policy == UserAudienceMessagingEnum.FOLLOWERS:
            can_message = is_following
        else:
            can_message = True

        profile = getattr(target, "profile", None)
        full_name = f"{target.first_name} {target.last_name}".strip()
        results.append(
            {
                "user_id": str(target.id),
                "profile_id": str(profile.id) if profile else None,
                "email": target.email,
                "first_name": target.first_name,
                "last_name": target.last_name,
                "full_name": full_name,
                "avatar_url": getattr(profile, "avatar_url", None),
                "is_private": getattr(profile, "is_private", False),
                "is_following": is_following,
                "is_follower": is_follower,
                "relationship": relationship,
                "can_message": can_message,
                "conversation_id": conv_by_peer.get(target.id),
                "has_e2ee_keys": (target.id in device_key_user_ids) or (target.id in backup_key_user_ids),
            }
        )

    return results


def get_gym_public_key_bundle(gym_id: str) -> List[Dict[str, Any]]:
    """
    Returns active public cryptographic key bundles for a gym entity.
    Validates UUID format and verifies gym existence.
    """
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


def _resolve_message_cursor_timestamp(conversation: Conversation, cursor_value: str):
    """Resolves either a message UUID or an ISO-8601 datetime string into a timestamp cursor."""
    if not cursor_value:
        return None
    val = str(cursor_value).strip()
    try:
        msg_uuid = uuid.UUID(val)
        msg_ts = (
            EncryptedMessage.objects.filter(conversation=conversation, id=msg_uuid)
            .values_list("sent_at", flat=True)
            .first()
        )
        if msg_ts is None:
            raise ResourceNotFoundError("Cursor message not found in this conversation.")
        return msg_ts
    except (ValueError, TypeError):
        dt = parse_datetime(val)
        if dt is None:
            raise DomainValidationError("Invalid cursor format. Provide a message UUID or ISO-8601 timestamp.")
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt


def list_conversation_messages(
    conversation_id: str,
    user: User,
    gym: Optional[Gym] = None,
    limit: int = 50,
    before: Optional[str] = None,
    after: Optional[str] = None,
    order: str = "asc",
) -> QuerySet[EncryptedMessage]:
    """
    Retrieves encrypted messages for a conversation for client decryption & new-device history sync.
    Supports optional `before` / `after` cursors and `order` ('asc' default or 'desc' for newest-first).
    """
    conversation = get_conversation_by_id(conversation_id, user, gym=gym, prefetch_participants=False)

    qs = (
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
    )

    if before:
        before_ts = _resolve_message_cursor_timestamp(conversation, before)
        qs = qs.filter(sent_at__lt=before_ts)
    if after:
        after_ts = _resolve_message_cursor_timestamp(conversation, after)
        qs = qs.filter(sent_at__gt=after_ts)

    ordering = "-sent_at" if str(order).lower() == "desc" else "sent_at"
    return qs.order_by(ordering)[:limit]


def search_chat_history(
    user: User,
    tokens: List[str],
    gym: Optional[Gym] = None,
    conversation_id: Optional[str] = None,
    match_mode: str = "all",
    limit: int = 20,
    matches_per_chat: int = 5,
) -> Dict[str, Any]:
    """
    WhatsApp-style zero-knowledge chat history search across conversations.
    Matches blinded HMAC-SHA256 keyword tokens and returns matching conversations
    along with their matching EncryptedMessage records so the client decrypts & highlights locally.
    """
    cleaned_tokens: List[str] = []
    seen = set()
    for tok in tokens or []:
        if not isinstance(tok, str):
            raise DomainValidationError("Each search token must be a string.")
        val = tok.strip()
        if not val:
            continue
        if len(val) > 128:
            raise DomainValidationError("Search token exceeds maximum length of 128 characters.")
        if val not in seen:
            seen.add(val)
            cleaned_tokens.append(val)
        if len(cleaned_tokens) >= 20:
            break

    if not cleaned_tokens:
        raise DomainValidationError("At least one blinded search token is required.")

    safe_limit = min(max(int(limit or 20), 1), 50)
    safe_matches_per_chat = min(max(int(matches_per_chat or 5), 1), 20)
    normalized_mode = (match_mode or "all").strip().lower()
    if normalized_mode not in ("all", "any"):
        raise DomainValidationError("match_mode must be 'all' or 'any'.")

    # Scope to conversations accessible by the user (or active gym context)
    if gym:
        conv_access_q = (
            Q(conversation__gym_a=gym)
            | Q(conversation__gym_b=gym)
            | Q(conversation__participants__gym=gym)
        )
        owner_q = Q(owner_gym=gym) | Q(owner_user__isnull=True, owner_gym__isnull=True)
    else:
        conv_access_q = (
            Q(conversation__user_a=user)
            | Q(conversation__user_b=user)
            | Q(conversation__participants__user=user)
        )
        owner_q = Q(owner_user=user) | Q(owner_user__isnull=True, owner_gym__isnull=True)

    token_qs = MessageSearchToken.objects.filter(
        conv_access_q,
        owner_q,
        token_hash__in=cleaned_tokens,
    )

    if conversation_id:
        target_conv = get_conversation_by_id(str(conversation_id), user, gym=gym, prefetch_participants=False)
        token_qs = token_qs.filter(conversation=target_conv)

    if normalized_mode == "all" and len(cleaned_tokens) > 1:
        matching_msg_ids_qs = (
            token_qs.values("message_id")
            .annotate(tok_cnt=Count("token_hash", distinct=True))
            .filter(tok_cnt=len(cleaned_tokens))
            .values("message_id")
        )
        base_msg_qs = EncryptedMessage.objects.filter(id__in=matching_msg_ids_qs)
    else:
        matching_msg_ids_qs = token_qs.values("message_id").distinct()
        base_msg_qs = EncryptedMessage.objects.filter(id__in=matching_msg_ids_qs)

    # Aggregate matches per conversation ordered by latest match timestamp
    conv_aggs = list(
        base_msg_qs.values("conversation_id")
        .annotate(
            match_count=Count("id", distinct=True),
            latest_match_at=Max("sent_at"),
        )
        .order_by("-latest_match_at")[:safe_limit]
    )

    if not conv_aggs:
        return {
            "total_conversations": 0,
            "total_matches": 0,
            "results": [],
        }

    top_conv_ids = [row["conversation_id"] for row in conv_aggs]

    # Fetch conversation objects with N+1-safe prefetching
    conv_objs = (
        Conversation.objects.filter(id__in=top_conv_ids)
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
    )
    conv_map = {c.id: c for c in conv_objs}

    # Fetch matching messages across the top conversations in 1 query
    matched_messages = list(
        base_msg_qs.filter(conversation_id__in=top_conv_ids)
        .select_related("sender_user", "sender_gym")
        .order_by("-sent_at")
    )

    msgs_by_conv: Dict[uuid.UUID, List[EncryptedMessage]] = {cid: [] for cid in top_conv_ids}
    for msg in matched_messages:
        bucket = msgs_by_conv.get(msg.conversation_id)
        if bucket is not None and len(bucket) < safe_matches_per_chat:
            bucket.append(msg)

    total_matches = sum(row["match_count"] for row in conv_aggs)
    results = []
    for row in conv_aggs:
        cid = row["conversation_id"]
        conv_obj = conv_map.get(cid)
        if not conv_obj:
            continue
        results.append(
            {
                "conversation": conv_obj,
                "match_count": row["match_count"],
                "latest_match_at": row["latest_match_at"],
                "matches": msgs_by_conv.get(cid, []),
            }
        )

    return {
        "total_conversations": len(results),
        "total_matches": total_matches,
        "results": results,
    }
