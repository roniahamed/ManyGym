import uuid
from typing import Any, Dict, List, Optional, Set
from django.db.models import BooleanField, Exists, OuterRef, Q, QuerySet, Value
from django.utils import timezone

from apps.access_control.models import GymStaffAssignment
from apps.gyms.models import Gym, GymBlockedUser, GymFollow, GymSetting
from apps.members.models import Member
from apps.posts.selectors import (
    check_posts_age_restriction,
    get_excluded_age_policy_codes,
    get_user_age,
)
from apps.stories.models import Story, StoryView
from apps.stories.permissions import (
    check_story_manage_permission,
    has_gym_story_manage_permission,
)
from apps.users.models import User, UserBlockedUser, UserFollow
from common.enums import (
    FeedTypeEnum,
    StaffStatus,
    StoryOwnerTypeEnum,
    StoryPrivacyEnum,
    normalize_feed_type,
)
from common.exceptions import (
    DomainValidationError,
    PermissionDeniedError,
    ResourceNotFoundError,
)


def _get_story_social_context(user: Optional[User]) -> Dict[str, Set[uuid.UUID]]:
    """
    Computes social & membership sets for story visibility in minimal queries:
    - staff_or_owned_gym_ids: Gyms where user is owner or active staff.
    - member_gym_ids: Gyms where user is a member.
    - followed_gym_ids: Gyms followed by user.
    - followed_user_ids: Public users followed by user.
    - blocked_gym_ids: Gyms that blocked user.
    - blocked_user_ids: Users with mutual block relation.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return {
            "staff_or_owned_gym_ids": set(),
            "member_gym_ids": set(),
            "followed_gym_ids": set(),
            "followed_user_ids": set(),
            "blocked_gym_ids": set(),
            "blocked_user_ids": set(),
        }

    staff_or_owned_gym_ids = set(
        Gym.objects.filter(
            Q(owner_user=user)
            | Q(staff_assignments__user=user, staff_assignments__status=StaffStatus.ACTIVE)
        ).values_list("id", flat=True)
    )
    member_gym_ids = set(
        Member.objects.filter(Q(user=user) | Q(email=user.email)).values_list("gym_id", flat=True)
    )
    followed_gym_ids = set(
        GymFollow.objects.filter(user=user).values_list("gym_id", flat=True)
    )
    followed_user_ids = set(
        UserFollow.objects.filter(follower=user).values_list("followed_user_id", flat=True)
    )
    blocked_gym_ids = set(
        GymBlockedUser.objects.filter(user=user).values_list("gym_id", flat=True)
    )

    blocked_records = UserBlockedUser.objects.filter(
        Q(blocker=user) | Q(blocked_user=user)
    ).values_list("blocker_id", "blocked_user_id")
    blocked_user_ids: Set[uuid.UUID] = set()
    for blocker_id, target_id in blocked_records:
        blocked_user_ids.add(target_id if blocker_id == user.id else blocker_id)

    return {
        "staff_or_owned_gym_ids": staff_or_owned_gym_ids,
        "member_gym_ids": member_gym_ids,
        "followed_gym_ids": followed_gym_ids,
        "followed_user_ids": followed_user_ids,
        "blocked_gym_ids": blocked_gym_ids,
        "blocked_user_ids": blocked_user_ids,
    }


def _build_base_stories_queryset(requesting_user: Optional[User] = None) -> QuerySet[Story]:
    """Returns an optimized Story queryset with related entities and has_viewed annotation."""
    qs = Story.objects.select_related(
        "user",
        "user__profile",
        "user__settings",
        "gym",
        "gym__settings",
        "source_post",
        "source_post__gym",
    )
    if requesting_user and getattr(requesting_user, "is_authenticated", False):
        qs = qs.annotate(
            has_viewed=Exists(
                StoryView.objects.filter(story=OuterRef("pk"), viewer_user=requesting_user)
            )
        )
    else:
        qs = qs.annotate(has_viewed=Value(False, output_field=BooleanField()))
    return qs


def _apply_optional_story_filters(
    qs: QuerySet[Story],
    owner_type: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    gym_id: Optional[uuid.UUID] = None,
    privacy: Optional[str] = None,
) -> QuerySet[Story]:
    if owner_type:
        cleaned_owner = owner_type.strip().lower()
        if cleaned_owner not in StoryOwnerTypeEnum.values:
            raise DomainValidationError(
                f"Invalid owner_type filter '{owner_type}'. Choices: {StoryOwnerTypeEnum.values}."
            )
        qs = qs.filter(owner_type=cleaned_owner)

    if gym_id:
        qs = qs.filter(owner_type=StoryOwnerTypeEnum.GYM, gym_id=gym_id)

    if user_id:
        if owner_type == StoryOwnerTypeEnum.GYM:
            qs = qs.filter(user_id=user_id)
        else:
            qs = qs.filter(owner_type=StoryOwnerTypeEnum.USER, user_id=user_id)

    if privacy:
        cleaned_priv = privacy.strip().lower().replace(" ", "_")
        if cleaned_priv == "gym_members_only":
            cleaned_priv = StoryPrivacyEnum.MEMBERS_ONLY
        if cleaned_priv not in StoryPrivacyEnum.values:
            raise DomainValidationError(
                f"Invalid privacy filter '{privacy}'. Choices: {StoryPrivacyEnum.values}."
            )
        qs = qs.filter(privacy=cleaned_priv)

    return qs


def list_active_stories(
    requesting_user: Optional[User] = None,
    owner_type: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    gym_id: Optional[uuid.UUID] = None,
    feed_type: Optional[str] = None,
    privacy: Optional[str] = None,
) -> QuerySet[Story]:
    """
    Returns non-expired, non-archived stories visible to the requesting user,
    strictly enforcing privacy (User: public/followers/private; Gym: public/followers/members_only/private),
    blocklists, lifecycle flags, and gym age restrictions.
    """
    now = timezone.now()
    qs = (
        _build_base_stories_queryset(requesting_user)
        .filter(expires_at__gt=now, is_archived=False)
        .exclude(user__settings__is_deleted=True)
        .exclude(user__settings__is_deactivated=True)
        .exclude(gym__settings__is_deleted=True)
    )

    canonical_feed_type = normalize_feed_type(feed_type)

    user_not_private_q = Q(user__profile__isnull=True) | Q(user__profile__is_private=False)
    gym_published_q = Q(gym__settings__isnull=True) | Q(gym__settings__is_published=True)
    gym_active_filter = Q(gym__settings__isnull=True) | (
        Q(gym__settings__is_published=True) & Q(gym__settings__is_deactivated=False)
    )

    if not requesting_user or not getattr(requesting_user, "is_authenticated", False):
        if canonical_feed_type in (FeedTypeEnum.FOLLOWED, FeedTypeEnum.CONNECTED):
            return Story.objects.none()

        excluded_policies = get_excluded_age_policy_codes(None)
        user_public_q = (
            Q(owner_type=StoryOwnerTypeEnum.USER)
            & Q(privacy=StoryPrivacyEnum.PUBLIC)
            & user_not_private_q
        )
        gym_public_q = (
            Q(owner_type=StoryOwnerTypeEnum.GYM)
            & Q(privacy=StoryPrivacyEnum.PUBLIC)
            & gym_active_filter
            & (Q(gym__settings__isnull=True) | ~Q(gym__settings__posts_age_restriction__in=excluded_policies))
        )
        qs = qs.filter(user_public_q | gym_public_q)
        qs = _apply_optional_story_filters(
            qs,
            owner_type=owner_type,
            user_id=user_id,
            gym_id=gym_id,
            privacy=privacy,
        )
        return qs.order_by("-published_at")

    social_ctx = _get_story_social_context(requesting_user)
    staff_or_owned_gym_ids = social_ctx["staff_or_owned_gym_ids"]
    member_gym_ids = social_ctx["member_gym_ids"]
    connected_gym_ids = staff_or_owned_gym_ids | member_gym_ids
    followed_gym_ids = social_ctx["followed_gym_ids"]
    followed_user_ids = social_ctx["followed_user_ids"]
    blocked_gym_ids = social_ctx["blocked_gym_ids"]
    blocked_user_ids = social_ctx["blocked_user_ids"]

    if blocked_user_ids:
        qs = qs.exclude(owner_type=StoryOwnerTypeEnum.USER, user_id__in=blocked_user_ids)
    if blocked_gym_ids:
        qs = qs.exclude(
            Q(owner_type=StoryOwnerTypeEnum.GYM)
            & Q(gym_id__in=blocked_gym_ids)
            & ~Q(gym_id__in=staff_or_owned_gym_ids)
        )

    # Enforce gym age restrictions (owners, superusers, active staff are exempt)
    if not requesting_user.is_superuser:
        user_age = get_user_age(requesting_user)
        restricted_policies = get_excluded_age_policy_codes(user_age)
        if restricted_policies:
            qs = qs.exclude(
                Q(owner_type=StoryOwnerTypeEnum.GYM)
                & Q(gym__settings__posts_age_restriction__in=restricted_policies)
                & ~Q(gym_id__in=staff_or_owned_gym_ids)
            )

    # User story visibility
    user_own_q = Q(owner_type=StoryOwnerTypeEnum.USER, user=requesting_user)
    user_public_q = (
        Q(owner_type=StoryOwnerTypeEnum.USER, privacy=StoryPrivacyEnum.PUBLIC)
        & (user_not_private_q | Q(user_id__in=followed_user_ids) | Q(user=requesting_user))
    )
    user_followers_q = Q(
        owner_type=StoryOwnerTypeEnum.USER,
        privacy=StoryPrivacyEnum.FOLLOWERS,
        user_id__in=followed_user_ids,
    )

    # Gym story visibility
    gym_staff_q = Q(owner_type=StoryOwnerTypeEnum.GYM, gym_id__in=staff_or_owned_gym_ids)
    gym_public_q = (
        Q(owner_type=StoryOwnerTypeEnum.GYM, privacy=StoryPrivacyEnum.PUBLIC)
        & (gym_active_filter | Q(gym_id__in=connected_gym_ids))
    )
    gym_followers_q = (
        Q(owner_type=StoryOwnerTypeEnum.GYM, privacy=StoryPrivacyEnum.FOLLOWERS, gym_id__in=followed_gym_ids)
        & (gym_active_filter | Q(gym_id__in=connected_gym_ids))
    )
    gym_members_q = (
        Q(owner_type=StoryOwnerTypeEnum.GYM, privacy=StoryPrivacyEnum.MEMBERS_ONLY, gym_id__in=member_gym_ids)
        & gym_published_q
    )

    all_visible_q = (
        user_own_q
        | user_public_q
        | user_followers_q
        | gym_staff_q
        | gym_public_q
        | gym_followers_q
        | gym_members_q
    )

    if canonical_feed_type == FeedTypeEnum.FOLLOWED:
        followed_q = (
            Q(owner_type=StoryOwnerTypeEnum.USER, user_id__in=followed_user_ids)
            | Q(owner_type=StoryOwnerTypeEnum.GYM, gym_id__in=followed_gym_ids)
        )
        qs = qs.filter(all_visible_q & followed_q)
    elif canonical_feed_type == FeedTypeEnum.CONNECTED:
        qs = qs.filter(all_visible_q & Q(owner_type=StoryOwnerTypeEnum.GYM, gym_id__in=connected_gym_ids))
    elif canonical_feed_type == FeedTypeEnum.PUBLIC:
        qs = qs.filter(all_visible_q & Q(privacy=StoryPrivacyEnum.PUBLIC))
    else:
        qs = qs.filter(all_visible_q)

    qs = _apply_optional_story_filters(
        qs,
        owner_type=owner_type,
        user_id=user_id,
        gym_id=gym_id,
        privacy=privacy,
    )
    return qs.distinct().order_by("-published_at")


def list_my_stories(
    user: User,
    owner_type: str = StoryOwnerTypeEnum.USER,
    gym: Optional[Gym] = None,
    include_expired: bool = False,
    include_archived: bool = True,
) -> QuerySet[Story]:
    """
    Returns stories owned by the requesting user (personal context) or gym (gym context).
    """
    qs = _build_base_stories_queryset(user)

    if owner_type == StoryOwnerTypeEnum.GYM:
        if not gym or not has_gym_story_manage_permission(user, gym):
            raise PermissionDeniedError("You do not have permission to view this gym's stories.")
        qs = qs.filter(owner_type=StoryOwnerTypeEnum.GYM, gym=gym)
    else:
        qs = qs.filter(owner_type=StoryOwnerTypeEnum.USER, user=user)

    if not include_expired:
        qs = qs.filter(expires_at__gt=timezone.now())

    if not include_archived:
        qs = qs.filter(is_archived=False)

    return qs.order_by("-published_at")


def list_story_tray(
    requesting_user: Optional[User] = None,
    owner_type: Optional[str] = None,
    feed_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Groups active visible stories by owner (Public User or Gym) for story ring/tray UIs.
    Buckets with unviewed stories appear first, ordered by most recent story timestamp.
    """
    stories = list(
        list_active_stories(
            requesting_user=requesting_user,
            owner_type=owner_type,
            feed_type=feed_type,
        )
    )

    buckets: Dict[tuple, Dict[str, Any]] = {}
    for story in stories:
        if story.owner_type == StoryOwnerTypeEnum.GYM and story.gym_id:
            key = (StoryOwnerTypeEnum.GYM, story.gym_id)
            owner_id = story.gym_id
            owner_name = story.gym.name
            owner_avatar = story.gym.profile_picture_url
        else:
            key = (StoryOwnerTypeEnum.USER, story.user_id)
            owner_id = story.user_id
            full_name = f"{story.user.first_name} {story.user.last_name}".strip()
            owner_name = full_name or story.user.email
            profile = getattr(story.user, "profile", None)
            owner_avatar = profile.avatar_url if profile else None

        if key not in buckets:
            buckets[key] = {
                "owner_type": story.owner_type,
                "owner_id": owner_id,
                "owner_name": owner_name,
                "owner_avatar_url": owner_avatar,
                "latest_story_at": story.published_at,
                "has_unviewed": False,
                "stories_count": 0,
                "stories": [],
            }

        bucket = buckets[key]
        bucket["stories"].append(story)
        bucket["stories_count"] += 1
        if not getattr(story, "has_viewed", False):
            bucket["has_unviewed"] = True
        if story.published_at > bucket["latest_story_at"]:
            bucket["latest_story_at"] = story.published_at

    # Chronological story playback within each owner's tray bucket
    result = list(buckets.values())
    for bucket in result:
        bucket["stories"].sort(key=lambda s: s.published_at)

    result.sort(key=lambda b: (b["has_unviewed"], b["latest_story_at"]), reverse=True)
    return result


