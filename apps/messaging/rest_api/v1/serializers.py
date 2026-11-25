"""
Serializers for End-to-End Encrypted (E2EE) Messaging.
Provides input validation, payload shaping, and response representations.
"""

import uuid
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.messaging.models import (
    Conversation,
    ConversationParticipant,
    EncryptedMessage,
    UserE2EEBackup,
)
from common.enums import (
    ConversationTypeEnum,
    MessageSenderTypeEnum,
)


class StrictCharField(serializers.CharField):
    """
    Strict CharField preventing type coercion / juggling.
    Rejects integers, booleans, floats, lists, and dicts where strings are expected.
    """
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError("Expected a string value, received unexpected data type.")
        return super().to_internal_value(data)


class StrictUUIDField(serializers.UUIDField):
    """
    Strict UUIDField preventing type coercion / juggling.
    Requires string or uuid.UUID input and rejects raw integers, booleans, or lists.
    """
    def to_internal_value(self, data):
        if not isinstance(data, (str, uuid.UUID)):
            raise serializers.ValidationError("Expected a valid UUID string, received unexpected data type.")
        return super().to_internal_value(data)


class UserDeviceKeyRegisterSerializer(serializers.Serializer):
    device_id = StrictCharField(max_length=100, allow_blank=False)
    device_name = StrictCharField(max_length=150, required=False, allow_blank=True, default="")
    identity_key = StrictCharField(allow_blank=False)
    signed_prekey = StrictCharField(allow_blank=False)
    signed_prekey_signature = StrictCharField(required=False, allow_blank=True, default="")
    one_time_prekeys = serializers.ListField(
        child=StrictCharField(allow_blank=False),
        required=False,
        default=list,
    )


class GymDeviceKeyRegisterSerializer(serializers.Serializer):
    gym_id = StrictUUIDField()
    device_id = StrictCharField(max_length=100, allow_blank=False)
    device_name = StrictCharField(max_length=150, required=False, allow_blank=True, default="")
    identity_key = StrictCharField(allow_blank=False)
    signed_prekey = StrictCharField(allow_blank=False)
    signed_prekey_signature = StrictCharField(required=False, allow_blank=True, default="")
    one_time_prekeys = serializers.ListField(
        child=StrictCharField(allow_blank=False),
        required=False,
        default=list,
    )


class PublicKeyBundleSerializer(serializers.Serializer):
    device_id = serializers.CharField()
    device_name = serializers.CharField()
    algorithm = serializers.CharField()
    identity_key = serializers.CharField()
    signed_prekey = serializers.CharField()
    signed_prekey_signature = serializers.CharField()
    one_time_prekeys = serializers.ListField(child=serializers.CharField())


class ConversationParticipantSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_full_name = serializers.SerializerMethodField()
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    profile_id = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    gym_name = serializers.CharField(source="gym.name", read_only=True)

    class Meta:
        model = ConversationParticipant
        fields = [
            "id",
            "participant_type",
            "user",
            "user_id",
            "profile_id",
            "user_email",
            "user_full_name",
            "avatar_url",
            "gym",
            "gym_name",
            "unread_count",
            "last_read_at",
            "is_muted",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_user_full_name(self, obj):
        if obj.user:
            return f"{obj.user.first_name} {obj.user.last_name}".strip()
        return None

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_profile_id(self, obj):
        if obj.user:
            profile = getattr(obj.user, "profile", None)
            return profile.id if profile else None
        return None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_avatar_url(self, obj):
        if obj.user:
            profile = getattr(obj.user, "profile", None)
            return profile.avatar_url if profile else None
        return None


class ConversationListSerializer(serializers.ModelSerializer):
    participants = ConversationParticipantSerializer(many=True, read_only=True)
    other_party = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "conversation_type",
            "user_a",
            "user_b",
            "gym_a",
            "gym_b",
            "participants",
            "other_party",
            "last_message_at",
            "last_message_preview",
            "created_at",
        ]

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_other_party(self, obj):
        """Helper for frontend UI displaying the other entity's name and type."""
        request = self.context.get("request")
        user = getattr(request, "user", None)
        gym = self.context.get("gym") or getattr(request, "gym", None)

        if obj.conversation_type == ConversationTypeEnum.USER_TO_USER and user:
            other_user = obj.user_b if obj.user_a_id == user.id else obj.user_a
            if other_user:
                profile = getattr(other_user, "profile", None)
                return {
                    "type": "user",
                    "id": str(other_user.id),
                    "user_id": str(other_user.id),
                    "profile_id": str(profile.id) if profile else None,
                    "avatar_url": profile.avatar_url if profile else None,
                    "name": f"{other_user.first_name} {other_user.last_name}".strip(),
                    "email": other_user.email,
                }
        elif obj.conversation_type == ConversationTypeEnum.USER_TO_GYM:
            if gym and obj.gym_a_id == gym.id:
                # Gym viewing user
                profile = getattr(obj.user_a, "profile", None)
                return {
                    "type": "user",
                    "id": str(obj.user_a.id),
                    "user_id": str(obj.user_a.id),
                    "profile_id": str(profile.id) if profile else None,
                    "avatar_url": profile.avatar_url if profile else None,
                    "name": f"{obj.user_a.first_name} {obj.user_a.last_name}".strip(),
                    "email": obj.user_a.email,
                }
            else:
                # User viewing gym
                return {
                    "type": "gym",
                    "id": str(obj.gym_a.id),
                    "name": obj.gym_a.name,
                    "profile_picture_url": obj.gym_a.profile_picture_url,
                }
        elif obj.conversation_type == ConversationTypeEnum.GYM_TO_GYM and gym:
            other_gym = obj.gym_b if obj.gym_a_id == gym.id else obj.gym_a
            if other_gym:
                return {
                    "type": "gym",
                    "id": str(other_gym.id),
                    "name": other_gym.name,
                    "profile_picture_url": other_gym.profile_picture_url,
                }
        return None


