from django.urls import path
from apps.notifications.rest_api.v1.views import (
    DeviceTokenListView,
    DeviceTokenUnregisterView,
    NotificationBatchMarkReadView,
    NotificationClearReadView,
    NotificationDetailView,
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationUnreadCountView,
)

app_name = "notifications"

urlpatterns = [
    # In-app notifications list & filters
    path("", NotificationListView.as_view(), name="notification-list"),
    path("unread-count/", NotificationUnreadCountView.as_view(), name="notification-unread-count"),

    # Bulk & batch operations
    path("mark-all-read/", NotificationMarkAllReadView.as_view(), name="notification-mark-all-read"),
    path("batch-read/", NotificationBatchMarkReadView.as_view(), name="notification-batch-mark-read"),
    path("clear-read/", NotificationClearReadView.as_view(), name="notification-clear-read"),

    # Single notification operations
    path("<uuid:notification_id>/", NotificationDetailView.as_view(), name="notification-detail"),
    path("<uuid:notification_id>/read/", NotificationMarkReadView.as_view(), name="notification-mark-read"),
    path("<uuid:notification_id>/mark-read/", NotificationMarkReadView.as_view(), name="notification-mark-read-alias"),

    # Device registration for FCM push notifications
    path("devices/", DeviceTokenListView.as_view(), name="device-token-list-register"),
    path("devices/unregister/", DeviceTokenUnregisterView.as_view(), name="device-token-unregister"),
]
