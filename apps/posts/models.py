import uuid
from django.db import models
from django.utils import timezone

from common.enums import PostOwnerTypeEnum, PostPrivacyEnum, MediaTypeEnum
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
