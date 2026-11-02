import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from common.enums import (
    GymTypeEnum,
    GymGenderRequired,
    GalleryCategoryEnum,
    MediaTypeEnum,
    ProcessingStatus,
    AudienceMessagingEnum,
    AudienceJoiningRequestEnum,
    AudienceMembersVisibilityEnum,
    AudienceFollowingVisibilityEnum,
    PostsAgeRestrictionEnum,
)
from common.models import OptimizedMediaMixin


class Gym(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_gyms",
    )
    name = models.CharField(max_length=255)
    profile_picture_url = models.CharField(max_length=1000, blank=True, null=True)
    cover_photo_url = models.CharField(max_length=1000, blank=True, null=True)
    short_description = models.TextField(blank=True, null=True)
    primary_type = models.CharField(
        max_length=50,
        choices=GymTypeEnum.choices,
        default=GymTypeEnum.GENERAL_FITNESS,
    )
    secondary_type = models.CharField(
        max_length=50,
        choices=GymTypeEnum.choices,
        blank=True,
        null=True,
    )
    gender_required = models.CharField(
        max_length=20,
        choices=GymGenderRequired.choices,
        default=GymGenderRequired.EVERYONE,
    )
    min_age = models.IntegerField(default=1)
    timezone = models.CharField(max_length=100, default="UTC")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "gyms"
        verbose_name = "Gym"
        verbose_name_plural = "Gyms"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} (Owner: {self.owner_user.email})"

    def get_settings(self) -> "GymSetting":
        """
        Retrieves gym settings instance or auto-creates default configuration.
        Caches instance in reverse relation if available.
        """
        if hasattr(self, "settings"):
            return self.settings
        settings_obj, _ = GymSetting.objects.get_or_create(gym=self)
        return settings_obj


class GymLocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="locations",
    )
    address = models.TextField()
    latitude = models.DecimalField(max_digits=10, decimal_places=8)
    longitude = models.DecimalField(max_digits=11, decimal_places=8)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=30, blank=True, null=True)
    is_primary = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "gym_locations"
        verbose_name = "Gym Location"
        verbose_name_plural = "Gym Locations"
        indexes = [
            models.Index(fields=["gym", "is_primary"]),
        ]

    def __str__(self):
        return f"Location of {self.gym.name}: {self.address}"


class GymOpeningHours(models.Model):
    DAYS_OF_WEEK = (
        (0, "Sunday"),
        (1, "Monday"),
        (2, "Tuesday"),
        (3, "Wednesday"),
        (4, "Thursday"),
        (5, "Friday"),
        (6, "Saturday"),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="opening_hours",
    )
    day_of_week = models.IntegerField(choices=DAYS_OF_WEEK)
    start_time = models.TimeField(blank=True, null=True)
    end_time = models.TimeField(blank=True, null=True)
    is_closed = models.BooleanField(default=False)

    class Meta:
        db_table = "gym_opening_hours"
        verbose_name = "Gym Opening Hour"
        verbose_name_plural = "Gym Opening Hours"
        unique_together = (("gym", "day_of_week"),)
        ordering = ["day_of_week"]

    def __str__(self):
        day_name = dict(self.DAYS_OF_WEEK).get(self.day_of_week, str(self.day_of_week))
        if self.is_closed:
            return f"{self.gym.name} - {day_name}: Closed"
        return f"{self.gym.name} - {day_name}: {self.start_time} - {self.end_time}"


class GymGallery(OptimizedMediaMixin, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="gallery_items",
    )
    media_url = models.CharField(max_length=1000)
    media_type = models.CharField(
        max_length=20,
        choices=MediaTypeEnum.choices,
        default=MediaTypeEnum.PICTURE,
    )
    category = models.CharField(
        max_length=50,
        choices=GalleryCategoryEnum.choices,
        default=GalleryCategoryEnum.GENERAL,
    )
    caption = models.CharField(max_length=200, blank=True, null=True)
    order_index = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "gym_gallery"
        verbose_name = "Gym Gallery Item"
        verbose_name_plural = "Gym Gallery Items"
        ordering = ["order_index", "-created_at"]
        indexes = [
            models.Index(fields=["gym", "order_index"]),
            models.Index(fields=["gym", "category"]),
        ]

    def __str__(self):
        return f"{self.gym.name} Gallery ({self.category}) - #{self.order_index} [{self.processing_status}]"


