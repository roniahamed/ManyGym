from typing import Optional
import uuid
from django.db.models import QuerySet

from apps.users.models import User, UserFollow
from common.exceptions import ResourceNotFoundError, PermissionDeniedError, DomainValidationError


def list_user_followers(user_id, requesting_user: Optional[User] = None) -> QuerySet[UserFollow]:
    """
    Returns QuerySet of UserFollow relations where user_id is followed_user.
    Respects privacy settings: if target user is private, only target user can view.
    Optimized with field projections (only()) and eager relationship fetching.
    """
    if isinstance(user_id, User):
        target_user = user_id
    else:
        try:
            target_uuid = uuid.UUID(str(user_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid user ID.")

        target_user = (
            User.objects.select_related("profile")
            .only("id", "profile__id", "profile__is_private")
            .filter(id=target_uuid)
            .first()
        )
        if not target_user:
            raise ResourceNotFoundError("User not found.")

    profile = getattr(target_user, "profile", None)
    if profile and profile.is_private:
        if not requesting_user or requesting_user.id != target_user.id:
            raise PermissionDeniedError("This user account is private.")

    return (
        UserFollow.objects.filter(followed_user=target_user)
        .select_related("follower__profile")
        .only(
            "id",
            "created_at",
            "followed_user_id",
            "follower__id",
            "follower__email",
            "follower__first_name",
            "follower__last_name",
            "follower__profile__id",
            "follower__profile__avatar_url",
            "follower__profile__is_private",
        )
        .order_by("-created_at")
    )


def list_user_following(user_id, requesting_user: Optional[User] = None) -> QuerySet[UserFollow]:
    """
    Returns QuerySet of UserFollow relations where user_id is follower.
    Respects privacy settings: if target user is private, only target user can view.
    Optimized with field projections (only()) and eager relationship fetching.
    """
    if isinstance(user_id, User):
        target_user = user_id
    else:
        try:
            target_uuid = uuid.UUID(str(user_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid user ID.")

        target_user = (
            User.objects.select_related("profile")
            .only("id", "profile__id", "profile__is_private")
            .filter(id=target_uuid)
            .first()
        )
        if not target_user:
            raise ResourceNotFoundError("User not found.")

    profile = getattr(target_user, "profile", None)
    if profile and profile.is_private:
        if not requesting_user or requesting_user.id != target_user.id:
            raise PermissionDeniedError("This user account is private.")

    return (
        UserFollow.objects.filter(follower=target_user)
        .select_related("followed_user__profile")
        .only(
            "id",
            "created_at",
            "follower_id",
            "followed_user__id",
            "followed_user__email",
            "followed_user__first_name",
            "followed_user__last_name",
            "followed_user__profile__id",
            "followed_user__profile__avatar_url",
            "followed_user__profile__is_private",
        )
        .order_by("-created_at")
    )


def is_following_user(follower, target_user) -> bool:
    """Returns True if follower is actively following target_user."""
    f_id = getattr(follower, "id", follower)
    t_id = getattr(target_user, "id", target_user)
    if not f_id or not t_id:
        return False
    return UserFollow.objects.filter(
        follower_id=f_id,
        followed_user_id=t_id,
    ).exists()


class ResolvedTarget(tuple):
    """
    Tuple subclass representing (target_type, target_uuid) while holding the loaded entity
    to eliminate redundant subsequent database round-trips.
    """
    def __new__(cls, target_type, target_uuid, entity=None):
        return super().__new__(cls, (target_type, target_uuid))

    def __init__(self, target_type, target_uuid, entity=None):
        self.target_type = target_type
        self.target_uuid = target_uuid
        self.entity = entity


def resolve_target_entity(target_id, target_type=None) -> ResolvedTarget:
    """
    Validates target_id and auto-detects whether the entity is a Gym or a User.
    Optimized with single query execution, field projections, and relationship prefetching.
    Returns ResolvedTarget(target_type, target_uuid, entity_obj).
    """
    from apps.gyms.models import Gym

    if isinstance(target_id, Gym):
        return ResolvedTarget("gym", target_id.id, target_id)
    if isinstance(target_id, User):
        return ResolvedTarget("user", target_id.id, target_id)

    try:
        target_uuid = uuid.UUID(str(target_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid target ID format. Must be a valid UUID.")

    resolved_type = (target_type or "").strip().lower()

    if resolved_type == "gym":
        gym = (
            Gym.objects.select_related("settings")
            .only(
                "id",
                "name",
                "owner_user_id",
                "settings__id",
                "settings__is_deleted",
                "settings__is_deactivated",
                "settings__who_can_see_followers",
                "settings__who_can_see_following",
            )
            .filter(id=target_uuid)
            .first()
        )
        if not gym:
            raise ResourceNotFoundError("Target entity (Gym) not found.")
        return ResolvedTarget("gym", target_uuid, gym)

    if resolved_type == "user":
        user = (
            User.objects.select_related("profile")
            .only(
                "id",
                "first_name",
                "last_name",
                "is_active",
                "profile__id",
                "profile__is_private",
            )
            .filter(id=target_uuid)
            .first()
        )
        if not user:
            raise ResourceNotFoundError("Target entity (User) not found.")
        return ResolvedTarget("user", target_uuid, user)

    # Auto-detect whether target_id is a Gym or User in minimal DB round-trips
    gym = (
        Gym.objects.select_related("settings")
        .only(
            "id",
            "name",
            "owner_user_id",
            "settings__id",
            "settings__is_deleted",
            "settings__is_deactivated",
            "settings__who_can_see_followers",
            "settings__who_can_see_following",
        )
        .filter(id=target_uuid)
        .first()
    )
    if gym:
        return ResolvedTarget("gym", target_uuid, gym)

    user = (
        User.objects.select_related("profile")
        .only(
            "id",
            "first_name",
            "last_name",
            "is_active",
            "profile__id",
            "profile__is_private",
        )
        .filter(id=target_uuid)
        .first()
    )
    if user:
        return ResolvedTarget("user", target_uuid, user)

    raise ResourceNotFoundError("Target entity (User or Gym) not found.")
