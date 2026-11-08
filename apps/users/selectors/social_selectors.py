from typing import Optional
import uuid
from django.db import models
from django.db.models import QuerySet

from apps.users.models import User, UserFollow, UserFollowRequest, FollowRequestStatus
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

    target_setting = target_user.get_settings()
    if target_setting.is_deleted:
        raise ResourceNotFoundError("User not found.")

    if target_setting.is_deactivated:
        if not requesting_user or requesting_user.id != target_user.id:
            raise DomainValidationError("This user account is deactivated.")

    from apps.users.models import UserBlockedUser
    from common.enums import UserAudienceVisibilityEnum

    if requesting_user and requesting_user.is_authenticated and requesting_user.id != target_user.id:
        if UserBlockedUser.objects.filter(blocker=target_user, blocked_user=requesting_user).exists():
            raise PermissionDeniedError("You have been blocked by this user.")

    profile = getattr(target_user, "profile", None)
    if profile and profile.is_private:
        if not requesting_user or requesting_user.id != target_user.id:
            raise PermissionDeniedError("This user account is private.")

    policy = target_setting.who_can_see_followers
    if policy == UserAudienceVisibilityEnum.PRIVATE and (not requesting_user or requesting_user.id != target_user.id):
        raise PermissionDeniedError("This user's followers list is private.")
    elif policy == UserAudienceVisibilityEnum.FOLLOWERS and (
        not requesting_user
        or (requesting_user.id != target_user.id and not is_following_user(requesting_user, target_user))
    ):
        raise PermissionDeniedError("Only followers can view this user's followers list.")

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

    target_setting = target_user.get_settings()
    if target_setting.is_deleted:
        raise ResourceNotFoundError("User not found.")

    if target_setting.is_deactivated:
        if not requesting_user or requesting_user.id != target_user.id:
            raise DomainValidationError("This user account is deactivated.")

    from apps.users.models import UserBlockedUser
    from common.enums import UserAudienceVisibilityEnum

    if requesting_user and requesting_user.is_authenticated and requesting_user.id != target_user.id:
        if UserBlockedUser.objects.filter(blocker=target_user, blocked_user=requesting_user).exists():
            raise PermissionDeniedError("You have been blocked by this user.")

    profile = getattr(target_user, "profile", None)
    if profile and profile.is_private:
        if not requesting_user or requesting_user.id != target_user.id:
            raise PermissionDeniedError("This user account is private.")

    policy = target_setting.who_can_see_following
    if policy == UserAudienceVisibilityEnum.PRIVATE and (not requesting_user or requesting_user.id != target_user.id):
        raise PermissionDeniedError("This user's following list is private.")
    elif policy == UserAudienceVisibilityEnum.FOLLOWERS and (
        not requesting_user
        or (requesting_user.id != target_user.id and not is_following_user(requesting_user, target_user))
    ):
        raise PermissionDeniedError("Only followers can view this user's following list.")

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


def has_pending_follow_request(requester, target_user) -> bool:
    """Returns True if requester has an active pending follow request to target_user."""
    r_id = getattr(requester, "id", requester)
    t_id = getattr(target_user, "id", target_user)
    if not r_id or not t_id:
        return False
    return UserFollowRequest.objects.filter(
        requester_id=r_id,
        target_user_id=t_id,
        status=FollowRequestStatus.PENDING,
    ).exists()


def list_received_follow_requests(user: User, status: Optional[str] = "pending") -> QuerySet[UserFollowRequest]:
    """Returns QuerySet of follow requests received by user."""
    qs = UserFollowRequest.objects.filter(target_user=user).select_related(
        "requester", "requester__profile"
    )
    if status and status.lower() != "all":
        qs = qs.filter(status=status.lower())
    return qs.order_by("-created_at")


def list_sent_follow_requests(user: User, status: Optional[str] = "pending") -> QuerySet[UserFollowRequest]:
    """Returns QuerySet of follow requests sent by user."""
    qs = UserFollowRequest.objects.filter(requester=user).select_related(
        "target_user", "target_user__profile"
    )
    if status and status.lower() != "all":
        qs = qs.filter(status=status.lower())
    return qs.order_by("-created_at")


def get_follow_request_by_id(user: User, request_id) -> UserFollowRequest:
    """Retrieves a follow request where user is either recipient or sender."""
    try:
        req_uuid = uuid.UUID(str(request_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid request ID format.")

    req = (
        UserFollowRequest.objects.select_related("requester", "target_user", "requester__profile", "target_user__profile")
        .filter(models.Q(target_user=user) | models.Q(requester=user), id=req_uuid)
        .first()
    )
    if not req:
        raise ResourceNotFoundError("Follow request not found.")
    return req


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
