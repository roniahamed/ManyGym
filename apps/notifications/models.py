import uuid
from django.conf import settings
from django.db import models
from common.enums import DevicePlatformEnum, NotificationTypeEnum


class DeviceToken(models.Model):
    """
    Stores FCM registration tokens for client mobile and web devices.
    Used for dispatching push notifications via Firebase Cloud Messaging.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_tokens",
        db_index=True,
    )
    token = models.CharField(max_length=500, unique=True, db_index=True)
    device_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    device_name = models.CharField(max_length=150, blank=True, default="")
    platform = models.CharField(
        max_length=20,
        choices=DevicePlatformEnum.choices,
        default=DevicePlatformEnum.ANDROID,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notification_device_tokens"
        verbose_name = "Device Token"
        verbose_name_plural = "Device Tokens"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "is_active"], name="idx_devtok_user_active"),
            models.Index(fields=["device_id", "user"], name="idx_devtok_dev_user"),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.platform} ({self.device_id or 'unknown'})"


class Notification(models.Model):
    """
    Persistent in-app notification record for non-message events
    (reactions, comments, replies, member requests, gym invites, follows, system alerts).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )
    gym = models.ForeignKey(
        "gyms.Gym",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
        db_index=True,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="acted_notifications",
    )
    actor_gym = models.ForeignKey(
        "gyms.Gym",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="gym_acted_notifications",
    )
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationTypeEnum.choices,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    target_type = models.CharField(max_length=50, blank=True, default="")
    target_id = models.CharField(max_length=100, blank=True, default="")
    action_url = models.CharField(max_length=500, blank=True, default="")
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications"
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"], name="idx_notif_rcpt_read_created"),
            models.Index(fields=["recipient", "-created_at"], name="idx_notif_rcpt_created"),
            models.Index(fields=["gym", "is_read", "-created_at"], name="idx_notif_gym_read_created"),
            models.Index(fields=["notification_type", "-created_at"], name="idx_notif_type_created"),
        ]

    def __str__(self):
        return f"[{self.notification_type}] {self.recipient.email}: {self.title}"
