from django.urls import path
from apps.notifications.rest_api.v1.views import (
    DeviceTokenListView,
    DeviceTokenUnregisterView,
    NotificationDetailView,
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationUnreadCountView,
)

urlpatterns = [
    # In-app notifications
    path("", NotificationListView.as_view(), name="notification-list"),
    path("unread-count/", NotificationUnreadCountView.as_view(), name="notification-unread-count"),
    path("mark-all-read/", NotificationMarkAllReadView.as_view(), name="notification-mark-all-read"),
    path("<uuid:notification_id>/", NotificationDetailView.as_view(), name="notification-detail"),
    path("<uuid:notification_id>/read/", NotificationMarkReadView.as_view(), name="notification-mark-read"),

    # Device registration for FCM push notifications
    path("devices/", DeviceTokenListView.as_view(), name="device-token-list-register"),
    path("devices/unregister/", DeviceTokenUnregisterView.as_view(), name="device-token-unregister"),
]
