import uuid
from typing import Optional
from django.db import models
from apps.gyms.models import Gym, GymSetting, GymFollow, GymBlockedUser
from apps.access_control.models import GymStaffAssignment
from apps.users.models import User
from apps.members.models import Member
from common.enums import AudienceFollowingVisibilityEnum, AudienceMembersVisibilityEnum, StaffStatus
from common.exceptions import DomainValidationError, ResourceNotFoundError, PermissionDeniedError


def list_gym_followers(gym_id, requesting_user: Optional[User] = None) -> models.QuerySet[GymFollow]:
    """
    Returns a QuerySet of GymFollow records representing users following this gym.
    Respects gym settings (who_can_see_followers / who_can_see_following):
      - 'everyone': visible to all authenticated users.
      - 'only_members': visible only to gym members, active staff, or owner.
      - 'private': visible only to active gym staff or owner.
    Optimized with field projection (only()) and eager relationship fetching.
    """
    if isinstance(gym_id, Gym):
        gym = gym_id
    else:
        try:
            gym_uuid = uuid.UUID(str(gym_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid gym ID.")

        try:
            gym = (
                Gym.objects.select_related("settings")
                .only(
                    "id",
                    "owner_user_id",
                    "settings__id",
                    "settings__who_can_see_followers",
                    "settings__who_can_see_following",
                    "settings__is_deactivated",
                    "settings__is_deleted",
                )
                .get(id=gym_uuid)
            )
        except Gym.DoesNotExist:
            raise ResourceNotFoundError("Gym not found.")

    setting = getattr(gym, "settings", None)
    if not setting:
        setting = GymSetting.objects.filter(gym_id=gym.id).first()

    if getattr(setting, "is_deleted", False):
        raise ResourceNotFoundError("Gym not found.")

    if getattr(setting, "is_deactivated", False):
        is_owner_or_staff = False
        if requesting_user and requesting_user.is_authenticated:
            if gym.owner_user_id == requesting_user.id:
                is_owner_or_staff = True
            elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
                is_owner_or_staff = True
        if not is_owner_or_staff:
            raise DomainValidationError("This gym is deactivated.")

    if requesting_user and requesting_user.is_authenticated:
        if GymBlockedUser.objects.filter(gym=gym, user=requesting_user).exists():
            raise PermissionDeniedError("You have been blocked by this gym.")

    if setting:
        policy = getattr(setting, "who_can_see_followers", None) or AudienceFollowingVisibilityEnum.EVERYONE
        if policy == AudienceFollowingVisibilityEnum.EVERYONE and getattr(setting, "who_can_see_following", None) != AudienceFollowingVisibilityEnum.EVERYONE:
            policy = setting.who_can_see_following

        if policy == AudienceFollowingVisibilityEnum.ONLY_MEMBERS:
            is_authorized = False
            if requesting_user and requesting_user.is_authenticated:
                if gym.owner_user_id == requesting_user.id:
                    is_authorized = True
                elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
                    is_authorized = True
                elif Member.objects.filter(gym=gym, user=requesting_user).exclude(joining_status="removed").exists():
                    is_authorized = True

            if not is_authorized:
                raise PermissionDeniedError("Only gym members can view the follower list.")

        elif policy == AudienceFollowingVisibilityEnum.PRIVATE:
            is_authorized = False
            if requesting_user and requesting_user.is_authenticated:
                if gym.owner_user_id == requesting_user.id:
                    is_authorized = True
                elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
                    is_authorized = True

            if not is_authorized:
                raise PermissionDeniedError("The follower list for this gym is private.")

    return (
        GymFollow.objects.filter(gym=gym)
        .select_related("user__profile")
        .only(
            "id",
            "created_at",
            "gym_id",
            "user__id",
            "user__email",
            "user__first_name",
            "user__last_name",
            "user__profile__id",
            "user__profile__avatar_url",
            "user__profile__is_private",
        )
        .order_by("-created_at")
    )


def list_user_followed_gyms(user: User) -> models.QuerySet[GymFollow]:
    """
    Returns a QuerySet of GymFollow records representing gyms followed by the specified user.
    Optimized with field projections (only()) and eager gym loading.
    """
    return (
        GymFollow.objects.filter(user=user)
        .select_related("gym")
        .only(
            "id",
            "created_at",
            "user_id",
            "gym__id",
            "gym__name",
            "gym__primary_type",
            "gym__profile_picture_url",
        )
        .order_by("-created_at")
    )


def is_following_gym(user, gym) -> bool:
    """Returns True if user is actively following gym."""
    u_id = getattr(user, "id", user)
    g_id = getattr(gym, "id", gym)
    if not u_id or not g_id:
        return False
    return GymFollow.objects.filter(user_id=u_id, gym_id=g_id).exists()


def list_gym_following(gym_id, requesting_user: Optional[User] = None) -> list:
    """
    Returns list of people and pages followed by this gym.
    Respects gym setting: who_can_see_following (everyone, only_members, private).
    Optimized with eager settings loading and instance passing.
    """
    if isinstance(gym_id, Gym):
        gym = gym_id
    else:
        try:
            gym_uuid = uuid.UUID(str(gym_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid gym ID.")

        try:
            gym = (
                Gym.objects.select_related("settings")
                .only(
                    "id",
                    "owner_user_id",
                    "settings__id",
                    "settings__who_can_see_following",
                    "settings__is_deactivated",
                    "settings__is_deleted",
                )
                .get(id=gym_uuid)
            )
        except Gym.DoesNotExist:
            raise ResourceNotFoundError("Gym not found.")

    setting = getattr(gym, "settings", None)
    if not setting:
        setting = GymSetting.objects.filter(gym_id=gym.id).first()

    if getattr(setting, "is_deleted", False):
        raise ResourceNotFoundError("Gym not found.")

    if getattr(setting, "is_deactivated", False):
        is_owner_or_staff = False
        if requesting_user and requesting_user.is_authenticated:
            if gym.owner_user_id == requesting_user.id:
                is_owner_or_staff = True
            elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
                is_owner_or_staff = True
        if not is_owner_or_staff:
            raise DomainValidationError("This gym is deactivated.")

    if requesting_user and requesting_user.is_authenticated:
        if GymBlockedUser.objects.filter(gym=gym, user=requesting_user).exists():
            raise PermissionDeniedError("You have been blocked by this gym.")

    if setting:
        policy = setting.who_can_see_following
        if policy == AudienceFollowingVisibilityEnum.ONLY_MEMBERS:
            is_authorized = False
            if requesting_user and requesting_user.is_authenticated:
                if gym.owner_user_id == requesting_user.id:
                    is_authorized = True
                elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
                    is_authorized = True
                elif Member.objects.filter(gym=gym, user=requesting_user).exclude(joining_status="removed").exists():
                    is_authorized = True

            if not is_authorized:
                raise PermissionDeniedError("Only gym members can view the people and pages this gym follows.")

        elif policy == AudienceFollowingVisibilityEnum.PRIVATE:
            is_authorized = False
            if requesting_user and requesting_user.is_authenticated:
                if gym.owner_user_id == requesting_user.id:
                    is_authorized = True
                elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
                    is_authorized = True

            if not is_authorized:
                raise PermissionDeniedError("The following list for this gym is private.")

    return []


def list_gym_members_for_audience(
    gym_id,
    requesting_user: Optional[User] = None,
    search: Optional[str] = None,
) -> models.QuerySet[Member]:
    """
    Returns a QuerySet of Member records representing gym members.
    Enforces:
    - Gym existence and soft-delete / deactivation checks.
    - GymBlockedUser check (blocked users cannot view).
    - GymSetting.who_can_see_members:
        - 'everyone': visible to all authenticated users.
        - 'only_members': visible only to gym members, active staff, or owner.
    """
    if isinstance(gym_id, Gym):
        gym = gym_id
    else:
        try:
            gym_uuid = uuid.UUID(str(gym_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid gym ID.")

        try:
            gym = (
                Gym.objects.select_related("settings")
                .only(
                    "id",
                    "owner_user_id",
                    "settings__id",
                    "settings__who_can_see_members",
                    "settings__is_deactivated",
                    "settings__is_deleted",
                )
                .get(id=gym_uuid)
            )
        except Gym.DoesNotExist:
            raise ResourceNotFoundError("Gym not found.")

    setting = getattr(gym, "settings", None)
    if not setting:
        setting = GymSetting.objects.filter(gym_id=gym.id).first()

    if getattr(setting, "is_deleted", False):
        raise ResourceNotFoundError("Gym not found.")

    if getattr(setting, "is_deactivated", False):
        is_owner_or_staff = False
        if requesting_user and requesting_user.is_authenticated:
            if gym.owner_user_id == requesting_user.id:
                is_owner_or_staff = True
            elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
                is_owner_or_staff = True
        if not is_owner_or_staff:
            raise DomainValidationError("This gym is deactivated.")

    if requesting_user and requesting_user.is_authenticated:
        if GymBlockedUser.objects.filter(gym=gym, user=requesting_user).exists():
            raise PermissionDeniedError("You have been blocked by this gym.")

    if setting:
        policy = getattr(setting, "who_can_see_members", AudienceMembersVisibilityEnum.EVERYONE)
        if policy == AudienceMembersVisibilityEnum.ONLY_MEMBERS:
            is_authorized = False
            if requesting_user and requesting_user.is_authenticated:
                if gym.owner_user_id == requesting_user.id:
                    is_authorized = True
                elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
                    is_authorized = True
                elif Member.objects.filter(gym=gym, user=requesting_user).exclude(joining_status="removed").exists():
                    is_authorized = True

            if not is_authorized:
                raise PermissionDeniedError("Only gym members can view the member roster.")

    qs = (
        Member.objects.filter(gym=gym)
        .exclude(joining_status="removed")
        .select_related("user", "user__profile")
        .only(
            "id",
            "gym_id",
            "user_id",
            "first_name",
            "last_name",
            "email",
            "profile_photo_url",
            "joining_status",
            "created_at",
            "user__id",
            "user__profile__avatar_url",
        )
        .order_by("-created_at")
    )

    if search and search.strip():
        s = search.strip()
        qs = qs.filter(
            models.Q(first_name__icontains=s)
            | models.Q(last_name__icontains=s)
            | models.Q(email__icontains=s)
        )

    return qs
