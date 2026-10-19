import uuid
from django.db import models
from django.utils import timezone

from common.enums import PostPrivacyEnum, MediaTypeEnum
from common.models import OptimizedMediaMixin


class GymPost(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="posts",
    )
    author_user = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="gym_posts",
    )
    content_text = models.TextField(blank=True, null=True, help_text="Optional if media attachments exist")
    privacy = models.CharField(
        max_length=30,
        choices=PostPrivacyEnum.choices,
        default=PostPrivacyEnum.PUBLIC,
        db_index=True,
    )
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
        ]

    def __str__(self):
        snippet = (self.content_text or "Media Post")[:30]
        return f"Post by {self.author_user.email} at {self.gym.name}: {snippet}"


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
