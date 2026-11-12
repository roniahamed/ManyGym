import uuid
from typing import Optional, Generator, Dict, Set, List
from django.db.models import QuerySet, Q, Count
from django.utils import timezone

from apps.gyms.models import Gym, GymSetting, GymBlockedUser, GymFollow
from apps.access_control.models import GymStaffAssignment
from apps.members.models import Member
from apps.users.models import User, UserFollow, UserBlockedUser
from apps.posts.models import GymPost, GymPostMedia
from common.enums import (
    PostOwnerTypeEnum,
    PostPrivacyEnum,
    PostsAgeRestrictionEnum,
    StaffStatus,
    FeedTypeEnum,
    normalize_feed_type,
)
from common.exceptions import ResourceNotFoundError, PermissionDeniedError, DomainValidationError


def get_user_social_context(user: Optional[User]) -> Dict[str, object]:
    """
    Computes social relationships for an authenticated user to drive feed personalization
    and O(1) source-post visibility checks:
    - connected_gym_ids: Gyms where user is owner, active staff, or member.
    - staff_or_owned_gym_ids: Gyms where user is owner or active staff.
    - followed_gym_ids: Gyms followed by user.
    - followed_user_ids: Users followed by user.
    - blocked_gym_ids: Gyms that have blocked the user.
    - blocked_user_ids: Users who blocked the user or whom the user has blocked.
    - excluded_age_policies: Gym age restriction policies the user does not satisfy.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return {
            "connected_gym_ids": set(),
            "staff_or_owned_gym_ids": set(),
            "followed_gym_ids": set(),
            "followed_user_ids": set(),
            "blocked_gym_ids": set(),
            "blocked_user_ids": set(),
            "excluded_age_policies": set(get_excluded_age_policy_codes(None)),
        }

    # 1. Gyms owned or actively staffed by user
    staff_or_owned_gym_ids = set(
        Gym.objects.filter(
            Q(owner_user=user)
            | Q(staff_assignments__user=user, staff_assignments__status=StaffStatus.ACTIVE)
        ).values_list("id", flat=True)
    )

    # 2. Gyms where user is a member
    member_gym_ids = set(
        Member.objects.filter(Q(user=user) | Q(email=user.email)).values_list("gym_id", flat=True)
    )
    connected_gym_ids = staff_or_owned_gym_ids | member_gym_ids

    # 3. Followed gyms
    followed_gym_ids = set(
        GymFollow.objects.filter(user=user).values_list("gym_id", flat=True)
    )

    # 4. Followed users
    followed_user_ids = set(
        UserFollow.objects.filter(follower=user).values_list("followed_user_id", flat=True)
    )

    # 5. Blocked gyms
    blocked_gym_ids = set(
        GymBlockedUser.objects.filter(user=user).values_list("gym_id", flat=True)
    )

    # 6. Mutually blocked users (in 1 optimized query)
    blocked_records = UserBlockedUser.objects.filter(
        Q(blocker=user) | Q(blocked_user=user)
    ).values_list("blocker_id", "blocked_user_id")
    blocked_user_ids: Set[uuid.UUID] = set()
    for blocker_id, target_id in blocked_records:
        if blocker_id == user.id:
            blocked_user_ids.add(target_id)
        else:
            blocked_user_ids.add(blocker_id)

    user_age = get_user_age(user)
    excluded_age_policies = set(get_excluded_age_policy_codes(user_age))

    return {
        "connected_gym_ids": connected_gym_ids,
        "staff_or_owned_gym_ids": staff_or_owned_gym_ids,
        "followed_gym_ids": followed_gym_ids,
        "followed_user_ids": followed_user_ids,
        "blocked_gym_ids": blocked_gym_ids,
        "blocked_user_ids": blocked_user_ids,
        "excluded_age_policies": excluded_age_policies,
    }


def get_user_age(user: Optional[User]) -> Optional[int]:
    """Computes age in completed years from profile date_of_birth, or None if unavailable."""
    if not user or not getattr(user, "is_authenticated", False):
        return None
    profile = getattr(user, "profile", None)
    if not profile or not profile.date_of_birth:
        return None
    dob = profile.date_of_birth
    today = timezone.now().date()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def get_excluded_age_policy_codes(user_age: Optional[int]) -> List[str]:
    """Returns list of PostsAgeRestrictionEnum policies that a user fails to satisfy."""
    if user_age is None:
        return [
            PostsAgeRestrictionEnum.AGE_17_PLUS,
            PostsAgeRestrictionEnum.AGE_18_PLUS,
            PostsAgeRestrictionEnum.AGE_19_PLUS,
            PostsAgeRestrictionEnum.AGE_20_PLUS,
        ]
    excluded = []
    if user_age < 17:
        excluded.append(PostsAgeRestrictionEnum.AGE_17_PLUS)
    if user_age < 18:
        excluded.append(PostsAgeRestrictionEnum.AGE_18_PLUS)
    if user_age < 19:
        excluded.append(PostsAgeRestrictionEnum.AGE_19_PLUS)
    if user_age < 20:
        excluded.append(PostsAgeRestrictionEnum.AGE_20_PLUS)
    return excluded


def check_posts_age_restriction(gym: Gym, requesting_user=None) -> bool:
    """
    Evaluates whether the requesting user satisfies the gym's posts age restriction policy:
    - 'any_age': Any user (including guests) can view.
    - '17_plus', '18_plus', '19_plus', '20_plus': Requires user to be authenticated,
      have date_of_birth in profile, and be >= threshold age.
    - Gym owner, superuser, and active gym staff are exempt.
    """
    setting = getattr(gym, "settings", None)
    if not setting:
        setting = GymSetting.objects.filter(gym=gym).first()

    policy = getattr(setting, "posts_age_restriction", PostsAgeRestrictionEnum.ANY_AGE) if setting else PostsAgeRestrictionEnum.ANY_AGE
    if not policy or policy == PostsAgeRestrictionEnum.ANY_AGE:
        return True

    if not requesting_user or not requesting_user.is_authenticated:
        return False

    if requesting_user.is_superuser or gym.owner_user_id == requesting_user.id:
        return True

    if GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
        return True

    user_age = get_user_age(requesting_user)
    if user_age is None:
        return False

    excluded = get_excluded_age_policy_codes(user_age)
    return policy not in excluded


def can_view_post_with_context(
    post: GymPost,
    requesting_user: Optional[User],
    social_ctx: Dict[str, object],
) -> bool:
    """
    Zero-query visibility check for a prefetched GymPost (e.g. nested source_post in a repost).
    Prevents IDOR leaks when someone reposts a restricted/private post.
    """
    is_authenticated = bool(requesting_user and getattr(requesting_user, "is_authenticated", False))
    is_superuser = bool(is_authenticated and requesting_user.is_superuser)
    followed_user_ids = social_ctx.get("followed_user_ids", set())
    followed_gym_ids = social_ctx.get("followed_gym_ids", set())
    connected_gym_ids = social_ctx.get("connected_gym_ids", set())
    staff_or_owned_gym_ids = social_ctx.get("staff_or_owned_gym_ids", set())
    blocked_gym_ids = social_ctx.get("blocked_gym_ids", set())
    blocked_user_ids = social_ctx.get("blocked_user_ids", set())
    excluded_age_policies = social_ctx.get("excluded_age_policies", set())

    if post.owner_type == PostOwnerTypeEnum.USER or post.gym_id is None:
        author = post.author_user
        if not author:
            return False
        author_setting = getattr(author, "settings", None)
        if author_setting and author_setting.is_deleted:
            return False
        is_owner = is_superuser or (is_authenticated and requesting_user.id == post.author_user_id)
        if author_setting and author_setting.is_deactivated and not is_owner:
            return False
        if is_owner:
            return True

        if post.author_user_id in blocked_user_ids:
            return False
        if post.privacy == PostPrivacyEnum.PRIVATE:
            return False

        is_follower = post.author_user_id in followed_user_ids
        if post.privacy == PostPrivacyEnum.FOLLOWERS and not is_follower:
            return False

        profile = getattr(author, "profile", None)
        if profile and profile.is_private and not is_follower:
            return False
        return True

    # Gym post
    gym = post.gym
    if not gym:
        return False
    setting = getattr(gym, "settings", None)
    if setting and setting.is_deleted:
        return False

    is_staff_or_owner = is_superuser or (is_authenticated and post.gym_id in staff_or_owned_gym_ids)
    if setting and not setting.is_published and not is_staff_or_owner:
        return False
    if is_staff_or_owner:
        return True

    is_connected = post.gym_id in connected_gym_ids
    if setting and setting.is_deactivated and not is_connected:
        return False
    if post.gym_id in blocked_gym_ids:
        return False
    if post.author_user_id in blocked_user_ids:
        return False
    if setting and setting.posts_age_restriction in excluded_age_policies:
        return False

    if post.privacy == PostPrivacyEnum.PRIVATE:
        return False
    if post.privacy == PostPrivacyEnum.FOLLOWERS and post.gym_id not in followed_gym_ids:
        return False
    if post.privacy in (PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY) and not is_connected:
        return False

    return True


def _build_base_posts_queryset() -> QuerySet[GymPost]:
    """Returns an optimized base queryset with required foreign keys, source_post, and media prefetched."""
    return (
        GymPost.objects.all()
        .select_related(
            "gym",
            "gym__settings",
            "author_user",
            "author_user__profile",
            "author_user__settings",
            "source_post",
            "source_post__gym",
            "source_post__gym__settings",
            "source_post__author_user",
            "source_post__author_user__profile",
            "source_post__author_user__settings",
        )
        .prefetch_related("media_attachments", "source_post__media_attachments")
        .annotate(media_count=Count("media_attachments", distinct=True))
    )


def _apply_feed_search(qs: QuerySet[GymPost], search: Optional[str]) -> QuerySet[GymPost]:
    """Applies case-insensitive keyword search matching post text, author name, or gym name."""
    if not search:
        return qs
    clean = search.strip()
    if not clean:
        return qs
    return qs.filter(
        Q(content_text__icontains=clean)
        | Q(author_user__first_name__icontains=clean)
        | Q(author_user__last_name__icontains=clean)
        | Q(gym__name__icontains=clean)
    )


def _apply_privacy_filter(qs: QuerySet[GymPost], privacy_filter: Optional[str]) -> QuerySet[GymPost]:
    """Applies post privacy filter ('public', 'followers', 'members_only', 'private')."""
    if not privacy_filter:
        return qs
    val = privacy_filter.strip().lower().replace(" ", "_")
    if val in (PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY):
        return qs.filter(privacy__in=[PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY])
    if val in (PostPrivacyEnum.PUBLIC, PostPrivacyEnum.FOLLOWERS, PostPrivacyEnum.PRIVATE):
        return qs.filter(privacy=val)
    return qs


def _apply_optional_feed_filters(
    qs: QuerySet[GymPost],
    owner_type: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    is_repost: Optional[bool] = None,
) -> QuerySet[GymPost]:
    if owner_type:
        cleaned_owner = owner_type.strip().lower()
        if cleaned_owner not in PostOwnerTypeEnum.values:
            raise DomainValidationError(
                f"Invalid owner_type filter '{owner_type}'. Choices: {PostOwnerTypeEnum.values}."
            )
        qs = qs.filter(owner_type=cleaned_owner)

    if user_id:
        if owner_type == PostOwnerTypeEnum.GYM:
            qs = qs.filter(author_user_id=user_id)
        else:
            qs = qs.filter(owner_type=PostOwnerTypeEnum.USER, author_user_id=user_id)

    if is_repost is not None:
        qs = qs.filter(is_repost=bool(is_repost))

    return qs


def _list_personalized_feed(
    requesting_user: User,
    feed_type: Optional[str] = None,
    privacy_filter: Optional[str] = None,
    search: Optional[str] = None,
    owner_type: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    is_repost: Optional[bool] = None,
    social_ctx: Optional[Dict[str, object]] = None,
) -> QuerySet[GymPost]:
    """
    Constructs personalized community & profile feed for an authenticated user:
    - Personal user posts & reposts (public, followers, own private)
    - Gym posts & reposts (public, followers, members_only, managed private)
    """
    if social_ctx is None:
        social_ctx = get_user_social_context(requesting_user)
    connected_gym_ids = social_ctx["connected_gym_ids"]
    staff_or_owned_gym_ids = social_ctx["staff_or_owned_gym_ids"]
    followed_gym_ids = social_ctx["followed_gym_ids"]
    followed_user_ids = social_ctx["followed_user_ids"]
    blocked_gym_ids = social_ctx["blocked_gym_ids"]
    blocked_user_ids = social_ctx["blocked_user_ids"]
    restricted_policies = list(social_ctx["excluded_age_policies"])

    qs = (
        _build_base_posts_queryset()
        .exclude(author_user__settings__is_deleted=True)
        .exclude(Q(owner_type=PostOwnerTypeEnum.USER) & Q(author_user__settings__is_deactivated=True) & ~Q(author_user=requesting_user))
        .exclude(Q(owner_type=PostOwnerTypeEnum.GYM) & Q(gym__settings__is_deleted=True))
    )

    # Exclude blocked entities
    if blocked_gym_ids:
        qs = qs.exclude(Q(owner_type=PostOwnerTypeEnum.GYM) & Q(gym_id__in=blocked_gym_ids) & ~Q(gym_id__in=staff_or_owned_gym_ids))
    if blocked_user_ids:
        qs = qs.exclude(author_user_id__in=blocked_user_ids)

    # Enforce age restriction across gyms
    if not requesting_user.is_superuser and restricted_policies:
        qs = qs.exclude(
            Q(owner_type=PostOwnerTypeEnum.GYM)
            & Q(gym__settings__posts_age_restriction__in=restricted_policies)
            & ~Q(gym_id__in=staff_or_owned_gym_ids)
        )

    user_not_private_q = Q(author_user__profile__isnull=True) | Q(author_user__profile__is_private=False)
    gym_active_filter = Q(gym__settings__isnull=True) | (
        Q(gym__settings__is_published=True) & Q(gym__settings__is_deactivated=False)
    )
    gym_published_q = Q(gym__settings__isnull=True) | Q(gym__settings__is_published=True)

    # Personal User post/repost visibility
    user_own_q = Q(owner_type=PostOwnerTypeEnum.USER, author_user=requesting_user)
    user_public_q = (
        Q(owner_type=PostOwnerTypeEnum.USER, privacy=PostPrivacyEnum.PUBLIC)
        & (user_not_private_q | Q(author_user_id__in=followed_user_ids) | Q(author_user=requesting_user))
    )
    user_followers_q = Q(
        owner_type=PostOwnerTypeEnum.USER,
        privacy=PostPrivacyEnum.FOLLOWERS,
        author_user_id__in=followed_user_ids,
    )

    # Gym post/repost visibility
    gym_staff_q = Q(owner_type=PostOwnerTypeEnum.GYM, gym_id__in=staff_or_owned_gym_ids)
    gym_public_q = (
        Q(owner_type=PostOwnerTypeEnum.GYM, privacy=PostPrivacyEnum.PUBLIC)
        & (gym_active_filter | Q(gym_id__in=connected_gym_ids))
    )
    gym_followers_q = (
        Q(owner_type=PostOwnerTypeEnum.GYM, privacy=PostPrivacyEnum.FOLLOWERS, gym_id__in=followed_gym_ids)
        & (gym_active_filter | Q(gym_id__in=connected_gym_ids))
    )
    gym_members_q = (
        Q(
            owner_type=PostOwnerTypeEnum.GYM,
            privacy__in=[PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY],
            gym_id__in=connected_gym_ids,
        )
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

    canonical_feed_type = normalize_feed_type(feed_type)

    if canonical_feed_type == FeedTypeEnum.FOLLOWED:
        followed_q = (
            Q(gym_id__in=followed_gym_ids)
            | Q(author_user_id__in=followed_user_ids)
        )
        qs = qs.filter(all_visible_q & followed_q)
    elif canonical_feed_type == FeedTypeEnum.CONNECTED:
        qs = qs.filter(all_visible_q & Q(owner_type=PostOwnerTypeEnum.GYM, gym_id__in=connected_gym_ids))
    elif canonical_feed_type == FeedTypeEnum.PUBLIC:
        qs = qs.filter(all_visible_q & Q(privacy=PostPrivacyEnum.PUBLIC))
    else:
        qs = qs.filter(all_visible_q)

    qs = _apply_optional_feed_filters(qs, owner_type=owner_type, user_id=user_id, is_repost=is_repost)
    qs = _apply_privacy_filter(qs, privacy_filter)
    qs = _apply_feed_search(qs, search)

    return qs.distinct().order_by("-published_at")


def _list_guest_feed(
    feed_type: Optional[str] = None,
    privacy_filter: Optional[str] = None,
    search: Optional[str] = None,
    owner_type: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    is_repost: Optional[bool] = None,
) -> QuerySet[GymPost]:
    """Constructs community feed for unauthenticated guests (public posts/reposts only)."""
    canonical_feed_type = normalize_feed_type(feed_type)
    if canonical_feed_type in (FeedTypeEnum.FOLLOWED, FeedTypeEnum.CONNECTED):
        return GymPost.objects.none()

    if privacy_filter:
        val = privacy_filter.strip().lower().replace(" ", "_")
        if val in (
            PostPrivacyEnum.MEMBERS_ONLY,
            PostPrivacyEnum.GYM_MEMBERS_ONLY,
            PostPrivacyEnum.FOLLOWERS,
            PostPrivacyEnum.PRIVATE,
        ):
            return GymPost.objects.none()

    excluded_policies = get_excluded_age_policy_codes(None)

    user_public_q = (
        Q(owner_type=PostOwnerTypeEnum.USER)
        & Q(privacy=PostPrivacyEnum.PUBLIC)
        & (Q(author_user__profile__isnull=True) | Q(author_user__profile__is_private=False))
    )
    gym_public_q = (
        Q(owner_type=PostOwnerTypeEnum.GYM)
        & Q(privacy=PostPrivacyEnum.PUBLIC)
        & Q(gym__settings__is_deleted=False)
        & Q(gym__settings__is_published=True)
        & Q(gym__settings__is_deactivated=False)
        & ~Q(gym__settings__posts_age_restriction__in=excluded_policies)
    )

    qs = (
        _build_base_posts_queryset()
        .exclude(author_user__settings__is_deleted=True)
        .exclude(author_user__settings__is_deactivated=True)
        .filter(user_public_q | gym_public_q)
    )

    qs = _apply_optional_feed_filters(qs, owner_type=owner_type, user_id=user_id, is_repost=is_repost)
    qs = _apply_feed_search(qs, search)
    return qs.distinct().order_by("-published_at")


def _list_single_gym_feed(
    gym: Gym,
    is_member_or_staff: bool = False,
    privacy_filter: Optional[str] = None,
    search: Optional[str] = None,
    requesting_user=None,
    is_repost: Optional[bool] = None,
) -> QuerySet[GymPost]:
    """Retrieves posts and reposts for a specific gym profile feed with lifecycle and visibility checks."""
    setting = getattr(gym, "settings", None)
    if not setting:
        try:
            setting = gym.settings
        except Exception:
            setting = GymSetting.objects.filter(gym=gym).first()

    if setting and setting.is_deleted:
        raise ResourceNotFoundError("Gym not found.")

    is_authenticated = bool(requesting_user and getattr(requesting_user, "is_authenticated", False))
    is_owner_or_staff = False
    if is_authenticated:
        if gym.owner_user_id == requesting_user.id or requesting_user.is_superuser:
            is_owner_or_staff = True
        elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
            is_owner_or_staff = True

    if setting and not setting.is_published and not is_owner_or_staff:
        raise ResourceNotFoundError("Gym not found.")

    if setting and setting.is_deactivated and not is_member_or_staff:
        return GymPost.objects.none()

    if is_authenticated and not is_owner_or_staff:
        if GymBlockedUser.objects.filter(gym=gym, user=requesting_user).exists():
            return GymPost.objects.none()

    if not check_posts_age_restriction(gym, requesting_user):
        return GymPost.objects.none()

    qs = _build_base_posts_queryset().filter(
        owner_type=PostOwnerTypeEnum.GYM,
        gym=gym,
    ).order_by("-published_at")

    if is_owner_or_staff:
        allowed_privacies = [
            PostPrivacyEnum.PUBLIC,
            PostPrivacyEnum.FOLLOWERS,
            PostPrivacyEnum.MEMBERS_ONLY,
            PostPrivacyEnum.GYM_MEMBERS_ONLY,
            PostPrivacyEnum.PRIVATE,
        ]
    else:
        allowed_privacies = [PostPrivacyEnum.PUBLIC]
        if is_member_or_staff:
            allowed_privacies.extend([PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY])
        if is_authenticated and GymFollow.objects.filter(user=requesting_user, gym=gym).exists():
            allowed_privacies.append(PostPrivacyEnum.FOLLOWERS)

    qs = qs.filter(privacy__in=allowed_privacies)
    qs = _apply_privacy_filter(qs, privacy_filter)
    if is_repost is not None:
        qs = qs.filter(is_repost=bool(is_repost))
    qs = _apply_feed_search(qs, search)
    return qs


def list_gym_feed(
    gym: Optional[Gym] = None,
    is_member_or_staff: bool = False,
    privacy_filter: Optional[str] = None,
    search: Optional[str] = None,
    requesting_user=None,
    feed_type: Optional[str] = None,
    owner_type: Optional[str] = None,
    user_id: Optional[uuid.UUID] = None,
    is_repost: Optional[bool] = None,
    social_ctx: Optional[Dict[str, object]] = None,
) -> QuerySet[GymPost]:
    """
    Returns an optimized queryset of community posts and reposts ordered by publication time.
    - When gym is specified: returns that gym's profile feed.
    - When user_id is specified (and gym is None): returns that public user's profile feed.
    - Otherwise: returns the personalized (or guest) global feed.
    """
    if gym is not None:
        return _list_single_gym_feed(
            gym=gym,
            is_member_or_staff=is_member_or_staff,
            privacy_filter=privacy_filter,
            search=search,
            requesting_user=requesting_user,
            is_repost=is_repost,
        )

    if requesting_user and getattr(requesting_user, "is_authenticated", False):
        return _list_personalized_feed(
            requesting_user=requesting_user,
            feed_type=feed_type,
            privacy_filter=privacy_filter,
            search=search,
            owner_type=owner_type,
            user_id=user_id,
            is_repost=is_repost,
            social_ctx=social_ctx,
        )

    return _list_guest_feed(
        feed_type=feed_type,
        privacy_filter=privacy_filter,
        search=search,
        owner_type=owner_type,
        user_id=user_id,
        is_repost=is_repost,
    )


def list_my_posts(
    user: User,
    owner_type: str = PostOwnerTypeEnum.USER,
    gym: Optional[Gym] = None,
    privacy_filter: Optional[str] = None,
    is_repost: Optional[bool] = None,
    search: Optional[str] = None,
) -> QuerySet[GymPost]:
    """
    Returns posts and reposts belonging to the requesting user's personal profile feed
    or active gym profile feed (including private posts).
    """
    qs = _build_base_posts_queryset()

    if owner_type == PostOwnerTypeEnum.GYM:
        if not gym:
            raise DomainValidationError("Gym context is required.")
        is_owner_or_staff = (
            user.is_superuser
            or gym.owner_user_id == user.id
            or GymStaffAssignment.objects.filter(
                gym=gym, user=user, status=StaffStatus.ACTIVE
            ).exists()
        )
        if not is_owner_or_staff:
            raise PermissionDeniedError("You do not have permission to view this gym's private profile feed.")
        qs = qs.filter(owner_type=PostOwnerTypeEnum.GYM, gym=gym)
    else:
        qs = qs.filter(owner_type=PostOwnerTypeEnum.USER, author_user=user)

    qs = _apply_privacy_filter(qs, privacy_filter)
    if is_repost is not None:
        qs = qs.filter(is_repost=bool(is_repost))
    qs = _apply_feed_search(qs, search)
    return qs.order_by("-published_at")


def _check_gym_post_access(
    post: GymPost,
    gym: Gym,
    is_member_or_staff: bool = False,
    requesting_user=None,
) -> None:
    setting = getattr(gym, "settings", None)
    if not setting:
        setting = GymSetting.objects.filter(gym=gym).first()

    if setting and setting.is_deleted:
        raise ResourceNotFoundError("Gym not found.")

    is_authenticated = bool(requesting_user and getattr(requesting_user, "is_authenticated", False))
    is_owner_or_staff = False
    if is_authenticated:
        if gym.owner_user_id == requesting_user.id or requesting_user.is_superuser:
            is_owner_or_staff = True
        elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
            is_owner_or_staff = True

    if setting and not setting.is_published and not is_owner_or_staff:
        raise ResourceNotFoundError("Gym not found.")

    if is_owner_or_staff:
        return

    if setting and setting.is_deactivated and not is_member_or_staff:
        raise DomainValidationError("This gym is deactivated.")

    if is_authenticated and GymBlockedUser.objects.filter(gym=gym, user=requesting_user).exists():
        raise PermissionDeniedError("You have been blocked by this gym.")

    if not check_posts_age_restriction(gym, requesting_user):
        raise PermissionDeniedError("This gym's posts are age-restricted. You do not meet the minimum age requirement.")

    if post.privacy == PostPrivacyEnum.PRIVATE:
        raise PermissionDeniedError("This post is private.")

    if post.privacy == PostPrivacyEnum.FOLLOWERS:
        is_follower = is_authenticated and GymFollow.objects.filter(user=requesting_user, gym=gym).exists()
        if not is_follower:
            raise PermissionDeniedError("This post is restricted to gym followers.")

    if post.privacy in (PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY) and not is_member_or_staff:
        raise PermissionDeniedError("This post is restricted to gym members.")


def get_post_detail(
    gym: Gym,
    post_id: uuid.UUID,
    is_member_or_staff: bool = False,
    requesting_user=None,
) -> GymPost:
    """
    Retrieves a single gym post dossier scoped to a specific gym (strict tenant isolation).
    """
    setting = getattr(gym, "settings", None)
    if not setting:
        setting = GymSetting.objects.filter(gym=gym).first()

    if setting and setting.is_deleted:
        raise ResourceNotFoundError("Gym not found.")

    is_owner_or_staff = False
    if requesting_user and getattr(requesting_user, "is_authenticated", False):
        if gym.owner_user_id == requesting_user.id or requesting_user.is_superuser:
            is_owner_or_staff = True
        elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
            is_owner_or_staff = True

    if setting and not setting.is_published and not is_owner_or_staff:
        raise ResourceNotFoundError("Gym not found.")

    try:
        post = (
            _build_base_posts_queryset()
            .filter(gym=gym, id=post_id)
            .get()
        )
    except GymPost.DoesNotExist:
        raise ResourceNotFoundError("Post not found.")

    if not is_owner_or_staff:
        _check_gym_post_access(
            post=post,
            gym=gym,
            is_member_or_staff=is_member_or_staff,
            requesting_user=requesting_user,
        )

    return post


def get_post_detail_by_id(
    post_id: uuid.UUID,
    requesting_user=None,
    for_management: bool = False,
) -> GymPost:
    """
    Retrieves a single post or repost (Personal User or Gym) by UUID,
    enforcing owner-type privacy, blocklist, lifecycle, and age restriction rules.
    """
    post = _build_base_posts_queryset().filter(id=post_id).first()
    if not post:
        raise ResourceNotFoundError("Post not found.")

    if for_management:
        return post

    is_authenticated = bool(requesting_user and getattr(requesting_user, "is_authenticated", False))

    if post.owner_type == PostOwnerTypeEnum.USER or post.gym is None:
        author = post.author_user
        is_owner = is_authenticated and (requesting_user.id == author.id or requesting_user.is_superuser)
        author_setting = author.get_settings()
        if author_setting.is_deleted:
            raise ResourceNotFoundError("Post not found.")
        if author_setting.is_deactivated and not is_owner:
            raise ResourceNotFoundError("Post not found.")

        if is_owner:
            return post

        if is_authenticated:
            is_blocked = UserBlockedUser.objects.filter(
                Q(blocker=author, blocked_user=requesting_user)
                | Q(blocker=requesting_user, blocked_user=author)
            ).exists()
            if is_blocked:
                raise PermissionDeniedError("You cannot view this user's post.")

        if post.privacy == PostPrivacyEnum.PRIVATE:
            raise PermissionDeniedError("This post is private.")

        is_follower = (
            is_authenticated
            and UserFollow.objects.filter(follower=requesting_user, followed_user=author).exists()
        )
        if post.privacy == PostPrivacyEnum.FOLLOWERS and not is_follower:
            raise PermissionDeniedError("This post is restricted to followers.")

        profile = getattr(author, "profile", None)
        if profile and profile.is_private and not is_follower:
            raise PermissionDeniedError("This user's account is private.")

        return post

    gym = post.gym
    is_member_or_staff = False
    if is_authenticated:
        if gym.owner_user_id == requesting_user.id or requesting_user.is_superuser:
            is_member_or_staff = True
        elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
            is_member_or_staff = True
        elif Member.objects.filter(gym=gym).filter(Q(user=requesting_user) | Q(email=requesting_user.email)).exists():
            is_member_or_staff = True

    _check_gym_post_access(
        post=post,
        gym=gym,
        is_member_or_staff=is_member_or_staff,
        requesting_user=requesting_user,
    )
    return post


def list_post_reposts(
    post_id: uuid.UUID,
    requesting_user=None,
) -> QuerySet[GymPost]:
    """
    Lists visible profile reposts of the given post_id after verifying the caller can view the post.
    """
    target_post = get_post_detail_by_id(post_id=post_id, requesting_user=requesting_user, for_management=False)
    qs = list_gym_feed(requesting_user=requesting_user, is_repost=True)
    return qs.filter(source_post=target_post)


def get_post_media_by_id(
    post_id: uuid.UUID,
    media_id: uuid.UUID,
    gym: Optional[Gym] = None,
) -> GymPostMedia:
    """
    Retrieves a specific media attachment associated with a post.
    """
    filters = {"id": media_id, "post_id": post_id}
    if gym is not None:
        filters["post__gym"] = gym
    try:
        return (
            GymPostMedia.objects.filter(**filters)
            .select_related("post", "post__gym", "post__author_user")
            .get()
        )
    except GymPostMedia.DoesNotExist:
        raise ResourceNotFoundError("Post media attachment not found.")


def stream_gym_feed(
    gym: Gym,
    is_member_or_staff: bool = False,
    chunk_size: int = 500,
) -> Generator[GymPost, None, None]:
    """
    Memory-efficient generator for social feed exports and bulk streaming.
    """
    qs = list_gym_feed(gym=gym, is_member_or_staff=is_member_or_staff)
    yield from qs.iterator(chunk_size=chunk_size)
