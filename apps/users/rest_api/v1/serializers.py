from rest_framework import serializers
from apps.users.models import User, UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = [
            "avatar_url",
            "address",
            "city",
            "country",
            "date_of_birth",
            "sex",
            "nationality",
            "created_at",
            "updated_at",
        ]


class UserSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "phone",
            "status",
            "is_verified",
            "created_at",
            "updated_at",
            "profile",
        ]
        read_only_fields = ["id", "email", "status", "is_verified", "created_at", "updated_at"]


class UserRegistrationSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True, min_length=8)
    first_name = serializers.CharField(required=True, max_length=100)
    last_name = serializers.CharField(required=True, max_length=100)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50)


class VerifySignupOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp_code = serializers.CharField(required=True, min_length=6, max_length=6)


class ResendOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)


class VerifyResetOTPSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp_code = serializers.CharField(required=True, min_length=6, max_length=6)


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp_code = serializers.CharField(required=True, min_length=6, max_length=6)
    new_password = serializers.CharField(required=True, min_length=8)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)


class UpdateProfileSerializer(serializers.Serializer):
    first_name = serializers.CharField(required=False, max_length=100)
    last_name = serializers.CharField(required=False, max_length=100)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=50)
    avatar_url = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    address = serializers.CharField(required=False, allow_blank=True, max_length=500)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)
    country = serializers.CharField(required=False, allow_blank=True, max_length=100)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    sex = serializers.CharField(required=False, allow_blank=True, max_length=20)
    nationality = serializers.CharField(required=False, allow_blank=True, max_length=100)


class RegisterResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    email = serializers.EmailField()


class TokenResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    context_type = serializers.CharField()
    gym_id = serializers.UUIDField(allow_null=True)
    gym_name = serializers.CharField(allow_null=True)
    scopes = serializers.ListField(child=serializers.CharField())


class VerifySignupResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    user = UserSerializer()
    tokens = TokenResponseSerializer()


class CurrentContextSerializer(serializers.Serializer):
    type = serializers.CharField()
    gym_id = serializers.UUIDField(allow_null=True)
    scopes = serializers.ListField(child=serializers.CharField())


class AccessibleGymItemSerializer(serializers.Serializer):
    gym_id = serializers.UUIDField()
    name = serializers.CharField()
    role = serializers.CharField()
    is_owner = serializers.BooleanField()
    primary_type = serializers.CharField()
    profile_picture_url = serializers.CharField(allow_null=True)


class UserProfileMeResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    current_context = CurrentContextSerializer()
    accessible_gyms = AccessibleGymItemSerializer(many=True)

