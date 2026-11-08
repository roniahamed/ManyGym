import uuid
from typing import Any, Optional, Tuple, Union
from django.db import models, transaction

from apps.users.models import User, UserFollow, UserFollowRequest, FollowRequestStatus
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)


@transaction.atomic
def follow_user(follower: User, target_user_id) -> Tuple[Union[UserFollow, UserFollowRequest], bool]:
    """
    Follows a target user if target user is active, not self, and not private.
    If target user requires confirmation/approval, creates or updates a UserFollowRequest with status='pending'.
    Returns (UserFollow | UserFollowRequest, created: bool).
    """
    if isinstance(target_user_id, User):
        target_user = target_user_id
        target_uuid = target_user.id
    else:
        try:
            target_uuid = uuid.UUID(str(target_user_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid target user ID.")

        if follower.id == target_uuid:
            raise DomainValidationError("You cannot follow yourself.")

        try:
            target_user = User.objects.select_related("profile", "settings").get(id=target_uuid, is_active=True)
        except User.DoesNotExist:
            raise ResourceNotFoundError("Target user not found or is inactive.")

    if follower.id == target_uuid:
        raise DomainValidationError("You cannot follow yourself.")

    if not getattr(target_user, "is_active", True):
        raise ResourceNotFoundError("Target user not found or is inactive.")

    setting = target_user.get_settings()
    if setting.is_deleted:
        raise ResourceNotFoundError("Target user not found.")
    if setting.is_deactivated:
        raise DomainValidationError("This user account is deactivated.")

    from apps.users.models import UserBlockedUser
    if UserBlockedUser.objects.filter(blocker=target_user, blocked_user=follower).exists():
        raise PermissionDeniedError("You have been blocked by this user.")
    if UserBlockedUser.objects.filter(blocker=follower, blocked_user=target_user).exists():
        raise DomainValidationError("You cannot follow a user you have blocked. Unblock them first.")

    profile = getattr(target_user, "profile", None)
    if profile and profile.is_private:
        raise PermissionDeniedError("This user account is private.")

    # Check if already following
    existing_follow = UserFollow.objects.filter(
        follower=follower,
        followed_user=target_user,
    ).first()
    if existing_follow:
        return existing_follow, False

    # Check if target user requires approval before accepting followers
    if setting.require_follow_approval:
        pending_req = UserFollowRequest.objects.filter(
            requester=follower,
            target_user=target_user,
            status=FollowRequestStatus.PENDING,
        ).first()
        if pending_req:
            return pending_req, False

        req_obj, created = UserFollowRequest.objects.update_or_create(
            requester=follower,
            target_user=target_user,
            defaults={"status": FollowRequestStatus.PENDING},
        )
        return req_obj, True

    # Automatic follow (default)
    follow_instance, created = UserFollow.objects.get_or_create(
        follower=follower,
        followed_user=target_user,
    )
    # Clean up any lingering request
    UserFollowRequest.objects.filter(
        requester=follower,
        target_user=target_user,
    ).delete()
    return follow_instance, created


@transaction.atomic
def unfollow_user(follower: User, target_user_id) -> bool:
    """
    Unfollows a target user or cancels a pending follow request.
    """
    try:
        target_uuid = uuid.UUID(str(target_user_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid target user ID.")

    deleted_count, _ = UserFollow.objects.filter(
        follower=follower,
        followed_user_id=target_uuid,
    ).delete()

    if deleted_count > 0:
        UserFollowRequest.objects.filter(
            requester=follower,
            target_user_id=target_uuid,
        ).delete()
        return True

    # Check if there is an active pending follow request to cancel
    req_deleted, _ = UserFollowRequest.objects.filter(
        requester=follower,
        target_user_id=target_uuid,
        status=FollowRequestStatus.PENDING,
    ).delete()

    if req_deleted > 0:
        return True

    raise ResourceNotFoundError("You are not currently following this user.")


@transaction.atomic
def accept_follow_request(target_user: User, identifier) -> Tuple[UserFollow, UserFollowRequest]:
    """
    Accepts/confirms a pending follow request for target_user.
    Identifier can be either the request UUID or the requester's UUID.
    Creates UserFollow and transitions request status to ACCEPTED.
    """
    try:
        ident_uuid = uuid.UUID(str(identifier))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid ID format.")

    req = (
        UserFollowRequest.objects.select_related("requester", "target_user")
        .filter(
            models.Q(id=ident_uuid) | models.Q(requester_id=ident_uuid),
            target_user=target_user,
            status=FollowRequestStatus.PENDING,
        )
        .first()
    )
    if not req:
        raise ResourceNotFoundError("Pending follow request not found.")

    follow_instance, _ = UserFollow.objects.get_or_create(
        follower=req.requester,
        followed_user=target_user,
    )

    req.status = FollowRequestStatus.ACCEPTED
    req.save(update_fields=["status", "updated_at"])

    return follow_instance, req


@transaction.atomic
def reject_follow_request(target_user: User, identifier) -> UserFollowRequest:
    """
    Rejects/declines a pending follow request for target_user.
    Identifier can be either the request UUID or the requester's UUID.
    Transitions request status to REJECTED.
    """
    try:
        ident_uuid = uuid.UUID(str(identifier))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid ID format.")

    req = (
        UserFollowRequest.objects.select_related("requester", "target_user")
        .filter(
            models.Q(id=ident_uuid) | models.Q(requester_id=ident_uuid),
            target_user=target_user,
            status=FollowRequestStatus.PENDING,
        )
        .first()
    )
    if not req:
        raise ResourceNotFoundError("Pending follow request not found.")

    req.status = FollowRequestStatus.REJECTED
    req.save(update_fields=["status", "updated_at"])

    return req


@transaction.atomic
def cancel_follow_request(requester: User, identifier) -> UserFollowRequest:
    """
    Cancels/withdraws a pending follow request sent by requester.
    Identifier can be either the request UUID or the target user's UUID.
    Transitions request status to CANCELLED.
    """
    try:
        ident_uuid = uuid.UUID(str(identifier))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid ID format.")

    req = (
        UserFollowRequest.objects.select_related("requester", "target_user")
        .filter(
            models.Q(id=ident_uuid) | models.Q(target_user_id=ident_uuid),
            requester=requester,
            status=FollowRequestStatus.PENDING,
        )
        .first()
    )
    if not req:
        raise ResourceNotFoundError("Pending follow request not found.")

    req.status = FollowRequestStatus.CANCELLED
    req.save(update_fields=["status", "updated_at"])

    return req
