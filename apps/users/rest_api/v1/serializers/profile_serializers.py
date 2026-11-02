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


UserProfileUpdateSerializer = UpdateProfileSerializer


class TokenResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    context_type = serializers.CharField()
    gym_id = serializers.UUIDField(allow_null=True)
    gym_name = serializers.CharField(allow_null=True)
    scopes = serializers.ListField(child=serializers.CharField())


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
