import uuid
from typing import Optional, Generator, Dict, Set, List
from django.db.models import QuerySet, Q, Count
from django.utils import timezone

from apps.gyms.models import Gym, GymSetting, GymBlockedUser, GymFollow
from apps.access_control.models import GymStaffAssignment
from apps.users.models import User, UserFollow, UserBlockedUser
from apps.members.models import Member
from apps.posts.models import GymPost, GymPostMedia
from common.enums import (
    PostPrivacyEnum,
    PostsAgeRestrictionEnum,
    StaffStatus,
    FeedTypeEnum,
    normalize_feed_type,
)
from common.exceptions import ResourceNotFoundError, PermissionDeniedError, DomainValidationError


def get_user_social_context(user: Optional[User]) -> Dict[str, Set[uuid.UUID]]:
    """
    Computes social relationships for an authenticated user to drive feed personalization:
    - connected_gym_ids: Gyms where user is owner, active staff, or member.
    - followed_gym_ids: Gyms followed by user.
    - followed_user_ids: Users followed by user.
    - blocked_gym_ids: Gyms that have blocked the user.
    - blocked_user_ids: Users who blocked the user or whom the user has blocked.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return {
            "connected_gym_ids": set(),
            "followed_gym_ids": set(),
            "followed_user_ids": set(),
            "blocked_gym_ids": set(),
            "blocked_user_ids": set(),
        }

    # 1. Connected gyms (Owner, Staff, or Member) in 1 optimized database query
    connected_gym_ids = set(
        Gym.objects.filter(
            Q(owner_user=user)
            | Q(staff_assignments__user=user, staff_assignments__status=StaffStatus.ACTIVE)
            | Q(members__user=user)
            | Q(members__email=user.email)
        ).values_list("id", flat=True)
    )

    # 2. Followed gyms
    followed_gym_ids = set(
        GymFollow.objects.filter(user=user).values_list("gym_id", flat=True)
    )

    # 3. Followed users
    followed_user_ids = set(
        UserFollow.objects.filter(follower=user).values_list("followed_user_id", flat=True)
    )

    # 4. Blocked gyms
    blocked_gym_ids = set(
        GymBlockedUser.objects.filter(user=user).values_list("gym_id", flat=True)
    )

    # 5. Mutually blocked users (in 1 optimized query)
    blocked_records = UserBlockedUser.objects.filter(
        Q(blocker=user) | Q(blocked_user=user)
    ).values_list("blocker_id", "blocked_user_id")
    blocked_user_ids = set()
    for blocker_id, target_id in blocked_records:
        if blocker_id == user.id:
            blocked_user_ids.add(target_id)
        else:
            blocked_user_ids.add(blocker_id)

    return {
        "connected_gym_ids": connected_gym_ids,
        "followed_gym_ids": followed_gym_ids,
        "followed_user_ids": followed_user_ids,
        "blocked_gym_ids": blocked_gym_ids,
        "blocked_user_ids": blocked_user_ids,
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


def _build_base_posts_queryset() -> QuerySet[GymPost]:
    """Returns an optimized base queryset with required foreign keys and media prefetched."""
    return (
        GymPost.objects.all()
        .select_related("gym", "gym__settings", "author_user__profile")
        .prefetch_related("media_attachments")
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
    """Applies post privacy filter ('public' or 'members_only')."""
    if not privacy_filter:
        return qs
    val = privacy_filter.strip().lower()
    if val in (PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY):
        return qs.filter(privacy__in=[PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY])
    if val == PostPrivacyEnum.PUBLIC:
        return qs.filter(privacy=PostPrivacyEnum.PUBLIC)
    return qs


def _list_personalized_feed(
    requesting_user: User,
    feed_type: Optional[str] = None,
    privacy_filter: Optional[str] = None,
    search: Optional[str] = None,
) -> QuerySet[GymPost]:
    """
    Constructs personalized community feed for an authenticated user:
    - Posts from followed list (followed gyms and users)
    - Posts from connected gym(s) (including members_only posts)
    - Public posts of any users or gyms across the platform
    """
    social_ctx = get_user_social_context(requesting_user)
    connected_gym_ids = social_ctx["connected_gym_ids"]
    followed_gym_ids = social_ctx["followed_gym_ids"]
    followed_user_ids = social_ctx["followed_user_ids"]
    blocked_gym_ids = social_ctx["blocked_gym_ids"]
    blocked_user_ids = social_ctx["blocked_user_ids"]

    qs = _build_base_posts_queryset().exclude(gym__settings__is_deleted=True)

    # Exclude blocked entities
    if blocked_gym_ids:
        qs = qs.exclude(gym_id__in=blocked_gym_ids)
    if blocked_user_ids:
        qs = qs.exclude(author_user_id__in=blocked_user_ids)

    # Enforce age restriction across gyms
    if not requesting_user.is_superuser:
        user_age = get_user_age(requesting_user)
        restricted_policies = get_excluded_age_policy_codes(user_age)
        if restricted_policies:
            exempt_gym_ids = set(
                Gym.objects.filter(owner_user=requesting_user).values_list("id", flat=True)
            ).union(
                GymStaffAssignment.objects.filter(
                    user=requesting_user, status=StaffStatus.ACTIVE
                ).values_list("gym_id", flat=True)
            )
            qs = qs.exclude(
                Q(gym__settings__posts_age_restriction__in=restricted_policies)
                & ~Q(gym_id__in=exempt_gym_ids)
            )

    # Feed Visibility Components:
    # 1. Public posts from active published gyms or connected gyms
    public_eligible = (
        Q(privacy=PostPrivacyEnum.PUBLIC)
        & (
            Q(gym__settings__is_published=True, gym__settings__is_deactivated=False)
            | Q(gym_id__in=connected_gym_ids)
        )
    )

    # 2. Connected gyms: both public and members_only posts
    connected_eligible = (
        Q(gym_id__in=connected_gym_ids)
        & Q(privacy__in=[PostPrivacyEnum.PUBLIC, PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY])
    )

    # 3. Followed list: posts from followed gyms or authored by followed users
    followed_eligible = (
        (Q(gym_id__in=followed_gym_ids) | Q(author_user_id__in=followed_user_ids))
        & (public_eligible | connected_eligible)
    )

    canonical_feed_type = normalize_feed_type(feed_type)

    if canonical_feed_type == FeedTypeEnum.FOLLOWED:
        qs = qs.filter(followed_eligible)
    elif canonical_feed_type == FeedTypeEnum.CONNECTED:
        qs = qs.filter(connected_eligible)
    elif canonical_feed_type == FeedTypeEnum.PUBLIC:
        qs = qs.filter(public_eligible)
    else:
        # Default ALL: Combined feed of Followed list, Connected gyms, and Public posts
        qs = qs.filter(public_eligible | connected_eligible | followed_eligible)

    qs = _apply_privacy_filter(qs, privacy_filter)
    qs = _apply_feed_search(qs, search)

    return qs.distinct().order_by("-published_at")


def _list_guest_feed(
    feed_type: Optional[str] = None,
    privacy_filter: Optional[str] = None,
    search: Optional[str] = None,
) -> QuerySet[GymPost]:
    """Constructs community feed for unauthenticated guests (public posts only)."""
    canonical_feed_type = normalize_feed_type(feed_type)
    if canonical_feed_type in (FeedTypeEnum.FOLLOWED, FeedTypeEnum.CONNECTED):
        return GymPost.objects.none()

    if privacy_filter:
        val = privacy_filter.strip().lower()
        if val in (PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY):
            return GymPost.objects.none()

    excluded_policies = get_excluded_age_policy_codes(None)

    qs = (
        _build_base_posts_queryset()
        .filter(
            privacy=PostPrivacyEnum.PUBLIC,
            gym__settings__is_deleted=False,
            gym__settings__is_published=True,
            gym__settings__is_deactivated=False,
        )
        .exclude(gym__settings__posts_age_restriction__in=excluded_policies)
    )

    qs = _apply_feed_search(qs, search)
    return qs.distinct().order_by("-published_at")


def _list_single_gym_feed(
    gym: Gym,
    is_member_or_staff: bool = False,
    privacy_filter: Optional[str] = None,
    search: Optional[str] = None,
    requesting_user=None,
) -> QuerySet[GymPost]:
    """Retrieves posts for a specific gym with lifecycle and visibility checks."""
    setting = getattr(gym, "settings", None)
    if not setting:
        setting = GymSetting.objects.filter(gym=gym).first()

    if setting and setting.is_deleted:
        raise ResourceNotFoundError("Gym not found.")

    is_owner_or_staff = False
    if requesting_user and requesting_user.is_authenticated:
        if gym.owner_user_id == requesting_user.id or requesting_user.is_superuser:
            is_owner_or_staff = True
        elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
            is_owner_or_staff = True

    if setting and not setting.is_published and not is_owner_or_staff:
        raise ResourceNotFoundError("Gym not found.")

    if setting and setting.is_deactivated and not is_member_or_staff:
        return GymPost.objects.none()

    if requesting_user and requesting_user.is_authenticated:
        if GymBlockedUser.objects.filter(gym=gym, user=requesting_user).exists():
            return GymPost.objects.none()

    if not check_posts_age_restriction(gym, requesting_user):
        return GymPost.objects.none()

    qs = (
        GymPost.objects.filter(gym=gym)
        .select_related("gym", "author_user__profile")
        .prefetch_related("media_attachments")
        .annotate(media_count=Count("media_attachments", distinct=True))
        .order_by("-published_at")
    )

    if is_member_or_staff:
        qs = _apply_privacy_filter(qs, privacy_filter)
        if not privacy_filter:
            qs = qs.filter(privacy__in=[PostPrivacyEnum.PUBLIC, PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY])
    else:
        qs = qs.filter(privacy=PostPrivacyEnum.PUBLIC)

    qs = _apply_feed_search(qs, search)
    return qs.distinct()


def list_gym_feed(
    gym: Optional[Gym] = None,
    is_member_or_staff: bool = False,
    privacy_filter: Optional[str] = None,
    search: Optional[str] = None,
    requesting_user=None,
    feed_type: Optional[str] = None,
) -> QuerySet[GymPost]:
    """
    Returns an optimized queryset of gym community posts ordered by publication time.
    When gym is None, returns personalized feed combining:
    1. Posts of followed list (followed users and followed gyms)
    2. Posts of connected gym(s) (including members_only posts)
    3. Public posts of any users or gyms across the platform
    Filters:
    - feed_type: 'all' (default), 'followed', 'connected', or 'public'.
    - privacy_filter: 'public' or 'members_only'.
    - search: keyword search in content text, author names, or gym names.
    Respects GymBlockedUser, UserBlockedUser, gym lifecycle, and age restriction policies.
    """
    if gym is not None:
        return _list_single_gym_feed(
            gym=gym,
            is_member_or_staff=is_member_or_staff,
            privacy_filter=privacy_filter,
            search=search,
            requesting_user=requesting_user,
        )

    if requesting_user and getattr(requesting_user, "is_authenticated", False):
        return _list_personalized_feed(
            requesting_user=requesting_user,
            feed_type=feed_type,
            privacy_filter=privacy_filter,
            search=search,
        )

    return _list_guest_feed(
        feed_type=feed_type,
        privacy_filter=privacy_filter,
        search=search,
    )


def get_post_detail(
    gym: Gym,
    post_id: uuid.UUID,
    is_member_or_staff: bool = False,
    requesting_user=None,
) -> GymPost:
    """
    Retrieves a single gym post dossier with all attached media.
    Enforces privacy access rules, blocklist, lifecycle state, and age restriction.
    """
    setting = getattr(gym, "settings", None)
    if not setting:
        setting = GymSetting.objects.filter(gym=gym).first()

    if setting and setting.is_deleted:
        raise ResourceNotFoundError("Gym not found.")

    is_owner_or_staff = False
    if requesting_user and requesting_user.is_authenticated:
        if gym.owner_user_id == requesting_user.id or requesting_user.is_superuser:
            is_owner_or_staff = True
        elif GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
            is_owner_or_staff = True

    if setting and not setting.is_published and not is_owner_or_staff:
        raise ResourceNotFoundError("Gym not found.")

    if setting and setting.is_deactivated and not is_member_or_staff:
        raise DomainValidationError("This gym is deactivated.")

    if requesting_user and requesting_user.is_authenticated:
        if GymBlockedUser.objects.filter(gym=gym, user=requesting_user).exists():
            raise PermissionDeniedError("You have been blocked by this gym.")

    if not check_posts_age_restriction(gym, requesting_user):
        raise PermissionDeniedError("This gym's posts are age-restricted. You do not meet the minimum age requirement.")

    try:
        post = (
            GymPost.objects.filter(gym=gym, id=post_id)
            .select_related("gym", "author_user__profile")
            .prefetch_related("media_attachments")
            .get()
        )
    except GymPost.DoesNotExist:
        raise ResourceNotFoundError("Post not found.")

    if post.privacy in (PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY) and not is_member_or_staff:
        raise PermissionDeniedError("This post is restricted to gym members.")

    return post


def get_post_media_by_id(
    gym: Gym,
    post_id: uuid.UUID,
    media_id: uuid.UUID,
) -> GymPostMedia:
    """
    Retrieves a specific media attachment associated with a gym post.
    """
    try:
        return (
            GymPostMedia.objects.filter(id=media_id, post_id=post_id, post__gym=gym)
            .select_related("post__gym")
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
