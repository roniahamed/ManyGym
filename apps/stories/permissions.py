import uuid
from typing import Optional, Tuple
from apps.gyms.models import Gym, GymSetting
from apps.access_control.models import GymStaffAssignment
from apps.stories.models import Story
from common.enums import StaffStatus, StoryOwnerTypeEnum, TokenContextType
from common.exceptions import (
    DomainValidationError,
    PermissionDeniedError,
    ResourceNotFoundError,
)


def _get_gym_setting(gym: Gym) -> Optional[GymSetting]:
    setting = getattr(gym, "settings", None)
    if setting is None:
        setting = GymSetting.objects.filter(gym=gym).first()
    return setting


def resolve_story_owner_context(
    request,
    require_active_gym: bool = True,
) -> Tuple[str, Optional[Gym]]:
    """
    Automatically determines whether a story request is operating in Public User context
    or Gym context strictly from the authenticated Bearer token claims
    (`request.token_context` and `request.gym_id`).

    - Personal token (`context_type == 'personal'`): returns ('user', None)
    - Gym token (`context_type == 'gym'`, `gym_id` present): returns ('gym', gym)
    """
    token_context = getattr(request, "token_context", TokenContextType.PERSONAL)
    token_gym_id = getattr(request, "gym_id", None)

    if token_context != TokenContextType.GYM or not token_gym_id:
        return StoryOwnerTypeEnum.USER, None

    try:
        gym_uuid = uuid.UUID(str(token_gym_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid gym_id in token context.")

    gym = Gym.objects.select_related("settings").filter(id=gym_uuid).first()
    if not gym:
        raise ResourceNotFoundError("Gym not found.")

    setting = _get_gym_setting(gym)
    if setting and setting.is_deleted:
        raise ResourceNotFoundError("Gym not found.")
    if require_active_gym and setting and setting.is_deactivated:
        raise DomainValidationError("This gym is deactivated.")

    return StoryOwnerTypeEnum.GYM, gym


def has_gym_story_manage_permission(user, gym: Gym) -> bool:
    """
    Returns True if user is superuser, gym owner, or active staff with 'stories:manage' or 'posts:manage'.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or gym.owner_user_id == user.id:
        return True

    assignment = (
        GymStaffAssignment.objects.select_related("role")
        .filter(gym=gym, user=user, status=StaffStatus.ACTIVE)
        .first()
    )
    if not assignment or not assignment.role:
        return False

    return assignment.role.permissions.filter(
        scope_code__in=["stories:manage", "posts:manage"]
    ).exists()


def check_story_creation_permission(user, owner_type: str, gym: Optional[Gym] = None) -> None:
    """
    Enforces authorization for creating a story as either a public user or a gym.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionDeniedError("Authentication credentials were not provided.")

    setting = user.get_settings()
    if setting.is_deleted or setting.is_deactivated:
        raise PermissionDeniedError("Your account is deactivated or deleted.")

    if owner_type == StoryOwnerTypeEnum.USER:
        return

    if owner_type == StoryOwnerTypeEnum.GYM:
        if not gym:
            raise DomainValidationError("Gym context is required for gym stories.")
        if not has_gym_story_manage_permission(user, gym):
            raise PermissionDeniedError(
                "You do not have permission to manage stories for this gym. Required scope: 'stories:manage' or 'posts:manage'."
            )
        return

    raise DomainValidationError(f"Unsupported story owner_type '{owner_type}'.")


def check_story_manage_permission(user, story: Story) -> None:
    """
    Enforces ownership/management permission on an existing story (update, delete, view viewers).
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionDeniedError("Authentication credentials were not provided.")

    if user.is_superuser:
        return

    if story.owner_type == StoryOwnerTypeEnum.USER:
        if story.user_id != user.id:
            raise PermissionDeniedError("You do not have permission to manage this user story.")
        return

    if story.owner_type == StoryOwnerTypeEnum.GYM:
        if not story.gym or not has_gym_story_manage_permission(user, story.gym):
            raise PermissionDeniedError("You do not have permission to manage this gym story.")
        return

    raise PermissionDeniedError("You do not have permission to manage this story.")

