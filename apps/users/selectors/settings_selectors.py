from typing import Optional
from django.db import models
from apps.users.models import User, UserSetting, UserBlockedUser
from common.exceptions import ResourceNotFoundError, DomainValidationError


def get_user_settings(user: User) -> UserSetting:
    """
    Retrieves or auto-provisions settings for the given user.
    """
    setting, _ = UserSetting.objects.select_related("user", "user__profile").get_or_create(user=user)
    return setting


def list_blocked_users_for_user(user: User) -> models.QuerySet[UserBlockedUser]:
    """
    Returns QuerySet of users blocked by the given user, with avatar and user projections.
    """
    return (
        UserBlockedUser.objects.filter(blocker=user)
        .select_related("blocked_user", "blocked_user__profile")
        .only(
            "id",
            "created_at",
            "reason",
            "blocker_id",
            "blocked_user__id",
            "blocked_user__email",
            "blocked_user__first_name",
            "blocked_user__last_name",
            "blocked_user__profile__id",
            "blocked_user__profile__avatar_url",
        )
        .order_by("-created_at")
    )


def search_users_to_block_for_user(user: User, query: Optional[str] = None) -> models.QuerySet[User]:
    """
    Searches active users to select for blocking, excluding self and already blocked users.
    """
    already_blocked_ids = UserBlockedUser.objects.filter(blocker=user).values_list("blocked_user_id", flat=True)

    qs = (
        User.objects.filter(is_active=True)
        .exclude(id=user.id)
        .exclude(id__in=already_blocked_ids)
        .select_related("profile")
        .only(
            "id",
            "email",
            "first_name",
            "last_name",
            "profile__id",
            "profile__avatar_url",
        )
        .order_by("first_name", "last_name")
    )

    if query and query.strip():
        q = query.strip()
        if "\x00" in q:
            raise DomainValidationError("Null characters are not allowed.")
        qs = qs.filter(
            models.Q(email__icontains=q)
            | models.Q(first_name__icontains=q)
            | models.Q(last_name__icontains=q)
        )

    return qs[:50]


def is_user_blocked_by(blocker: User, target_user: User) -> bool:
    """Returns True if target_user is blocked by blocker."""
    if not blocker or not target_user:
        return False
    return UserBlockedUser.objects.filter(blocker=blocker, blocked_user=target_user).exists()

