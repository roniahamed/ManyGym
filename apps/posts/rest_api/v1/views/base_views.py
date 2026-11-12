import uuid
from typing import Optional, Tuple
from django.db.models import Q
from apps.gyms.models import Gym, GymSetting
from apps.access_control.models import GymStaffAssignment
from apps.members.models import Member
from apps.posts.models import GymPost
from common.enums import PostOwnerTypeEnum, StaffStatus, TokenContextType
from common.exceptions import DomainValidationError, ResourceNotFoundError, PermissionDeniedError


def _get_gym_by_id(gym_id, require_active: bool = False) -> Gym:
    try:
        gym_uuid = uuid.UUID(str(gym_id))
        gym = Gym.objects.select_related("settings").get(id=gym_uuid)
    except (Gym.DoesNotExist, ValueError, TypeError, AttributeError):
        raise ResourceNotFoundError("Gym not found.")

    setting = getattr(gym, "settings", None) or GymSetting.objects.filter(gym=gym).first()
    if setting and setting.is_deleted:
        raise ResourceNotFoundError("Gym not found.")
    if require_active and setting and setting.is_deactivated:
        raise DomainValidationError("This gym is deactivated.")
    return gym


def resolve_post_gym(request) -> Gym:
    """Helper to determine target gym from query param, active JWT context, or request body."""
    cached = getattr(request, "_resolved_gym", None)
    if cached is not None:
        return cached

    gym_id = (
        request.query_params.get("gym_id")
        or getattr(request, "gym_id", None)
        or (request.data.get("gym_id") if isinstance(request.data, dict) else None)
    )
    if not gym_id:
        raise DomainValidationError("An active Gym context token or 'gym_id' parameter is required.")
    gym = _get_gym_by_id(gym_id, require_active=False)
    request._resolved_gym = gym
    return gym


def resolve_post_owner_context(
    request,
    allow_explicit_gym_id: bool = True,
    require_active_gym: bool = True,
) -> Tuple[str, Optional[Gym]]:
    """
    Determines whether a post/repost operation is acting as a Public User ('user', None)
    or a Gym ('gym', Gym) from the authenticated Bearer token context (or optional explicit gym_id).
    """
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        setting = user.get_settings()
        if setting.is_deleted or setting.is_deactivated:
            raise PermissionDeniedError("Your account is deactivated or deleted.")

    if allow_explicit_gym_id:
        explicit_gym_id = (
            request.query_params.get("gym_id")
            or (request.data.get("gym_id") if isinstance(request.data, dict) else None)
        )
        if explicit_gym_id:
            gym = _get_gym_by_id(explicit_gym_id, require_active=require_active_gym)
            return PostOwnerTypeEnum.GYM, gym

    token_context = getattr(request, "token_context", TokenContextType.PERSONAL)
    token_gym_id = getattr(request, "gym_id", None)
    if token_context == TokenContextType.GYM and token_gym_id:
        gym = _get_gym_by_id(token_gym_id, require_active=require_active_gym)
        return PostOwnerTypeEnum.GYM, gym

    return PostOwnerTypeEnum.USER, None


def check_user_is_member_or_staff(request, gym: Gym) -> bool:
    """Returns True if the requesting user is the gym owner, staff member, or active member."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return False

    if gym.owner_user_id == user.id or user.is_superuser:
        return True

    if GymStaffAssignment.objects.filter(gym=gym, user=user, status=StaffStatus.ACTIVE).exists():
        return True

    if Member.objects.filter(gym=gym).filter(Q(email=user.email) | Q(user=user)).exists():
        return True

    return False


def check_post_management_permission(request, gym: Gym) -> None:
    """Enforces that only gym owner, superuser, or staff with 'posts:manage' scope can mutate gym posts."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        raise PermissionDeniedError("Authentication credentials were not provided.")

    if gym.owner_user_id == user.id or user.is_superuser:
        return

    assignment = GymStaffAssignment.objects.filter(
        gym=gym,
        user=user,
        status=StaffStatus.ACTIVE,
    ).first()

    if not assignment:
        raise PermissionDeniedError("You are not an active staff member of this gym.")

    if not assignment.role:
        raise PermissionDeniedError("You do not have permission to manage community posts.")

    has_perm = assignment.role.permissions.filter(scope_code="posts:manage").exists()
    if not has_perm:
        raise PermissionDeniedError("Missing required permission scope 'posts:manage'.")


def check_post_owner_manage_permission(request, post: GymPost) -> None:
    """Enforces management permission (PATCH / DELETE / thumbnail) on either a User post or a Gym post."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        raise PermissionDeniedError("Authentication credentials were not provided.")

    if post.owner_type == PostOwnerTypeEnum.USER or post.gym is None:
        if user.is_superuser or post.author_user_id == user.id:
            return
        raise PermissionDeniedError("You do not have permission to manage this user post.")

    # Cross-tenant guard: if caller is operating under a Gym token for a different gym
    token_context = getattr(request, "token_context", TokenContextType.PERSONAL)
    token_gym_id = getattr(request, "gym_id", None)
    if token_context == TokenContextType.GYM and token_gym_id and str(post.gym_id) != str(token_gym_id):
        raise ResourceNotFoundError("Post not found.")

    check_post_management_permission(request, post.gym)
