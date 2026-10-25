import uuid
from django.db import models
from django.conf import settings
from common.enums import TokenContextType


class AuthToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="auth_tokens",
    )
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="auth_tokens",
    )
    token_hash = models.CharField(max_length=255, unique=True, db_index=True)
    context_type = models.CharField(
        max_length=20,
        choices=TokenContextType.choices,
        default=TokenContextType.PERSONAL,
    )
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_tokens"
        verbose_name = "Auth Token"
        verbose_name_plural = "Auth Tokens"
        ordering = ["-created_at"]

    def __str__(self):
        ctx = f"Gym: {self.gym.name}" if self.gym else "Personal"
        return f"Token for {self.user.email} [{ctx}]"
