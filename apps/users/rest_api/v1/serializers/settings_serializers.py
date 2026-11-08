from rest_framework import serializers
from apps.users.models import User, UserSetting, UserBlockedUser, UserDevice
from common.serializers import StrictCharField, StrictBooleanField, StrictUUIDField, StrictEmailField
from common.enums import UserAudienceMessagingEnum, UserAudienceFollowEnum, UserAudienceVisibilityEnum


class UserSettingSerializer(serializers.ModelSerializer):
    """
    Read-only presentation serializer for comprehensive User Profile & Privacy Settings.
    """
    user_id = serializers.UUIDField(read_only=True)
    is_private = serializers.BooleanField(source="user.profile.is_private", read_only=True)
    who_can_follow_me = serializers.CharField(source="who_can_follow", read_only=True)

    class Meta:
        model = UserSetting
        fields = [
            "id",
            "user_id",
            "language",
            "video_autoplay",
            "dark_mode",
            "two_factor_enabled",
            "is_private",
            "require_follow_approval",
            "who_can_follow",
            "who_can_follow_me",
            "who_can_message",
            "who_can_see_followers",
            "who_can_see_following",
            "is_deactivated",
            "deactivated_at",
            "is_deleted",
            "deleted_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "user_id",
            "is_private",
            "who_can_follow_me",
            "two_factor_enabled",
            "deactivated_at",
            "deleted_at",
            "created_at",
            "updated_at",
        ]


class UserSettingUpdateSerializer(serializers.Serializer):
    """
    Validation and deserialization serializer for updating User Settings.
    """
    language = StrictCharField(required=False, max_length=20)
    video_autoplay = StrictBooleanField(required=False, help_text="Video Autoplay (ON/OFF).")
    dark_mode = StrictBooleanField(required=False)
    is_private = StrictBooleanField(required=False, help_text="Toggle private profile state.")
    require_follow_approval = StrictBooleanField(required=False, help_text="Require approval before someone can follow you.")

    who_can_follow = serializers.ChoiceField(
        choices=UserAudienceFollowEnum.choices,
        required=False,
        help_text="Who can follow me: 'everyone', 'friends_of_friends'",
    )
    who_can_follow_me = serializers.ChoiceField(
        choices=UserAudienceFollowEnum.choices,
        required=False,
        help_text="Alias for who_can_follow: 'everyone', 'friends_of_friends'",
    )
    who_can_message = serializers.ChoiceField(
        choices=UserAudienceMessagingEnum.choices,
        required=False,
        help_text="Controls messaging permission: 'everyone', 'followers', 'no_one'",
    )
    who_can_see_followers = serializers.ChoiceField(
        choices=UserAudienceVisibilityEnum.choices,
        required=False,
        help_text="Visibility of followers list: 'everyone', 'followers', 'private'",
    )
    who_can_see_following = serializers.ChoiceField(
        choices=UserAudienceVisibilityEnum.choices,
        required=False,
        help_text="Visibility of followed pages/users: 'everyone', 'followers', 'private'",
    )

    def validate(self, attrs):
        if "who_can_follow_me" in attrs and "who_can_follow" not in attrs:
            attrs["who_can_follow"] = attrs["who_can_follow_me"]
        return attrs

    def validate_language(self, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Language code cannot be empty.")
        return cleaned


class UserBlockedUserSerializer(serializers.ModelSerializer):
    """
    Serializer representing a blocked user record for a user profile.
    """
    user_id = serializers.UUIDField(source="blocked_user.id", read_only=True)
    email = serializers.EmailField(source="blocked_user.email", read_only=True)
    first_name = serializers.CharField(source="blocked_user.first_name", read_only=True)
    last_name = serializers.CharField(source="blocked_user.last_name", read_only=True)
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = UserBlockedUser
        fields = [
            "id",
            "user_id",
            "email",
            "first_name",
            "last_name",
            "avatar_url",
            "reason",
            "created_at",
        ]
        read_only_fields = fields

    def get_avatar_url(self, obj: UserBlockedUser) -> str | None:
        if hasattr(obj.blocked_user, "profile") and obj.blocked_user.profile:
            return obj.blocked_user.profile.avatar_url
        return None


class UserBlockUserCreateSerializer(serializers.Serializer):
    """
    Request serializer for blocking another user.
    """
    user_id = StrictUUIDField(required=True, help_text="Valid UUID string of the user to block.")
    reason = StrictCharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Optional rationale for blocking.",
    )

    def validate_reason(self, value: str | None) -> str:
        if value is None:
            return ""
        return value.strip()


class UserFollowerBlockCreateSerializer(serializers.Serializer):
    """
    Request payload serializer for blocking directly from the followers list.
    """
    reason = StrictCharField(
        required=False,
        allow_blank=True,
        default="Blocked from followers list",
        max_length=255,
        help_text="Optional rationale for blocking from followers list.",
    )

    def validate_reason(self, value: str | None) -> str:
        if value is None:
            return "Blocked from followers list"
        cleaned = value.strip()
        return cleaned if cleaned else "Blocked from followers list"


class UserSearchToBlockSerializer(serializers.ModelSerializer):
    """
    Lightweight projection serializer for searching active users to block.
    """
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "avatar_url",
        ]
        read_only_fields = fields

    def get_avatar_url(self, obj: User) -> str | None:
        if hasattr(obj, "profile") and obj.profile:
            return obj.profile.avatar_url
        return None


