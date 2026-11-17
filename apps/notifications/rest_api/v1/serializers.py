from rest_framework import serializers

from apps.notifications.models import DeviceToken, Notification
from apps.users.models import User
from apps.gyms.models import Gym
from common.enums import DevicePlatformEnum, NotificationTypeEnum
from common.serializers import StrictCharField


class DeviceTokenRegisterSerializer(serializers.Serializer):
    """Payload for registering/updating client FCM device token."""
    token = StrictCharField(max_length=500, help_text="Unique FCM registration token string.")
    device_id = StrictCharField(
        max_length=120,
        required=False,
        allow_blank=True,
        default="",
        help_text="Client hardware/UUID identifier for device.",
    )
    device_name = StrictCharField(
        max_length=150,
        required=False,
        allow_blank=True,
        default="",
        help_text="Human-readable device name (e.g. 'iPhone 15', 'Pixel 8').",
    )
    platform = serializers.ChoiceField(
        choices=DevicePlatformEnum.choices,
        default=DevicePlatformEnum.ANDROID,
        help_text="Client OS platform (android, ios, web).",
    )


class DeviceTokenUnregisterSerializer(serializers.Serializer):
    """Payload for unregistering an FCM device token."""
    token = StrictCharField(max_length=500, help_text="FCM registration token to unregister.")


class DeviceTokenDetailSerializer(serializers.ModelSerializer):
    """Representation of a registered client device token."""
    class Meta:
        model = DeviceToken
        fields = [
            "id",
            "device_id",
            "device_name",
            "platform",
            "is_active",
            "last_seen_at",
            "created_at",
        ]


class NotificationActorSerializer(serializers.Serializer):
    """Minimal representation of the user triggering the notification."""
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.SerializerMethodField()
    profile_photo = serializers.SerializerMethodField()

    def get_full_name(self, obj: User) -> str:
        profile = getattr(obj, "profile", None)
        if profile and (profile.first_name or profile.last_name):
            return f"{profile.first_name} {profile.last_name}".strip()
        return obj.email

    def get_profile_photo(self, obj: User) -> str:
        profile = getattr(obj, "profile", None)
        if profile and profile.profile_photo:
            try:
                return profile.profile_photo.url
            except Exception:
                return ""
        return ""


class NotificationGymSerializer(serializers.Serializer):
    """Minimal representation of a gym associated with the notification."""
    id = serializers.UUIDField()
    name = serializers.CharField()
    logo_url = serializers.SerializerMethodField()

    def get_logo_url(self, obj: Gym) -> str:
        if getattr(obj, "logo", None):
            try:
                return obj.logo.url
            except Exception:
                return ""
        return ""


class NotificationDetailSerializer(serializers.ModelSerializer):
    """Complete detail representation of an in-app notification."""
    actor = NotificationActorSerializer(read_only=True)
    actor_gym = NotificationGymSerializer(read_only=True)
    gym = NotificationGymSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "notification_type",
            "title",
            "body",
            "data",
            "target_type",
            "target_id",
            "action_url",
            "is_read",
            "read_at",
            "created_at",
            "actor",
            "actor_gym",
            "gym",
        ]


class UnreadCountResponseSerializer(serializers.Serializer):
    """Response payload returning count of unread notifications."""
    unread_count = serializers.IntegerField(help_text="Total count of unread notifications.")


class MarkAllReadResponseSerializer(serializers.Serializer):
    """Response payload confirming mark all read action."""
    marked_read_count = serializers.IntegerField(help_text="Number of notifications marked as read.")
