import uuid
from typing import Dict, List, Optional, Sequence
from django.db import connection
from django.db.models import F, Q, QuerySet, Window
from django.db.models.functions import RowNumber

from apps.posts.models import PostComment
from apps.posts.selectors import get_post_detail_by_id, get_user_social_context
from apps.users.models import User
from common.enums import CommentMediaTypeEnum, PostOwnerTypeEnum
from common.exceptions import (
    DomainValidationError,
    PermissionDeniedError,
    ResourceNotFoundError,
)


def _build_base_comments_queryset() -> QuerySet[PostComment]:
    """Returns an optimized base queryset for comments with author, gym, and reply target loaded."""
    return PostComment.objects.select_related(
        "user",
        "user__profile",
        "user__settings",
        "reply_to_user",
        "reply_to_user__profile",
        "gym",
        "gym__settings",
        "source_post",
        "source_post__gym",
        "source_post__author_user",
    )


def _apply_comment_visibility_filters(
    qs: QuerySet[PostComment],
    requesting_user: Optional[User],
    social_ctx: Dict[str, object],
) -> QuerySet[PostComment]:
    """
    Excludes comments from deleted/deactivated accounts, mutually blocked users,
    and deleted/unpublished/blocked gyms using precomputed social context.
    """
    is_authenticated = bool(requesting_user and getattr(requesting_user, "is_authenticated", False))
    is_superuser = bool(is_authenticated and requesting_user.is_superuser)

    qs = qs.exclude(user__settings__is_deleted=True)
    if is_authenticated:
        qs = qs.exclude(Q(user__settings__is_deactivated=True) & ~Q(user=requesting_user))
    else:
        qs = qs.exclude(user__settings__is_deactivated=True)

    qs = qs.exclude(Q(owner_type=PostOwnerTypeEnum.GYM) & Q(gym__settings__is_deleted=True))

    if is_superuser:
        return qs

    blocked_user_ids = social_ctx.get("blocked_user_ids", set())
    blocked_gym_ids = social_ctx.get("blocked_gym_ids", set())
    staff_or_owned_gym_ids = social_ctx.get("staff_or_owned_gym_ids", set())
    connected_gym_ids = social_ctx.get("connected_gym_ids", set())

    if blocked_user_ids:
        qs = qs.exclude(user_id__in=blocked_user_ids)

    if blocked_gym_ids:
        qs = qs.exclude(
            Q(owner_type=PostOwnerTypeEnum.GYM)
            & Q(gym_id__in=blocked_gym_ids)
            & ~Q(gym_id__in=staff_or_owned_gym_ids)
        )

    # Hide gym-authored comments from unpublished or deactivated gyms unless viewer is connected/staff
    qs = qs.exclude(
        Q(owner_type=PostOwnerTypeEnum.GYM)
        & Q(gym__settings__is_published=False)
        & ~Q(gym_id__in=staff_or_owned_gym_ids)
    )
    qs = qs.exclude(
        Q(owner_type=PostOwnerTypeEnum.GYM)
        & Q(gym__settings__is_deactivated=True)
        & ~Q(gym_id__in=connected_gym_ids)
    )
    return qs


def _apply_comment_media_filter(
    qs: QuerySet[PostComment],
    media_type: Optional[str],
) -> QuerySet[PostComment]:
    if not media_type:
        return qs
    cleaned = media_type.strip().lower()
    if not cleaned:
        return qs
    if cleaned == "text":
        return qs.filter(media_type__isnull=True)
    if cleaned in CommentMediaTypeEnum.values:
        return qs.filter(media_type=cleaned)
    raise DomainValidationError(
        f"Invalid media_type filter '{media_type}'. Choices: {list(CommentMediaTypeEnum.values) + ['text']}."
    )


def _apply_comment_sort(
    qs: QuerySet[PostComment],
    sort: Optional[str],
    default_sort: str = "newest",
) -> QuerySet[PostComment]:
    cleaned = (sort or default_sort).strip().lower()
    if cleaned == "newest":
        return qs.order_by("-created_at", "-id")
    if cleaned == "oldest":
        return qs.order_by("created_at", "id")
    if cleaned == "most_replied":
        return qs.order_by("-replies_count", "-created_at", "-id")
    raise DomainValidationError(
        f"Invalid sort '{sort}'. Allowed choices: ['newest', 'oldest', 'most_replied']."
    )


