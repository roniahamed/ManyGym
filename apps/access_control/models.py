import uuid
from django.db import models
from django.conf import settings
from common.enums import StaffStatus


class Permission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.CharField(max_length=100, db_index=True)
    scope_code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "permissions"
        verbose_name = "Permission"
        verbose_name_plural = "Permissions"
        ordering = ["topic", "name"]

    def __str__(self):
        return f"[{self.topic}] {self.scope_code}"


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="roles",
    )
    name = models.CharField(max_length=100)
    slug = models.CharField(max_length=100, db_index=True)
    is_custom = models.BooleanField(default=False)
    description = models.TextField(blank=True, null=True)
    permissions = models.ManyToManyField(
        Permission,
        through="RolePermission",
        related_name="roles",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "roles"
        verbose_name = "Role"
        verbose_name_plural = "Roles"
        ordering = ["name"]

    def __str__(self):
        scope_str = f"Gym: {self.gym.name}" if self.gym else "Global"
        return f"{self.name} ({scope_str})"


class RolePermission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="permission_roles",
    )

    class Meta:
        db_table = "role_permissions"
        unique_together = (("role", "permission"),)

    def __str__(self):
        return f"{self.role.name} -> {self.permission.scope_code}"


class GymStaffAssignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gym_staff_assignments",
    )
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="staff_assignments",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="staff_assignments",
    )
    status = models.CharField(
        max_length=20,
        choices=StaffStatus.choices,
        default=StaffStatus.ACTIVE,
    )
    invited_at = models.DateTimeField(auto_now_add=True)
    joined_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "gym_staff_assignments"
        unique_together = (("user", "gym", "role"),)
        ordering = ["-invited_at"]
        indexes = [
            models.Index(fields=["gym", "status"]),
            models.Index(fields=["user", "gym", "status"]),
        ]

    def __str__(self):
        return f"{self.user.email} as {self.role.name} at {self.gym.name} ({self.status})"