class GymSetting(models.Model):
    """
    Configuration and administrative settings for a gym entity.
    Encompasses Display Preferences, Alert Subscriptions, Audience Visibility Rules,
    and Gym Lifecycle (Access & Control) States.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.OneToOneField(
        Gym,
        on_delete=models.CASCADE,
        related_name="settings",
    )

    # --- Preference -> Display ---
    language = models.CharField(
        max_length=20,
        default="en",
        help_text="Display language (e.g. en, bn)."
    )
    video_autoplay = models.BooleanField(
        default=True,
        help_text="Video Autoplay (ON/OFF)."
    )
    dark_mode = models.BooleanField(
        default=False,
        help_text="Dark Mode (ON/OFF)."
    )

    # --- Privacy and Sharing -> Alerts ---
    admin_logs_alerts = models.BooleanField(
        default=True,
        help_text="Admin Logs alert notifications enabled (ON/OFF)."
    )
    issues_alerts = models.BooleanField(
        default=True,
        help_text="Issues alert notifications enabled (ON/OFF)."
    )

    # --- Privacy and Sharing -> Audience ---
    who_can_message = models.CharField(
        max_length=50,
        choices=AudienceMessagingEnum.choices,
        default=AudienceMessagingEnum.EVERYONE,
        help_text="Who can send you messages? (Everyone, Followers & Members, Members only)"
    )
    who_can_send_joining_request = models.CharField(
        max_length=50,
        choices=AudienceJoiningRequestEnum.choices,
        default=AudienceJoiningRequestEnum.EVERYONE,
        help_text="Who can send you a Member joining request? (Everyone, No one)"
    )
    who_can_see_members = models.CharField(
        max_length=50,
        choices=AudienceMembersVisibilityEnum.choices,
        default=AudienceMembersVisibilityEnum.EVERYONE,
        help_text="Who can see your Gym’s Members? (Everyone, Only Members)"
    )
    who_can_see_following = models.CharField(
        max_length=50,
        choices=AudienceFollowingVisibilityEnum.choices,
        default=AudienceFollowingVisibilityEnum.EVERYONE,
        help_text="Who can see the people and pages you follow? (Everyone, Only members, Private)"
    )
    posts_age_restriction = models.CharField(
        max_length=50,
        choices=PostsAgeRestrictionEnum.choices,
        default=PostsAgeRestrictionEnum.ANY_AGE,
        help_text="Age restriction for your Gym’s posts (Any age, 17+, 18+, 19+, 20+)"
    )

    # --- Visibility -> Access & Control ---
    is_deactivated = models.BooleanField(
        default=False,
        help_text="Whether the gym is deactivated."
    )
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the gym was deactivated."
    )
    is_published = models.BooleanField(
        default=True,
        help_text="Whether the gym is published."
    )
    unpublished_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the gym was unpublished."
    )
    is_deleted = models.BooleanField(
        default=False,
        help_text="Soft-delete flag for gym."
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when the gym was deleted."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "gym_settings"
        verbose_name = "Gym Setting"
        verbose_name_plural = "Gym Settings"

    def __str__(self):
        return f"Settings of {self.gym.name}"

    def deactivate(self) -> None:
        """Transitions gym state to deactivated and records timestamp."""
        self.is_deactivated = True
        self.deactivated_at = timezone.now()

    def reactivate(self) -> None:
        """Reactivates gym and resets deactivated timestamp."""
        self.is_deactivated = False
        self.deactivated_at = None

    def unpublish(self) -> None:
        """Unpublishes gym from discovery feed and records timestamp."""
        self.is_published = False
        self.unpublished_at = timezone.now()

    def publish(self) -> None:
        """Publishes gym to discovery feed and resets unpublished timestamp."""
        self.is_published = True
        self.unpublished_at = None

    def soft_delete(self) -> None:
        """Marks gym as soft-deleted and records timestamp."""
        self.is_deleted = True
        self.deleted_at = timezone.now()

    def restore(self) -> None:
        """Restores soft-deleted gym and resets deleted timestamp."""
        self.is_deleted = False
        self.deleted_at = None


class GymBlockedUser(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="blocked_users",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocked_by_gyms",
    )
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gym_blocks_initiated",
    )
    reason = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gym_blocked_users"
        verbose_name = "Gym Blocked User"
        verbose_name_plural = "Gym Blocked Users"
        unique_together = (("gym", "user"),)
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["gym", "user"]),
            models.Index(fields=["gym", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.gym.name} blocked {self.user.email}"


class GymFollow(models.Model):
    """
    Represents an intentional follow relationship from a user to a gym.
    Gym members automatically follow their connected gyms by default, and can unfollow later.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="followed_gyms",
    )
    gym = models.ForeignKey(
        Gym,
        on_delete=models.CASCADE,
        related_name="followers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "gym_follows"
        verbose_name = "Gym Follow"
        verbose_name_plural = "Gym Follows"
        unique_together = (("user", "gym"),)
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="idx_gfollow_usr_created"),
            models.Index(fields=["gym", "-created_at"], name="idx_gfollow_gym_created"),
        ]

    def __str__(self):
        return f"{self.user.email} follows {self.gym.name}"