def list_post_comments(
    post_id: uuid.UUID,
    requesting_user=None,
    sort: Optional[str] = "newest",
    media_type: Optional[str] = None,
    social_ctx: Optional[Dict[str, object]] = None,
) -> QuerySet[PostComment]:
    """
    Returns an optimized queryset of visible top-level comments for a given post
    after verifying the caller is authorized to view the post.
    """
    post = get_post_detail_by_id(
        post_id=post_id,
        requesting_user=requesting_user,
        for_management=False,
    )
    if social_ctx is None:
        social_ctx = get_user_social_context(requesting_user)

    qs = _build_base_comments_queryset().filter(
        source_post=post,
        source_comment__isnull=True,
    )
    qs = _apply_comment_visibility_filters(qs, requesting_user=requesting_user, social_ctx=social_ctx)
    qs = _apply_comment_media_filter(qs, media_type=media_type)
    return _apply_comment_sort(qs, sort=sort, default_sort="newest")


def get_comment_detail(
    comment_id: uuid.UUID,
    post_id: Optional[uuid.UUID] = None,
    requesting_user=None,
    for_management: bool = False,
    social_ctx: Optional[Dict[str, object]] = None,
) -> PostComment:
    """
    Retrieves a single comment or reply while enforcing post visibility,
    user/gym blocklists, and account lifecycle rules.
    """
    filters: Dict[str, object] = {"id": comment_id}
    if post_id is not None:
        filters["source_post_id"] = post_id

    comment = _build_base_comments_queryset().filter(**filters).first()
    if not comment:
        raise ResourceNotFoundError("Comment not found.")

    if for_management:
        return comment

    # Verify the viewer can access the parent post first
    get_post_detail_by_id(
        post_id=comment.source_post_id,
        requesting_user=requesting_user,
        for_management=False,
    )

    is_authenticated = bool(requesting_user and getattr(requesting_user, "is_authenticated", False))
    is_superuser = bool(is_authenticated and requesting_user.is_superuser)
    is_self = bool(is_authenticated and comment.user_id == requesting_user.id)

    author_setting = getattr(comment.user, "settings", None)
    if author_setting and author_setting.is_deleted:
        raise ResourceNotFoundError("Comment not found.")
    if author_setting and author_setting.is_deactivated and not (is_self or is_superuser):
        raise ResourceNotFoundError("Comment not found.")

    if social_ctx is None:
        social_ctx = get_user_social_context(requesting_user)

    if not is_superuser and not is_self:
        if comment.user_id in social_ctx.get("blocked_user_ids", set()):
            raise PermissionDeniedError("You cannot view this comment.")

    if comment.owner_type == PostOwnerTypeEnum.GYM and comment.gym:
        gym_setting = getattr(comment.gym, "settings", None)
        staff_or_owned = social_ctx.get("staff_or_owned_gym_ids", set())
        connected = social_ctx.get("connected_gym_ids", set())
        is_gym_staff = is_superuser or comment.gym_id in staff_or_owned

        if gym_setting and gym_setting.is_deleted:
            raise ResourceNotFoundError("Comment not found.")
        if gym_setting and not gym_setting.is_published and not is_gym_staff:
            raise ResourceNotFoundError("Comment not found.")
        if gym_setting and gym_setting.is_deactivated and not (is_gym_staff or comment.gym_id in connected):
            raise ResourceNotFoundError("Comment not found.")
        if not is_gym_staff and comment.gym_id in social_ctx.get("blocked_gym_ids", set()):
            raise PermissionDeniedError("You cannot view this comment.")

    return comment


def list_comment_replies(
    comment_id: uuid.UUID,
    post_id: Optional[uuid.UUID] = None,
    requesting_user=None,
    sort: Optional[str] = "oldest",
    media_type: Optional[str] = None,
    social_ctx: Optional[Dict[str, object]] = None,
) -> QuerySet[PostComment]:
    """
    Returns an optimized queryset of direct replies to a given comment (at any nesting depth)
    after verifying the caller can view both the parent comment and the parent post.
    """
    if social_ctx is None:
        social_ctx = get_user_social_context(requesting_user)

    parent_comment = get_comment_detail(
        comment_id=comment_id,
        post_id=post_id,
        requesting_user=requesting_user,
        for_management=False,
        social_ctx=social_ctx,
    )

    qs = _build_base_comments_queryset().filter(source_comment_id=parent_comment.id)
    qs = _apply_comment_visibility_filters(qs, requesting_user=requesting_user, social_ctx=social_ctx)
    qs = _apply_comment_media_filter(qs, media_type=media_type)
    return _apply_comment_sort(qs, sort=sort, default_sort="oldest")