class ConversationCreateSerializer(serializers.Serializer):
    conversation_type = StrictCharField(
        required=False,
        allow_blank=True,
        default="",
        help_text="Optional: 'user_to_user', 'user_to_gym', 'gym_to_user', 'gym_to_gym'. Auto-detected if omitted.",
    )
    target_user_id = StrictUUIDField(required=False, allow_null=True)
    target_gym_id = StrictUUIDField(required=False, allow_null=True)
    source_gym_id = StrictUUIDField(required=False, allow_null=True)

    def validate_conversation_type(self, value):
        if not value:
            return ""
        val = value.strip().lower()
        if val in ("user_to_gym", "gym_to_user"):
            return ConversationTypeEnum.USER_TO_GYM
        if val in ("user_to_user", "gym_to_gym"):
            return val
        raise serializers.ValidationError(f"Invalid conversation_type '{value}'.")


class SendMessageSerializer(serializers.Serializer):
    ciphertext = StrictCharField(allow_blank=False, help_text="Base64 ciphertext string")
    nonce = StrictCharField(max_length=255, allow_blank=False, help_text="Base64 nonce / IV")
    ephemeral_public_key = StrictCharField(required=False, allow_blank=True, default="")
    recipient_key_fingerprint = StrictCharField(required=False, allow_blank=True, default="")
    sender_device_id = StrictCharField(max_length=100, required=False, allow_blank=True, default="")
    encrypted_keys = serializers.DictField(required=False, default=dict)
    sender_type = serializers.ChoiceField(
        choices=MessageSenderTypeEnum.choices,
        default=MessageSenderTypeEnum.USER,
    )
    sender_gym_id = StrictUUIDField(required=False, allow_null=True)
    search_tokens = serializers.ListField(
        child=StrictCharField(max_length=128, allow_blank=False),
        required=False,
        default=list,
        max_length=200,
        help_text="Optional blinded HMAC-SHA256 keyword tokens for the sender's E2EE chat search.",
    )
    shared_search_tokens = serializers.ListField(
        child=StrictCharField(max_length=128, allow_blank=False),
        required=False,
        default=list,
        max_length=200,
        help_text="Optional blinded HMAC-SHA256 keyword tokens derived from a shared conversation search key.",
    )


