import uuid
from django.conf import settings
from django.db import models

from common.enums import PostOwnerTypeEnum


class ReactionItem(models.Model):
    """
    Catalog item representing a reaction type (e.g., Smile 😊, Laugh 😆, Love ❤️, Fire 🔥).
    Supports customizable emoji reactions across the social ecosystem.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Unique programmatic slug for the reaction item (e.g. 'smile', 'laugh', 'fire').",
    )
    emoji = models.CharField(
        max_length=16,
        help_text="Visual emoji character (e.g. 😊, 😆, 🔥).",
    )
    label = models.CharField(
        max_length=50,
        help_text="Human-readable title (e.g. 'Smile', 'Laugh', 'Fire').",
    )
    order = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text="Display sorting order.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this reaction is currently active and selectable by users.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reaction_items"
        verbose_name = "Reaction Item"
        verbose_name_plural = "Reaction Items"
        ordering = ["order", "created_at"]
        indexes = [
            models.Index(fields=["is_active", "order"], name="idx_react_item_act_ord"),
        ]

    def __str__(self):
        return f"{self.emoji} {self.label} ({self.code})"


class Reaction(models.Model):
    """
    Represents a user or gym reaction on a post, story, or post comment.
    Enforces that exactly one polymorphic target is attached, and guarantees
    uniqueness per actor per target.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reactions",
        help_text="User who reacted (or authorized staff/owner reacting on behalf of a gym).",
    )
    owner_type = models.CharField(
        max_length=10,
        choices=PostOwnerTypeEnum.choices,
        default=PostOwnerTypeEnum.USER,
        db_index=True,
        help_text="Whether the reaction was submitted as a personal user or a gym.",
    )
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
        help_text="Gym entity when owner_type='gym'; null for personal user reactions.",
    )
    reaction_item = models.ForeignKey(
        ReactionItem,
        on_delete=models.CASCADE,
        related_name="reactions",
        help_text="Selected reaction emoji/item.",
    )

    # Polymorphic target references (exactly one must be populated)
    post = models.ForeignKey(
        "posts.GymPost",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
        help_text="Target post if reacting to a community post or repost.",
    )
    story = models.ForeignKey(
        "stories.Story",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
        help_text="Target story if reacting to an ephemeral story.",
    )
    comment = models.ForeignKey(
        "posts.PostComment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
        help_text="Target comment if reacting to a post comment or nested reply.",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reactions"
        verbose_name = "Reaction"
        verbose_name_plural = "Reactions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["post", "reaction_item", "-created_at"], name="idx_react_post_item_crt"),
            models.Index(fields=["story", "reaction_item", "-created_at"], name="idx_react_story_item_crt"),
            models.Index(fields=["comment", "reaction_item", "-created_at"], name="idx_react_comm_item_crt"),
            models.Index(fields=["user", "-created_at"], name="idx_react_user_crt"),
            models.Index(fields=["gym", "-created_at"], name="idx_react_gym_crt"),
        ]
        constraints = [
            # Ensure gym context consistency
            models.CheckConstraint(
                condition=(
                    (models.Q(owner_type=PostOwnerTypeEnum.USER) & models.Q(gym__isnull=True))
                    | (models.Q(owner_type=PostOwnerTypeEnum.GYM) & models.Q(gym__isnull=False))
                ),
                name="reaction_owner_type_gym_consistency",
            ),
            # Ensure exactly one target is specified
            models.CheckConstraint(
                condition=(
                    (models.Q(post__isnull=False) & models.Q(story__isnull=True) & models.Q(comment__isnull=True))
                    | (models.Q(post__isnull=True) & models.Q(story__isnull=False) & models.Q(comment__isnull=True))
                    | (models.Q(post__isnull=True) & models.Q(story__isnull=True) & models.Q(comment__isnull=False))
                ),
                name="reaction_exactly_one_target",
            ),
            # Personal user uniqueness per target
            models.UniqueConstraint(
                fields=["user", "post"],
                condition=models.Q(owner_type=PostOwnerTypeEnum.USER, post__isnull=False),
                name="unique_user_post_reaction",
            ),
            models.UniqueConstraint(
                fields=["user", "story"],
                condition=models.Q(owner_type=PostOwnerTypeEnum.USER, story__isnull=False),
                name="unique_user_story_reaction",
            ),
            models.UniqueConstraint(
                fields=["user", "comment"],
                condition=models.Q(owner_type=PostOwnerTypeEnum.USER, comment__isnull=False),
                name="unique_user_comment_reaction",
            ),
            # Gym entity uniqueness per target
            models.UniqueConstraint(
                fields=["gym", "post"],
                condition=models.Q(owner_type=PostOwnerTypeEnum.GYM, post__isnull=False),
                name="unique_gym_post_reaction",
            ),
            models.UniqueConstraint(
                fields=["gym", "story"],
                condition=models.Q(owner_type=PostOwnerTypeEnum.GYM, story__isnull=False),
                name="unique_gym_story_reaction",
            ),
            models.UniqueConstraint(
                fields=["gym", "comment"],
                condition=models.Q(owner_type=PostOwnerTypeEnum.GYM, comment__isnull=False),
                name="unique_gym_comment_reaction",
            ),
        ]

    @property
    def target_type(self) -> str:
        if self.post_id:
            return "post"
        if self.story_id:
            return "story"
        if self.comment_id:
            return "comment"
        return "unknown"

    @property
    def target_id(self) -> uuid.UUID | None:
        return self.post_id or self.story_id or self.comment_id

    def __str__(self):
        target = f"{self.target_type} {self.target_id}"
        actor = self.gym.name if self.owner_type == PostOwnerTypeEnum.GYM and self.gym else self.user.email
        emoji = self.reaction_item.emoji if self.reaction_item else "?"
        return f"Reaction({emoji} by {actor} on {target})"

