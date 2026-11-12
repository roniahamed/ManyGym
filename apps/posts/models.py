import uuid
from django.db import models
from django.utils import timezone

from common.enums import (
    CommentMediaTypeEnum,
    MediaTypeEnum,
    PostOwnerTypeEnum,
    PostPrivacyEnum,
)
from common.models import OptimizedMediaMixin


class GymPost(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_type = models.CharField(
        max_length=10,
        choices=PostOwnerTypeEnum.choices,
        default=PostOwnerTypeEnum.GYM,
        db_index=True,
        help_text="Whether this post/repost belongs to a public user or a gym.",
    )
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="posts",
        null=True,
        blank=True,
        help_text="Gym entity when owner_type='gym'; null for public user posts/reposts.",
    )
    author_user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="gym_posts",
    )
    source_post = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reposts",
        help_text="Optional original post shared/reposted onto this profile feed.",
    )
    is_repost = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if this post is a repost/share of another post.",
    )
    content_text = models.TextField(blank=True, null=True, help_text="Optional if media attachments or source_post exist")
    privacy = models.CharField(
        max_length=30,
        choices=PostPrivacyEnum.choices,
        default=PostPrivacyEnum.PUBLIC,
        db_index=True,
    )
    reposts_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "gym_posts"
        verbose_name = "Gym Post"
        verbose_name_plural = "Gym Posts"
        ordering = ["-published_at"]
        indexes = [
            models.Index(fields=["gym", "privacy", "-published_at"], name="idx_gpost_gym_priv_pub"),
            models.Index(fields=["gym", "-published_at"], name="idx_gpost_gym_pub"),
            models.Index(fields=["author_user", "-published_at"], name="idx_gpost_author_pub"),
            models.Index(fields=["owner_type", "privacy", "-published_at"], name="idx_gpost_own_priv_pub"),
            models.Index(fields=["author_user", "owner_type", "-published_at"], name="idx_gpost_auth_own_pub"),
            models.Index(fields=["source_post", "-published_at"], name="idx_gpost_src_pub"),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    (models.Q(owner_type=PostOwnerTypeEnum.USER) & models.Q(gym__isnull=True))
                    | (models.Q(owner_type=PostOwnerTypeEnum.GYM) & models.Q(gym__isnull=False))
                ),
                name="post_owner_type_gym_consistency",
            ),
            models.CheckConstraint(
                check=(
                    ~models.Q(owner_type=PostOwnerTypeEnum.USER, privacy=PostPrivacyEnum.MEMBERS_ONLY)
                    & ~models.Q(owner_type=PostOwnerTypeEnum.USER, privacy=PostPrivacyEnum.GYM_MEMBERS_ONLY)
                ),
                name="post_user_no_members_only_privacy",
            ),
        ]

    def __str__(self):
        snippet = (self.content_text or ("Repost" if self.is_repost else "Media Post"))[:30]
        owner_label = self.gym.name if self.owner_type == PostOwnerTypeEnum.GYM and self.gym_id else self.author_user.email
        return f"Post({self.owner_type}:{owner_label}): {snippet}"


