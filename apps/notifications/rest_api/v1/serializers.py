from rest_framework import serializers

from apps.gyms.models import Gym
from apps.notifications.models import DeviceToken, Notification
from apps.users.models import User
from common.enums import DevicePlatformEnum, NotificationTypeEnum
from common.serializers import StrictCharField


class NotificationFilterSerializer(serializers.Serializer):
    """
    Validates query parameters for listing in-app notifications.
    Ensures type safety for boolean filters and enum choices.
    """
    is_read = serializers.BooleanField(
        required=False,
        default=None,
        allow_null=True,
        help_text="Filter by read status (true or false).",
    )
    notification_type = serializers.ChoiceField(
        choices=NotificationTypeEnum.choices,
        required=False,
        default=None,
        allow_blank=True,
        allow_null=True,
        help_text="Filter by notification type.",
    )
    type = serializers.ChoiceField(
        choices=NotificationTypeEnum.choices,
        required=False,
        default=None,
        allow_blank=True,
        allow_null=True,
        help_text="Alias for notification_type.",
    )

    def validate(self, attrs):
        if attrs.get("type") and not attrs.get("notification_type"):
            attrs["notification_type"] = attrs["type"]
        return attrs


class DeviceTokenRegisterSerializer(serializers.Serializer):
    """Payload for registering or updating a client FCM device token."""
    token = StrictCharField(
        max_length=500,
        help_text="Unique FCM registration token string.",
    )
    device_id = StrictCharField(
        max_length=120,
        required=False,
        allow_blank=True,
        default="",
        help_text="Client hardware or UUID identifier for the device.",
    )
    device_name = StrictCharField(
        max_length=150,
        required=False,
        allow_blank=True,
        default="",
        help_text="Human-readable device model name (e.g. 'iPhone 15 Pro', 'Pixel 8').",
    )
    platform = serializers.ChoiceField(
        choices=DevicePlatformEnum.choices,
        default=DevicePlatformEnum.ANDROID,
        help_text="Client operating platform (android, ios, web).",
    )


class DeviceTokenUnregisterSerializer(serializers.Serializer):
    """Payload for deactivating an FCM device token."""
    token = StrictCharField(
        max_length=500,
        help_text="FCM registration token to unregister.",
    )


class DeviceTokenDetailSerializer(serializers.ModelSerializer):
    """Representation of an active or inactive client device token."""
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
        read_only_fields = fields


class NotificationActorSerializer(serializers.Serializer):
    """Representation of the user actor who triggered the notification."""
    id = serializers.UUIDField()
    email = serializers.EmailField()
    full_name = serializers.SerializerMethodField()
    profile_photo = serializers.SerializerMethodField()

    def get_full_name(self, obj: User) -> str:
        profile = getattr(obj, "profile", None)
        if profile:
            name = f"{profile.first_name} {profile.last_name}".strip()
            if name:
                return name
        first_name = getattr(obj, "first_name", "") or ""
        last_name = getattr(obj, "last_name", "") or ""
        combined = f"{first_name} {last_name}".strip()
        return combined or getattr(obj, "email", "")

    def get_profile_photo(self, obj: User) -> str:
        profile = getattr(obj, "profile", None)
        if profile and profile.profile_photo:
            try:
                return profile.profile_photo.url
            except Exception:
                return ""
        return ""


class NotificationGymSerializer(serializers.Serializer):
    """Representation of a gym entity associated with the notification."""
    id = serializers.UUIDField()
    name = serializers.CharField()
    logo_url = serializers.SerializerMethodField()

    def get_logo_url(self, obj: Gym) -> str:
        logo = getattr(obj, "logo", None)
        if logo:
            try:
                return logo.url
            except Exception:
                return ""
        return ""


class NotificationDetailSerializer(serializers.ModelSerializer):
    """Complete detail representation of an in-app notification record."""
    actor = NotificationActorSerializer(read_only=True, allow_null=True)
    actor_gym = NotificationGymSerializer(read_only=True, allow_null=True)
    gym = NotificationGymSerializer(read_only=True, allow_null=True)

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
        read_only_fields = fields


class UnreadCountResponseSerializer(serializers.Serializer):
    """Response payload returning count of unread notifications."""
    unread_count = serializers.IntegerField(help_text="Total count of unread in-app notifications.")


class MarkAllReadResponseSerializer(serializers.Serializer):
    """Response payload confirming mark all read action."""
    marked_read_count = serializers.IntegerField(help_text="Number of notifications marked as read.")
