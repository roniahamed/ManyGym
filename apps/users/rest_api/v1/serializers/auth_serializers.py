from rest_framework import serializers
from common.serializers import StrictCharField
from apps.users.rest_api.v1.serializers.profile_serializers import UserSerializer, TokenResponseSerializer


class UserRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, max_length=255)
    password = StrictCharField(write_only=True, required=True, min_length=8)
    first_name = StrictCharField(required=True, max_length=100)
    last_name = StrictCharField(required=True, max_length=100)
    phone = StrictCharField(required=False, allow_blank=True, max_length=50)


class VerifySignupOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, max_length=255)
    otp_code = StrictCharField(required=True, min_length=6, max_length=6)


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, max_length=255)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, max_length=255)


class VerifyResetOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, max_length=255)
    otp_code = StrictCharField(required=True, min_length=6, max_length=6)


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True, max_length=255)
    otp_code = StrictCharField(required=True, min_length=6, max_length=6)
    new_password = StrictCharField(required=True, min_length=8)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = StrictCharField(required=True)
    new_password = StrictCharField(required=True, min_length=8)
    confirm_password = StrictCharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if "\x00" in attrs.get("new_password", "") or "\x00" in attrs.get("current_password", ""):
            raise serializers.ValidationError("Null characters are not allowed.")
        confirm = attrs.get("confirm_password")
        if confirm and confirm != attrs.get("new_password"):
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs


class RegisterResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    email = serializers.EmailField()


class VerifySignupResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    user = UserSerializer()
    tokens = TokenResponseSerializer()
