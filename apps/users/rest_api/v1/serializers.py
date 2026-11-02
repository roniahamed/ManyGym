from rest_framework import serializers
from apps.users.models import User, UserProfile
from common.serializers import StrictCharField, validate_uploaded_image


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
            "is_private",
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


class UpdateProfileSerializer(serializers.Serializer):
    first_name = StrictCharField(required=False, max_length=100)
    last_name = StrictCharField(required=False, max_length=100)
    phone = StrictCharField(required=False, allow_blank=True, max_length=50)
    avatar_url = StrictCharField(required=False, allow_blank=True, max_length=1000)
    avatar = serializers.FileField(
        required=False,
        allow_null=True,
        help_text="Direct avatar image upload (multipart/form-data). Max size: 10MB. Formats: JPEG, PNG, WebP, BMP, GIF, HEIC, TIFF. Automatically corrects orientation and converts directly to WebP.",
    )
    address = StrictCharField(required=False, allow_blank=True, max_length=500)
    city = StrictCharField(required=False, allow_blank=True, max_length=100)
    country = StrictCharField(required=False, allow_blank=True, max_length=100)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    sex = StrictCharField(required=False, allow_blank=True, max_length=20)
    nationality = StrictCharField(required=False, allow_blank=True, max_length=100)
    is_private = serializers.BooleanField(required=False)

    def validate(self, attrs):
        validate_uploaded_image(attrs.get("avatar"), field_name="avatar")
        return attrs



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
    type = serializers.CharField(help_text="Active token session context ('personal' or 'gym').")
    gym_id = serializers.UUIDField(allow_null=True, help_text="ID of active gym if in gym context; null if personal.")
    gym_name = serializers.CharField(allow_null=True, required=False, help_text="Name of active gym if in gym context.")
    profile_picture_url = serializers.CharField(allow_null=True, required=False, help_text="Profile picture URL of active gym if in gym context.")
    scopes = serializers.ListField(child=serializers.CharField(), help_text="Effective RBAC permission scopes for active context.")


class AccessibleGymItemSerializer(serializers.Serializer):
    gym_id = serializers.UUIDField(help_text="Unique identifier of accessible gym.")
    name = serializers.CharField(help_text="Display name of the gym.")
    role = serializers.CharField(help_text="User's role in this gym ('Owner' or assigned staff role).")
    is_owner = serializers.BooleanField(help_text="True if user owns this gym tenant.")
    primary_type = serializers.CharField(help_text="Gym facility category/type.")
    profile_picture_url = serializers.CharField(allow_null=True, help_text="Profile/logo image URL of the gym.")


class UserProfileMeResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    current_context = CurrentContextSerializer()
    accessible_gyms = AccessibleGymItemSerializer(many=True)


class FollowUserItemSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(help_text="User unique identifier.")
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)
    is_private = serializers.BooleanField()
    followed_at = serializers.DateTimeField()


class UserFollowActionResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    is_following = serializers.BooleanField()
    target_user_id = serializers.UUIDField()


class FollowActionSerializer(serializers.Serializer):
    target_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of target User or Gym. Auto-detected whether user or gym.",
    )
    id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Alias for target_id.",
    )
    target_type = serializers.ChoiceField(
        choices=["user", "gym"],
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional entity type ('user' or 'gym'). Auto-detected automatically if omitted.",
    )
    action = serializers.ChoiceField(
        choices=["follow", "unfollow"],
        default="follow",
        required=False,
        help_text="Action to perform: 'follow' (default) or 'unfollow'.",
    )

    def validate(self, attrs):
        tid = attrs.get("target_id") or attrs.get("id") or self.context.get("target_id")
        if not tid:
            raise serializers.ValidationError("Please provide target_id (or id).")
        attrs["target_id"] = tid
        return attrs



class FollowActionResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    is_following = serializers.BooleanField()
    target_type = serializers.CharField()
    target_id = serializers.UUIDField()
    target_name = serializers.CharField(allow_null=True, required=False)


