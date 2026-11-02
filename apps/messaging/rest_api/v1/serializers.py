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