class GymPostMedia(OptimizedMediaMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(
        GymPost,
        on_delete=models.CASCADE,
        related_name="media_attachments",
    )
    media_url = models.CharField(max_length=1000)
    media_type = models.CharField(
        max_length=20,
        choices=MediaTypeEnum.choices,
        default=MediaTypeEnum.PICTURE,
    )
    file_size_bytes = models.BigIntegerField(default=0, help_text="Size in bytes: <=10MB image, <=200MB video")
    order_index = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gym_post_media"
        verbose_name = "Gym Post Media"
        verbose_name_plural = "Gym Post Media"
        ordering = ["order_index", "created_at"]
        indexes = [
            models.Index(fields=["post", "order_index"], name="idx_gpost_med_post_ord"),
        ]

    def __str__(self):
        return f"{self.media_type.capitalize()} for Post {self.post_id} (order {self.order_index})"


class PostComment(OptimizedMediaMixin, models.Model):
    """
    Represents a comment on a community post or a nested reply to another comment.
    Supports optional text alongside an optional single media attachment (photo, video, or GIF),
    arbitrary nesting tracked via root_comment + depth, and atomic reply/comment counters.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_post = models.ForeignKey(
        GymPost,
        on_delete=models.CASCADE,
        related_name="comments",
        help_text="Post or repost that this comment thread belongs to.",
    )
    source_comment = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
        help_text="Optional parent comment ID when this entry is a reply.",
    )
    root_comment = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="thread_comments",
        help_text="Top-level ancestor comment for O(1) nested thread batch loading; null for top-level comments.",
    )
    depth = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text="Nesting depth: 0 for top-level post comments, 1+ for nested replies.",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="post_comments",
        help_text="User who authored this comment or reply.",
    )
    reply_to_user = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="comment_replies_received",
        help_text="User being replied to (derived from source_comment.user when replying).",
    )
    owner_type = models.CharField(
        max_length=10,
        choices=PostOwnerTypeEnum.choices,
        default=PostOwnerTypeEnum.USER,
        db_index=True,
        help_text="Whether the commenter is acting as a personal user or a gym page.",
    )
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="post_comments",
        null=True,
        blank=True,
        help_text="Gym entity when owner_type='gym'; null for personal user comments.",
    )

    comment_text = models.TextField(
        blank=True,
        null=True,
        help_text="Optional text body of the comment (required if no photo/video/gif is attached).",
    )
    comment_photo = models.CharField(
        max_length=1000,
        blank=True,
        null=True,
        help_text="Optional photo URL attached to the comment.",
    )
    comment_video = models.CharField(
        max_length=1000,
        blank=True,
        null=True,
        help_text="Optional video URL attached to the comment.",
    )
    comment_gif = models.CharField(
        max_length=1000,
        blank=True,
        null=True,
        help_text="Optional GIF URL attached to the comment.",
    )
    media_type = models.CharField(
        max_length=20,
        choices=CommentMediaTypeEnum.choices,
        blank=True,
        null=True,
        db_index=True,
        help_text="Media attachment kind ('photo', 'video', 'gif') when media is present.",
    )
    file_size_bytes = models.BigIntegerField(
        default=0,
        help_text="Uploaded file size in bytes: <=10MB photo/gif, <=200MB video.",
    )
    duration_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Optional video playback duration in seconds.",
    )

    replies_count = models.PositiveIntegerField(
        default=0,
        help_text="Direct child replies count.",
    )
    total_replies_count = models.PositiveIntegerField(
        default=0,
        help_text="Total nested descendant replies count across all depths under this comment.",
    )
    is_edited = models.BooleanField(default=False)
    edited_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "post_comments"
        verbose_name = "Post Comment"
        verbose_name_plural = "Post Comments"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source_post", "source_comment", "-created_at"], name="idx_pcomm_post_src_new"),
            models.Index(fields=["source_post", "source_comment", "created_at"], name="idx_pcomm_post_src_old"),
            models.Index(fields=["source_post", "source_comment", "-replies_count", "-created_at"], name="idx_pcomm_post_src_rep"),
            models.Index(fields=["source_comment", "created_at"], name="idx_pcomm_parent_created"),
            models.Index(fields=["root_comment", "depth", "created_at"], name="idx_pcomm_root_depth_crt"),
            models.Index(fields=["user", "-created_at"], name="idx_pcomm_user_created"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(owner_type=PostOwnerTypeEnum.USER) & models.Q(gym__isnull=True))
                    | (models.Q(owner_type=PostOwnerTypeEnum.GYM) & models.Q(gym__isnull=False))
                ),
                name="comment_owner_type_gym_consistency",
            ),
            models.CheckConstraint(
                condition=models.Q(source_comment__isnull=True) | ~models.Q(source_comment=models.F("id")),
                name="comment_not_self_parent",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(source_comment__isnull=True, depth=0, root_comment__isnull=True)
                    | models.Q(source_comment__isnull=False, depth__gte=1, root_comment__isnull=False)
                ),
                name="comment_depth_root_consistency",
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(comment_text__isnull=False) & ~models.Q(comment_text=""))
                    | models.Q(comment_photo__isnull=False)
                    | models.Q(comment_video__isnull=False)
                    | models.Q(comment_gif__isnull=False)
                ),
                name="comment_has_content_or_media",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(comment_photo__isnull=True, comment_video__isnull=True, comment_gif__isnull=True)
                    | models.Q(comment_photo__isnull=False, comment_video__isnull=True, comment_gif__isnull=True)
                    | models.Q(comment_photo__isnull=True, comment_video__isnull=False, comment_gif__isnull=True)
                    | models.Q(comment_photo__isnull=True, comment_video__isnull=True, comment_gif__isnull=False)
                ),
                name="comment_single_media_attachment",
            ),
        ]

    @property
    def active_media_url(self) -> str | None:
        return self.comment_photo or self.comment_video or self.comment_gif

    @property
    def resolved_media_url(self) -> str | None:
        return self.optimized_url or self.active_media_url or self.original_url

    @property
    def resolved_thumbnail_url(self) -> str | None:
        return self.thumbnail_url or self.optimized_url or self.active_media_url or self.original_url

    def __str__(self):
        snippet = (self.comment_text or self.media_type or "Comment")[:30]
        return f"Comment({self.id}) on Post {self.source_post_id}: {snippet}"
