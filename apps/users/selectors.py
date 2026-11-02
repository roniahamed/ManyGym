from typing import Optional, Iterator
import uuid
from django.db.models import QuerySet
from apps.users.models import User, UserProfile, UserFollow
from common.exceptions import ResourceNotFoundError, PermissionDeniedError, DomainValidationError


def get_user_by_email(email: str) -> Optional[User]:
    """Retrieve user with profile by normalized email using select_related."""
    return User.objects.select_related("profile").filter(email=email.lower().strip()).first()


def get_user_by_id(user_id) -> Optional[User]:
    """Retrieve user with profile by UUID using select_related."""
    try:
        uuid.UUID(str(user_id))
        return User.objects.select_related("profile").filter(id=user_id).first()
    except Exception:
        return None


def get_user_profile(user: User) -> UserProfile:
    """Retrieve or create user profile."""
    profile, _ = UserProfile.objects.select_related("user").get_or_create(user=user)
    return profile


def iter_users(chunk_size: int = 500) -> Iterator[User]:
    """
    Generator yielding users with profiles preloaded,
    streaming records via iterator() to minimize memory footprint.
    """
    for user in (
        User.objects.select_related("profile")
        .order_by("-created_at")
        .iterator(chunk_size=chunk_size)
    ):
        yield user


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

