import uuid
from typing import Optional
from django.db import models
from django.db.models import Q
from apps.gyms.models import Gym, GymSetting, GymBlockedUser
from apps.users.models import User


def get_gym_settings(gym_id: str) -> Optional[GymSetting]:
    """
    Retrieves gym settings with field projections, auto-creating default settings if not present.
    """
    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return None

    settings_obj = (
        GymSetting.objects.filter(gym_id=gym_id)
        .only(
            "id",
            "gym_id",
            "language",
            "video_autoplay",
            "dark_mode",
            "admin_logs_alerts",
            "issues_alerts",
            "who_can_message",
            "who_can_send_joining_request",
            "who_can_see_members",
            "who_can_see_followers",
            "who_can_see_following",
            "posts_age_restriction",
            "is_deactivated",
            "deactivated_at",
            "is_published",
            "unpublished_at",
            "is_deleted",
            "deleted_at",
            "created_at",
            "updated_at",
        )
        .first()
    )
    if not settings_obj:
        gym = Gym.objects.filter(id=gym_id).only("id", "name").first()
        if gym:
            settings_obj, _ = GymSetting.objects.get_or_create(gym=gym)
    return settings_obj


def list_blocked_users_for_gym(gym_id: str) -> "models.QuerySet[GymBlockedUser]":
    """
    Lists all users blocked by the given gym with select_related and field projections.
    """
    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return GymBlockedUser.objects.none()

    return (
        GymBlockedUser.objects.filter(gym_id=gym_id)
        .select_related("user", "user__profile", "blocked_by")
        .only(
            "id",
            "gym_id",
            "user_id",
            "reason",
            "created_at",
            "user__id",
            "user__email",
            "user__first_name",
            "user__last_name",
            "user__profile__id",
            "user__profile__user_id",
            "user__profile__avatar_url",
            "blocked_by__id",
            "blocked_by__email",
        )
        .order_by("-created_at")
    )


def search_users_to_block_for_gym(
    gym_id: str,
    query: Optional[str] = None,
    limit: int = 20,
) -> "models.QuerySet[User]":
    """
    Searches active Manygym users eligible for blocking.
    Excludes the gym owner and already blocked accounts.
    """
    try:
        uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        return User.objects.none()

    gym = Gym.objects.filter(id=gym_id).only("id", "owner_user_id").first()
    if not gym:
        return User.objects.none()

    blocked_user_ids = GymBlockedUser.objects.filter(gym_id=gym_id).values_list("user_id", flat=True)

    qs = (
        User.objects.filter(is_active=True)
        .exclude(id=gym.owner_user_id)
        .exclude(id__in=blocked_user_ids)
        .select_related("profile")
        .only(
            "id",
            "email",
            "first_name",
            "last_name",
            "profile__id",
            "profile__user_id",
            "profile__avatar_url",
        )
    )

    if query and query.strip():
        q = query.strip()
        qs = qs.filter(
            Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )

    return qs.order_by("first_name", "last_name", "email")[:limit]
