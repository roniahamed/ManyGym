from django.contrib import admin
from apps.notifications.models import DeviceToken, Notification


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "device_id", "is_active", "last_seen_at", "created_at")
    list_filter = ("platform", "is_active")
    search_fields = ("user__email", "token", "device_id", "device_name")
    readonly_fields = ("created_at", "updated_at", "last_seen_at")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "notification_type", "title", "is_read", "created_at")
    list_filter = ("notification_type", "is_read", "created_at")
    search_fields = ("recipient__email", "title", "body", "target_id")
    readonly_fields = ("created_at", "updated_at", "read_at")