class EncryptedMessageSerializer(serializers.ModelSerializer):
    sender_gym_name = serializers.CharField(source="sender_gym.name", read_only=True)
    sender_user_full_name = serializers.SerializerMethodField()

    class Meta:
        model = EncryptedMessage
        fields = [
            "id",
            "conversation_id",
            "sender_type",
            "sender_user_id",
            "sender_user_full_name",
            "sender_gym_id",
            "sender_gym_name",
            "sender_device_id",
            "ciphertext",
            "nonce",
            "ephemeral_public_key",
            "recipient_key_fingerprint",
            "encrypted_keys",
            "delivery_status",
            "sent_at",
            "delivered_at",
            "read_at",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_sender_user_full_name(self, obj):
        if obj.sender_user:
            return f"{obj.sender_user.first_name} {obj.sender_user.last_name}".strip()
        return None


class MarkReadSerializer(serializers.Serializer):
    gym_id = StrictUUIDField(required=False, allow_null=True)
    up_to_message_id = StrictUUIDField(required=False, allow_null=True)


class PeopleSearchResultSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    profile_id = serializers.UUIDField(allow_null=True)
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)
    is_private = serializers.BooleanField()
    is_following = serializers.BooleanField()
    is_follower = serializers.BooleanField()
    relationship = serializers.ChoiceField(choices=["mutual", "following", "follower"])
    can_message = serializers.BooleanField()
    conversation_id = serializers.UUIDField(allow_null=True)
    has_e2ee_keys = serializers.BooleanField()


class StrictBooleanField(serializers.BooleanField):
    """Rejects non-boolean types if strict bool is required."""
    def to_internal_value(self, data):
        if not isinstance(data, bool):
            raise serializers.ValidationError("Expected a boolean value.")
        return super().to_internal_value(data)


class StrictIntegerField(serializers.IntegerField):
    """Rejects booleans, strings, lists, and dicts where an integer is expected."""
    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, int):
            raise serializers.ValidationError("Expected an integer value.")
        return super().to_internal_value(data)


class UserE2EEBackupSetSerializer(serializers.Serializer):
    recovery_code = StrictCharField(
        max_length=5,
        required=False,
        allow_blank=True,
        default="",
        help_text="5-digit numeric Messenger-style recovery code (e.g. '12345').",
    )
    backup_public_key = StrictCharField(required=False, allow_blank=True, default="")
    encrypted_key_bundle = StrictCharField(required=False, allow_blank=True, default="")
    nonce = StrictCharField(max_length=255, required=False, allow_blank=True, default="")
    salt = StrictCharField(max_length=255, required=False, allow_blank=True, default="")
    kdf_algorithm = StrictCharField(max_length=32, required=False, default="pbkdf2_sha256")
    kdf_iterations = StrictIntegerField(required=False, default=310000, min_value=10000, max_value=5000000)
    cipher_algorithm = StrictCharField(max_length=32, required=False, default="chacha20_poly1305")
    secret_type = serializers.ChoiceField(
        choices=UserE2EEBackup.SECRET_TYPE_CHOICES,
        required=False,
        default=UserE2EEBackup.SECRET_TYPE_PIN,
    )
    pin_length = StrictIntegerField(required=False, default=5, min_value=5, max_value=5)
    auth_proof = StrictCharField(max_length=255, required=False, allow_blank=True, default="")
    recovery_encrypted_bundle = StrictCharField(required=False, allow_blank=True, default="")
    recovery_nonce = StrictCharField(max_length=255, required=False, allow_blank=True, default="")
    recovery_salt = StrictCharField(max_length=255, required=False, allow_blank=True, default="")
    max_attempts = StrictIntegerField(required=False, default=10, min_value=3, max_value=20)

    def validate_recovery_code(self, value):
        if not value:
            return ""
        if not value.isdigit() or len(value) != 5:
            raise serializers.ValidationError("Recovery code must be a 5-digit number (e.g., '12345').")
        return value

    def validate(self, attrs):
        has_code = bool(attrs.get("recovery_code"))
        has_bundle = all(
            bool(attrs.get(f))
            for f in ("backup_public_key", "encrypted_key_bundle", "nonce", "salt")
        )
        if not has_code and not has_bundle:
            raise serializers.ValidationError(
                "Provide either a 5-digit 'recovery_code' or complete encrypted backup bundle fields "
                "('backup_public_key', 'encrypted_key_bundle', 'nonce', 'salt')."
            )
        return attrs


