import uuid
from typing import Optional, Generator
from django.db.models import QuerySet, Q, Count

from apps.gyms.models import Gym
from apps.posts.models import GymPost, GymPostMedia
from common.enums import PostPrivacyEnum
from common.exceptions import ResourceNotFoundError, PermissionDeniedError


def list_gym_feed(
    gym: Gym,
    is_member_or_staff: bool = False,
    privacy_filter: Optional[str] = None,
    search: Optional[str] = None,
) -> QuerySet[GymPost]:
    """
    Returns an optimized queryset of gym community posts ordered by publication time.
    Visibility Rules:
    - Public / Unauthenticated / Non-member users see ONLY public posts.
    - Verified Members and Staff see both public and members_only posts.
    """
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
) -> GymPost:
    """
    Retrieves a single gym post dossier with all attached media.
    Enforces privacy access rules.
    """
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
