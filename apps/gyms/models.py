import uuid
from django.db import models
from django.conf import settings
from common.enums import (
    GymTypeEnum,
    GymGenderRequired,
    GalleryCategoryEnum,
    MediaTypeEnum,
)


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


class GymGallery(models.Model):
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

    class Meta:
        db_table = "gym_gallery"
        verbose_name = "Gym Gallery Item"
        verbose_name_plural = "Gym Gallery Items"
        ordering = ["order_index", "-created_at"]

    def __str__(self):
        return f"{self.gym.name} Gallery ({self.category}) - #{self.order_index}"
