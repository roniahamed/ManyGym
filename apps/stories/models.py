import uuid
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone

from common.enums import (
    MediaTypeEnum,
    StoryLifetimeEnum,
    StoryOwnerTypeEnum,
    StoryPrivacyEnum,
)
from common.models import OptimizedMediaMixin


class Story(OptimizedMediaMixin, models.Model):
    """
    Ephemeral media story uploaded by either a Public User or a Gym.
    Supports a single image or video file, selectable lifetime (6h/12h/18h/24h/48h),
    optional source post reference, and owner-type-scoped privacy levels.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_type = models.CharField(
        max_length=10,
        choices=StoryOwnerTypeEnum.choices,
        default=StoryOwnerTypeEnum.USER,
        db_index=True,
        help_text="Whether this story belongs to a public user or a gym.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="stories",
        help_text="User who uploaded the story (author for public user stories, or staff/owner for gym stories).",
    )
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="stories",
        help_text="Gym entity when owner_type='gym'; null for public user stories.",
    )
    source_post = models.ForeignKey(
        "posts.GymPost",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stories",
        help_text="Optional original post shared into this story.",
    )

    # Single media attachment (image or video)
    media_url = models.CharField(max_length=1000)
    media_type = models.CharField(
        max_length=20,
        choices=MediaTypeEnum.choices,
        default=MediaTypeEnum.PICTURE,
    )
    file_size_bytes = models.BigIntegerField(
        default=0,
        help_text="Size in bytes: <=10MB image, <=200MB video.",
    )
    duration_seconds = models.FloatField(
        null=True,
        blank=True,
        help_text="Optional media playback duration in seconds.",
    )

    # Story presentation & metadata
    caption = models.TextField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Optional short text caption overlaid on the story.",
    )
    background_color = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        help_text="Optional backdrop hex/gradient color code.",
    )

    # Lifetime & Privacy
    lifetime_hours = models.PositiveSmallIntegerField(
        choices=StoryLifetimeEnum.choices,
        default=StoryLifetimeEnum.HOURS_18,
        db_index=True,
        help_text="Story lifetime in hours (6, 12, 18 [default], 24, or 48).",
    )
    privacy = models.CharField(
        max_length=30,
        choices=StoryPrivacyEnum.choices,
        default=StoryPrivacyEnum.PUBLIC,
        db_index=True,
        help_text="Public user: public/followers/private; Gym: public/followers/members_only/private.",
    )

    # Lifecycle & Engagement counters
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    views_count = models.PositiveIntegerField(default=0)
    is_archived = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stories"
        verbose_name = "Story"
        verbose_name_plural = "Stories"
        ordering = ["-published_at"]
        indexes = [
            models.Index(fields=["owner_type", "privacy", "expires_at", "-published_at"], name="idx_story_owner_priv_exp"),
            models.Index(fields=["user", "expires_at", "-published_at"], name="idx_story_user_exp"),
            models.Index(fields=["gym", "expires_at", "-published_at"], name="idx_story_gym_exp"),
            models.Index(fields=["expires_at", "is_archived"], name="idx_story_exp_arch"),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    (models.Q(owner_type=StoryOwnerTypeEnum.USER) & models.Q(gym__isnull=True))
                    | (models.Q(owner_type=StoryOwnerTypeEnum.GYM) & models.Q(gym__isnull=False))
                ),
                name="story_owner_type_gym_consistency",
            ),
            models.CheckConstraint(
                check=~models.Q(owner_type=StoryOwnerTypeEnum.USER, privacy=StoryPrivacyEnum.MEMBERS_ONLY),
                name="story_user_no_members_only_privacy",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self.published_at:
            self.published_at = timezone.now()
        if not self.expires_at:
            hours = int(self.lifetime_hours or StoryLifetimeEnum.HOURS_18)
            self.expires_at = self.published_at + timedelta(hours=hours)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        """Returns True if the story has passed its configured expiration timestamp."""
        return timezone.now() >= self.expires_at

    def __str__(self):
        owner_label = self.gym.name if self.owner_type == StoryOwnerTypeEnum.GYM and self.gym_id else self.user.email
        return f"Story({self.owner_type}:{owner_label}, {self.media_type}, {self.privacy})"


class StoryView(models.Model):
    """
    Tracks unique authenticated user views for a story.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name="views",
    )
    viewer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="story_views",
    )
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "story_views"
        verbose_name = "Story View"
        verbose_name_plural = "Story Views"
        ordering = ["-viewed_at"]
        constraints = [
            models.UniqueConstraint(fields=["story", "viewer_user"], name="unique_story_view"),
        ]
        indexes = [
            models.Index(fields=["story", "-viewed_at"], name="idx_sview_story_viewed"),
        ]

    def __str__(self):
        return f"{self.viewer_user.email} viewed Story {self.story_id}"