def get_story_detail(
    story_id,
    requesting_user: Optional[User] = None,
    for_management: bool = False,
) -> Story:
    """
    Retrieves a single story dossier with full privacy, expiry, blocklist, and RBAC checks.
    """
    try:
        story_uuid = uuid.UUID(str(story_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid story ID.")

    story = _build_base_stories_queryset(requesting_user).filter(id=story_uuid).first()
    if not story:
        raise ResourceNotFoundError("Story not found.")

    if for_management:
        check_story_manage_permission(requesting_user, story)
        return story

    is_authenticated = bool(requesting_user and getattr(requesting_user, "is_authenticated", False))

    if story.owner_type == StoryOwnerTypeEnum.USER:
        is_owner = is_authenticated and (requesting_user.id == story.user_id or requesting_user.is_superuser)
        author_setting = story.user.get_settings()
        if author_setting.is_deleted:
            raise ResourceNotFoundError("Story not found.")
        if author_setting.is_deactivated and not is_owner:
            raise ResourceNotFoundError("Story not found.")

        if (story.is_expired or story.is_archived) and not is_owner:
            raise ResourceNotFoundError("Story not found or has expired.")

        if is_owner:
            return story

        if is_authenticated:
            is_blocked = UserBlockedUser.objects.filter(
                Q(blocker=story.user, blocked_user=requesting_user)
                | Q(blocker=requesting_user, blocked_user=story.user)
            ).exists()
            if is_blocked:
                raise PermissionDeniedError("You cannot view this user's story.")

        if story.privacy == StoryPrivacyEnum.PRIVATE:
            raise PermissionDeniedError("This story is private.")

        is_follower = (
            is_authenticated
            and UserFollow.objects.filter(follower=requesting_user, followed_user=story.user).exists()
        )
        if story.privacy == StoryPrivacyEnum.FOLLOWERS and not is_follower:
            raise PermissionDeniedError("This story is restricted to followers.")

        profile = getattr(story.user, "profile", None)
        if profile and profile.is_private and not is_follower:
            raise PermissionDeniedError("This user's account is private.")

        return story

    # Gym story
    gym = story.gym
    if not gym:
        raise ResourceNotFoundError("Story not found.")

    gym_setting = getattr(gym, "settings", None) or GymSetting.objects.filter(gym=gym).first()
    if gym_setting and gym_setting.is_deleted:
        raise ResourceNotFoundError("Story not found.")

    is_staff_or_owner = is_authenticated and (
        requesting_user.is_superuser
        or gym.owner_user_id == requesting_user.id
        or GymStaffAssignment.objects.filter(
            gym=gym, user=requesting_user, status=StaffStatus.ACTIVE
        ).exists()
    )

    if gym_setting and not gym_setting.is_published and not is_staff_or_owner:
        raise ResourceNotFoundError("Story not found.")

    if (story.is_expired or story.is_archived) and not is_staff_or_owner:
        raise ResourceNotFoundError("Story not found or has expired.")

    if is_staff_or_owner:
        return story

    is_member = (
        is_authenticated
        and Member.objects.filter(gym=gym).filter(Q(user=requesting_user) | Q(email=requesting_user.email)).exists()
    )

    if gym_setting and gym_setting.is_deactivated and not is_member:
        raise DomainValidationError("This gym is deactivated.")

    if is_authenticated and GymBlockedUser.objects.filter(gym=gym, user=requesting_user).exists():
        raise PermissionDeniedError("You have been blocked by this gym.")

    if not check_posts_age_restriction(gym, requesting_user):
        raise PermissionDeniedError("This gym's content is age-restricted. You do not meet the minimum age requirement.")

    if story.privacy == StoryPrivacyEnum.PRIVATE:
        raise PermissionDeniedError("This story is private.")

    if story.privacy == StoryPrivacyEnum.MEMBERS_ONLY and not is_member:
        raise PermissionDeniedError("This story is restricted to gym members.")

    if story.privacy == StoryPrivacyEnum.FOLLOWERS:
        is_follower = is_authenticated and GymFollow.objects.filter(user=requesting_user, gym=gym).exists()
        if not is_follower:
            raise PermissionDeniedError("This story is restricted to gym followers.")

    return story


def list_story_viewers(story_id, requesting_user: User) -> QuerySet[StoryView]:
    """
    Returns ordered StoryView queryset for a story. Only accessible to the story owner / gym managers.
    """
    story = get_story_detail(story_id, requesting_user=requesting_user, for_management=True)
    return (
        StoryView.objects.filter(story=story)
        .select_related("viewer_user", "viewer_user__profile")
        .order_by("-viewed_at")
    )