def _fetch_bounded_replies_for_parents(
    parent_nodes: Sequence[PostComment],
    per_parent_limit: int,
    requesting_user=None,
    social_ctx: Optional[Dict[str, object]] = None,
    reply_sort: str = "oldest",
) -> List[PostComment]:
    """
    Fetches up to `per_parent_limit + 1` visible replies per parent comment ID in
    constant query count without loading unbounded reply trees into Python memory.
    """
    if not parent_nodes:
        return []

    if social_ctx is None:
        social_ctx = get_user_social_context(requesting_user)

    parent_ids = [node.id for node in parent_nodes]
    visible_qs = _apply_comment_visibility_filters(
        PostComment.objects.filter(source_comment_id__in=parent_ids),
        requesting_user=requesting_user,
        social_ctx=social_ctx,
    )

    if reply_sort == "newest":
        order_fields = ("-created_at", "-id")
        window_order = [F("created_at").desc(), F("id").desc()]
    elif reply_sort == "most_replied":
        order_fields = ("-replies_count", "created_at", "id")
        window_order = [F("replies_count").desc(), F("created_at").asc(), F("id").asc()]
    else:
        order_fields = ("created_at", "id")
        window_order = [F("created_at").asc(), F("id").asc()]

    total_possible = sum(node.replies_count for node in parent_nodes)
    # Fast path for typical pages: single direct ORM query when total replies are modest
    if total_possible <= 200:
        return list(
            _apply_comment_visibility_filters(
                _build_base_comments_queryset().filter(source_comment_id__in=parent_ids),
                requesting_user=requesting_user,
                social_ctx=social_ctx,
            ).order_by(*order_fields)
        )

    # Bounded SQL Window query for viral threads so PostgreSQL only emits <= (limit + 1) rows per parent
    ranked_qs = visible_qs.annotate(
        _rn=Window(
            expression=RowNumber(),
            partition_by=[F("source_comment_id")],
            order_by=window_order,
        )
    ).values("id", "_rn")
    inner_sql, params = ranked_qs.query.sql_with_params()

    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT id FROM ({inner_sql}) AS _ranked_replies WHERE _rn <= %s",
            [*params, per_parent_limit + 1],
        )
        selected_ids = [row[0] for row in cursor.fetchall()]

    if not selected_ids:
        return []

    return list(
        _build_base_comments_queryset()
        .filter(id__in=selected_ids)
        .order_by(*order_fields)
    )


def attach_nested_replies(
    comments: Sequence[PostComment],
    requesting_user=None,
    social_ctx: Optional[Dict[str, object]] = None,
    include_replies: bool = True,
    replies_limit: int = 2,
    reply_depth: int = 2,
    reply_sort: str = "oldest",
) -> List[PostComment]:
    """
    Attaches nested `_prefetched_replies` and `_has_more_replies` recursively up to
    `reply_depth` levels using at most O(reply_depth) queries for the entire page.
    Zero N+1 queries occur during serialization.
    """
    comment_list = list(comments)
    for node in comment_list:
        node._prefetched_replies = []
        node._has_more_replies = node.replies_count > 0

    if not comment_list or not include_replies or reply_depth <= 0 or replies_limit <= 0:
        return comment_list

    if social_ctx is None:
        social_ctx = get_user_social_context(requesting_user)

    current_level = [c for c in comment_list if c.replies_count > 0]

    for _ in range(reply_depth):
        if not current_level:
            break

        fetched_replies = _fetch_bounded_replies_for_parents(
            parent_nodes=current_level,
            per_parent_limit=replies_limit,
            requesting_user=requesting_user,
            social_ctx=social_ctx,
            reply_sort=reply_sort,
        )

        grouped: Dict[uuid.UUID, List[PostComment]] = {}
        for reply in fetched_replies:
            grouped.setdefault(reply.source_comment_id, []).append(reply)

        next_level: List[PostComment] = []
        for parent in current_level:
            children = grouped.get(parent.id, [])
            parent._has_more_replies = len(children) > replies_limit
            kept = children[:replies_limit]
            for child in kept:
                child._prefetched_replies = []
                child._has_more_replies = child.replies_count > 0
            parent._prefetched_replies = kept
            next_level.extend([child for child in kept if child.replies_count > 0])

        current_level = next_level

    return comment_list