class UserAccessControlActionSerializer(serializers.Serializer):
    """
    Request payload serializer for user profile lifecycle state transitions.
    For 'delete' action, requires account password and confirmation keyword 'delete'.
    """
    action = serializers.ChoiceField(
        choices=[
            "deactivate",
            "reactivate",
            "delete",
            "restore",
        ],
        required=True,
        help_text="Lifecycle state transition action.",
    )
    password = serializers.CharField(
        required=False,
        write_only=True,
        help_text="Account password required for delete or restore confirmation.",
    )
    confirmation = serializers.CharField(
        required=False,
        help_text="Confirmation keyword ('delete') required for delete confirmation.",
    )

    def validate(self, attrs):
        action = attrs.get("action")
        if action == "delete":
            password = attrs.get("password")
            confirmation = attrs.get("confirmation")
            if not password:
                raise serializers.ValidationError({"password": "Password is required to delete account."})
            if not confirmation:
                raise serializers.ValidationError({"confirmation": "Confirmation text is required. Please type 'delete' to confirm."})
            if confirmation.strip().lower() != "delete":
                raise serializers.ValidationError({"confirmation": "Please type 'delete' to confirm deletion."})
        elif action == "restore":
            password = attrs.get("password")
            if not password:
                raise serializers.ValidationError({"password": "Password is required to restore account."})
        return attrs


# ==============================================================================
# LOGIN AND SECURITY SERIALIZERS
# ==============================================================================

class UserContactInfoSerializer(serializers.Serializer):
    """
    Representation of User Contact Info in Login and Security.
    Primary email is strictly read-only.
    """
    primary_email = serializers.EmailField(read_only=True)
    secondary_email = serializers.EmailField(allow_null=True, required=False)
    phone = serializers.CharField(allow_null=True, required=False, max_length=50)


class UserContactInfoUpdateSerializer(serializers.Serializer):
    """
    Validation serializer for updating User Contact Info.
    Primary email cannot be updated or deleted.
    """
    primary_email = serializers.CharField(required=False)
    email = serializers.CharField(required=False)
    secondary_email = StrictEmailField(required=False, allow_null=True, allow_blank=True)
    phone = StrictCharField(required=False, allow_null=True, allow_blank=True, max_length=50)

    def validate(self, attrs):
        if "primary_email" in self.initial_data or "email" in self.initial_data:
            raise serializers.ValidationError({
                "primary_email": "Primary email cannot be updated or deleted."
            })
        return attrs

    def validate_secondary_email(self, value):
        if value is not None and value != "":
            if "\x00" in value:
                raise serializers.ValidationError("Null characters are not allowed in secondary email.")
            cleaned = value.strip().lower()
            request = self.context.get("request")
            if request and hasattr(request, "user") and request.user.email.lower() == cleaned:
                raise serializers.ValidationError("Secondary email cannot be the same as primary email.")
            return cleaned
        return None

    def validate_phone(self, value):
        if value is not None and value != "":
            if "\x00" in value:
                raise serializers.ValidationError("Null characters are not allowed in phone number.")
            return value.strip()
        return None


class UserTwoFactorToggleSerializer(serializers.Serializer):
    """
    Validation serializer for toggling Two Factor Authentication state.
    """
    two_factor_enabled = StrictBooleanField(
        required=True,
        help_text="Two Factor Authentication toggle (true=ON, false=OFF).",
    )


class UserDeviceSerializer(serializers.ModelSerializer):
    """
    Projection serializer for logged-in devices (max 5 per user).
    """
    is_current_device = serializers.SerializerMethodField()

    class Meta:
        model = UserDevice
        fields = [
            "id",
            "device_id",
            "device_name",
            "ip_address",
            "user_agent",
            "last_login",
            "created_at",
            "is_current_device",
        ]
        read_only_fields = fields

    def get_is_current_device(self, obj: UserDevice) -> bool:
        request = self.context.get("request")
        if not request:
            return False
        req_dev_id = request.headers.get("X-Device-Id")
        if req_dev_id and req_dev_id == obj.device_id:
            return True
        return False


class UserSecuritySettingsSerializer(serializers.Serializer):
    """
    High-level dashboard serializer for Login and Security.
    """
    contact_info = UserContactInfoSerializer()
    two_factor_enabled = serializers.BooleanField()
    logged_in_devices_count = serializers.IntegerField()
    max_devices = serializers.IntegerField(default=5)
    account_status = serializers.DictField()


class Verify2FASerializer(serializers.Serializer):
    """
    Request payload serializer for verifying Two Factor Authentication OTP.
    """
    email = StrictEmailField(required=True)
    otp_code = StrictCharField(
        min_length=6,
        max_length=6,
        required=True,
        help_text="6-digit numeric verification code.",
    )
    device_id = StrictCharField(required=False, allow_blank=True, max_length=100)
    device_name = StrictCharField(required=False, allow_blank=True, max_length=150)

    def validate_otp_code(self, value):
        cleaned = value.strip()
        if not cleaned.isdigit() or len(cleaned) != 6:
            raise serializers.ValidationError("OTP code must be a 6-digit numeric string.")
        return cleaned


class Resend2FASerializer(serializers.Serializer):
    """
    Request payload serializer for requesting a new 2FA code via fallback or specific channel.
    """
    email = StrictEmailField(required=True)
    channel = serializers.ChoiceField(
        choices=["primary_email", "secondary_email", "phone_sms", "auto"],
        required=False,
        default="auto",
    )


