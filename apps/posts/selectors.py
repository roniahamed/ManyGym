import uuid
from typing import Optional, Generator
from django.db.models import QuerySet, Q, Count
from django.utils import timezone

from apps.gyms.models import Gym, GymSetting, GymBlockedUser
from apps.access_control.models import GymStaffAssignment
from apps.posts.models import GymPost, GymPostMedia
from common.enums import PostPrivacyEnum, PostsAgeRestrictionEnum, StaffStatus
from common.exceptions import ResourceNotFoundError, PermissionDeniedError, DomainValidationError


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

    age_thresholds = {
        PostsAgeRestrictionEnum.AGE_17_PLUS: 17,
        PostsAgeRestrictionEnum.AGE_18_PLUS: 18,
        PostsAgeRestrictionEnum.AGE_19_PLUS: 19,
        PostsAgeRestrictionEnum.AGE_20_PLUS: 20,
    }
    required_age = age_thresholds.get(policy, 0)
    if required_age == 0:
        return True

    if not requesting_user or not requesting_user.is_authenticated:
        return False

    if requesting_user.is_superuser or gym.owner_user_id == requesting_user.id:
        return True

    if GymStaffAssignment.objects.filter(gym=gym, user=requesting_user, status=StaffStatus.ACTIVE).exists():
        return True

    profile = getattr(requesting_user, "profile", None)
    if not profile or not profile.date_of_birth:
        return False

    dob = profile.date_of_birth
    today = timezone.now().date()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return age >= required_age


def list_gym_feed(
    gym: Gym,
    is_member_or_staff: bool = False,
    privacy_filter: Optional[str] = None,
    search: Optional[str] = None,
    requesting_user=None,
) -> QuerySet[GymPost]:
    """
    Returns an optimized queryset of gym community posts ordered by publication time.
    Visibility Rules:
    - Public / Unauthenticated / Non-member users see ONLY public posts.
    - Verified Members and Staff see both public and members_only posts.
    - Respects GymBlockedUser, gym lifecycle (deleted/deactivated), and posts_age_restriction.
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
        # Members and staff can view public and members_only posts
        if privacy_filter:
            p_val = privacy_filter.strip().lower()
            if p_val in (PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY):
                qs = qs.filter(privacy__in=[PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY])
            elif p_val == PostPrivacyEnum.PUBLIC:
                qs = qs.filter(privacy=PostPrivacyEnum.PUBLIC)
        else:
            # All visible to member/staff
            qs = qs.filter(privacy__in=[PostPrivacyEnum.PUBLIC, PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY])
    else:
        # Non-members / Guests strictly restricted to PUBLIC posts
        qs = qs.filter(privacy=PostPrivacyEnum.PUBLIC)

    if search:
        search_clean = search.strip()
        qs = qs.filter(
            Q(content_text__icontains=search_clean)
            | Q(author_user__first_name__icontains=search_clean)
            | Q(author_user__last_name__icontains=search_clean)
        ).distinct()

    return qs


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
