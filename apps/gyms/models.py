import uuid
from django.db import models
from django.conf import settings
from common.enums import GymTypeEnum, GymGenderRequired


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