class UserE2EEBackupRestoreSerializer(serializers.Serializer):
    recovery_code = StrictCharField(
        max_length=5,
        required=False,
        allow_blank=True,
        default="",
        help_text="5-digit numeric Messenger-style recovery code (e.g. '12345').",
    )
    auth_proof = StrictCharField(max_length=255, required=False, allow_blank=True, default="")
    success = StrictBooleanField(required=False, allow_null=True, default=None)
    use_recovery = StrictBooleanField(required=False, default=False)
    # Optional new-device key registration fields to complete restore in 1 request
    device_id = StrictCharField(max_length=100, required=False, allow_blank=True, default="")
    device_name = StrictCharField(max_length=150, required=False, allow_blank=True, default="")
    identity_key = StrictCharField(required=False, allow_blank=True, default="")
    signed_prekey = StrictCharField(required=False, allow_blank=True, default="")
    signed_prekey_signature = StrictCharField(required=False, allow_blank=True, default="")
    one_time_prekeys = serializers.ListField(
        child=StrictCharField(allow_blank=False),
        required=False,
        default=list,
    )

    def validate_recovery_code(self, value):
        if not value:
            return ""
        if not value.isdigit() or len(value) != 5:
            raise serializers.ValidationError("Recovery code must be a 5-digit number (e.g., '12345').")
        return value


class UserE2EEBackupChangeCodeSerializer(serializers.Serializer):
    current_recovery_code = StrictCharField(max_length=5, required=False, allow_blank=True, default="")
    new_recovery_code = StrictCharField(max_length=5, required=False, allow_blank=True, default="")
    current_auth_proof = StrictCharField(max_length=255, required=False, allow_blank=True, default="")
    new_auth_proof = StrictCharField(max_length=255, required=False, allow_blank=True, default="")
    encrypted_key_bundle = StrictCharField(required=False, allow_blank=True, default="")
    nonce = StrictCharField(max_length=255, required=False, allow_blank=True, default="")
    salt = StrictCharField(max_length=255, required=False, allow_blank=True, default="")
    kdf_algorithm = StrictCharField(max_length=32, required=False, default="pbkdf2_sha256")
    kdf_iterations = StrictIntegerField(required=False, default=310000, min_value=10000, max_value=5000000)
    cipher_algorithm = StrictCharField(max_length=32, required=False, default="chacha20_poly1305")
    secret_type = serializers.ChoiceField(
        choices=UserE2EEBackup.SECRET_TYPE_CHOICES,
        required=False,
        allow_null=True,
        default=None,
    )
    backup_public_key = StrictCharField(required=False, allow_blank=True, default="")

    def validate_current_recovery_code(self, value):
        if not value:
            return ""
        if not value.isdigit() or len(value) != 5:
            raise serializers.ValidationError("current_recovery_code must be a 5-digit number.")
        return value

    def validate_new_recovery_code(self, value):
        if not value:
            return ""
        if not value.isdigit() or len(value) != 5:
            raise serializers.ValidationError("new_recovery_code must be a 5-digit number.")
        return value

    def validate(self, attrs):
        has_codes = bool(attrs.get("current_recovery_code") and attrs.get("new_recovery_code"))
        has_bundle = all(bool(attrs.get(f)) for f in ("encrypted_key_bundle", "nonce", "salt"))
        if not has_codes and not has_bundle:
            raise serializers.ValidationError(
                "Provide either 'current_recovery_code' + 'new_recovery_code' or re-encrypted bundle fields."
            )
        return attrs


class ChatHistorySearchSerializer(serializers.Serializer):
    tokens = serializers.ListField(
        child=StrictCharField(max_length=128, allow_blank=False),
        min_length=1,
        max_length=20,
    )
    match_mode = serializers.ChoiceField(choices=["all", "any"], required=False, default="all")
    conversation_id = StrictUUIDField(required=False, allow_null=True, default=None)
    gym_id = StrictUUIDField(required=False, allow_null=True, default=None)
    limit = StrictIntegerField(required=False, default=20, min_value=1, max_value=50)
    matches_per_chat = StrictIntegerField(required=False, default=5, min_value=1, max_value=20)


class MessageSearchIndexItemSerializer(serializers.Serializer):
    message_id = StrictUUIDField()
    tokens = serializers.ListField(
        child=StrictCharField(max_length=128, allow_blank=False),
        min_length=1,
        max_length=200,
    )


class MessageSearchIndexBatchSerializer(serializers.Serializer):
    gym_id = StrictUUIDField(required=False, allow_null=True, default=None)
    items = serializers.ListField(
        child=MessageSearchIndexItemSerializer(),
        min_length=1,
        max_length=100,
    )
