from rest_framework import serializers
from common.serializers import StrictCharField
from apps.users.rest_api.v1.serializers.profile_serializers import UserSerializer, TokenResponseSerializer


class UserRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = StrictCharField(write_only=True, required=True, min_length=8)
    first_name = StrictCharField(required=True, max_length=100)
    last_name = StrictCharField(required=True, max_length=100)
    phone = StrictCharField(required=False, allow_blank=True, max_length=50)


class VerifySignupOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp_code = StrictCharField(required=True, min_length=6, max_length=6)


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class VerifyResetOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp_code = StrictCharField(required=True, min_length=6, max_length=6)


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp_code = StrictCharField(required=True, min_length=6, max_length=6)
    new_password = StrictCharField(required=True, min_length=8)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = StrictCharField(required=True)
    new_password = StrictCharField(required=True, min_length=8)


class RegisterResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    email = serializers.EmailField()


class VerifySignupResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    user = UserSerializer()
    tokens = TokenResponseSerializer()
