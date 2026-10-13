from rest_framework import serializers
from common.enums import TokenContextType
from common.serializers import StrictCharField, StrictUUIDField
from apps.users.rest_api.v1.serializers import UserSerializer, TokenResponseSerializer


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = StrictCharField(required=True, write_only=True)


class SwitchContextSerializer(serializers.Serializer):
    context_type = serializers.ChoiceField(
        choices=TokenContextType.choices,
        required=True,
        help_text="Target context type: 'personal' or 'gym'",
    )
    gym_id = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text="Required if context_type is 'gym'",
    )

    def validate(self, attrs):
        if attrs.get("context_type") == TokenContextType.GYM and not attrs.get("gym_id"):
            raise serializers.ValidationError({"gym_id": "gym_id is required when switching to gym context."})
        return attrs


class LogoutSerializer(serializers.Serializer):
    refresh = StrictCharField(required=False, allow_blank=True)


class LoginResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    user = UserSerializer()
    tokens = TokenResponseSerializer()


class SwitchContextResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    tokens = TokenResponseSerializer()
