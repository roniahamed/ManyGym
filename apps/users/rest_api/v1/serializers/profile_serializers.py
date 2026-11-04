from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from apps.users.models import User, UserProfile, UserEducation, UserSocialLink
from common.enums import GenderEnum, SocialPlatformEnum
from common.serializers import StrictCharField, StrictBooleanField, validate_uploaded_image


class FlexibleDateField(serializers.DateField):
    """Accepts standard YYYY-MM-DD or 4-digit year format (e.g. '2020' -> 2020-01-01)."""

    def to_internal_value(self, data):
        if isinstance(data, (bool, dict, list)):
            raise serializers.ValidationError("Expected a valid date string (YYYY-MM-DD or YYYY).")
        if isinstance(data, str) and data.strip().isdigit() and len(data.strip()) == 4:
            import datetime
            try:
                year = int(data.strip())
                if 1900 <= year <= 2100:
                    return datetime.date(year, 1, 1)
            except Exception:
                pass
        elif isinstance(data, int) and not isinstance(data, bool) and 1900 <= data <= 2100:
            import datetime
            return datetime.date(data, 1, 1)
        return super().to_internal_value(data)


class UserEducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserEducation
        fields = [
            "id",
            "university_name",
            "from_year",
            "till_year",
            "subject",
            "graduated",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class UserEducationInputSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False, allow_null=True)
    university_name = StrictCharField(max_length=255, required=True)
    from_year = FlexibleDateField(required=True)
    till_year = FlexibleDateField(required=False, allow_null=True)
    subject = StrictCharField(max_length=255, required=True)
    graduated = StrictBooleanField(required=False, default=False)

    def validate(self, attrs):
        from_year = attrs.get("from_year")
        till_year = attrs.get("till_year")
        if from_year and till_year and till_year < from_year:
            raise serializers.ValidationError({"till_year": "Till year must be greater than or equal to from year."})
        return attrs


class UserSocialLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSocialLink
        fields = ["id", "platform", "link", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class UserSocialLinkInputSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False, allow_null=True)
    platform = serializers.ChoiceField(choices=SocialPlatformEnum.choices, required=True)
    link = StrictCharField(max_length=1000, required=True)


class PersonalDetailsSerializer(serializers.Serializer):
    current_address = StrictCharField(allow_blank=True, allow_null=True, required=False, max_length=500)
    home_town = StrictCharField(allow_blank=True, allow_null=True, required=False, max_length=255)
    date_of_birth = serializers.DateField(allow_null=True, required=False)
    gender = serializers.ChoiceField(choices=GenderEnum.choices, allow_blank=True, allow_null=True, required=False)


class ContactInfoSerializer(serializers.Serializer):
    social_links = UserSocialLinkSerializer(many=True, read_only=True)
    phone_number = serializers.CharField(allow_null=True, read_only=True)
    email = serializers.EmailField(read_only=True, help_text="Registered account email (cannot be changed).")


class ContactInfoInputSerializer(serializers.Serializer):
    social_links = serializers.ListField(
        child=UserSocialLinkInputSerializer(),
        required=False,
        max_length=50,
    )
    phone_number = StrictCharField(max_length=50, required=False, allow_blank=True, allow_null=True)


class DetailsAboutYouSerializer(serializers.Serializer):
    about_you = StrictCharField(max_length=320, allow_blank=True, allow_null=True, required=False)
    favourite_quote = StrictCharField(max_length=160, allow_blank=True, allow_null=True, required=False)


class UserAboutResponseSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(source="id")
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    avatar_url = serializers.CharField(source="profile.avatar_url", allow_null=True)
    is_private = serializers.BooleanField(source="profile.is_private")
    personal_details = serializers.SerializerMethodField()
    education_list = UserEducationSerializer(source="educations", many=True)
    hobbies = serializers.SerializerMethodField()
    contact_info = serializers.SerializerMethodField()
    details_about_you = serializers.SerializerMethodField()

    @extend_schema_field(PersonalDetailsSerializer)
    def get_personal_details(self, obj):
        profile = getattr(obj, "profile", None)
        return {
            "current_address": profile.address if profile else None,
            "home_town": profile.home_town if profile else None,
            "date_of_birth": profile.date_of_birth if profile else None,
            "gender": profile.gender if profile else None,
        }

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_hobbies(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.hobbies if profile and profile.hobbies else []

    @extend_schema_field(ContactInfoSerializer)
    def get_contact_info(self, obj):
        social_links = getattr(obj, "social_links", None)
        links_data = UserSocialLinkSerializer(
            social_links.all() if hasattr(social_links, "all") else [],
            many=True,
        ).data
        return {
            "social_links": links_data,
            "phone_number": obj.phone,
            "email": obj.email,
        }

    @extend_schema_field(DetailsAboutYouSerializer)
    def get_details_about_you(self, obj):
        profile = getattr(obj, "profile", None)
        return {
            "about_you": profile.about_you if profile else None,
            "favourite_quote": profile.favourite_quote if profile else None,
        }


class UserAboutUpdateSerializer(serializers.Serializer):
    # Nested sections
    personal_details = PersonalDetailsSerializer(required=False)
    education_list = serializers.ListField(
        child=UserEducationInputSerializer(),
        required=False,
        max_length=50,
    )
    hobbies = serializers.ListField(
        child=StrictCharField(max_length=100),
        required=False,
        max_length=100,
    )
    contact_info = ContactInfoInputSerializer(required=False)
    details_about_you = DetailsAboutYouSerializer(required=False)

    # Flat aliases for direct convenience
    current_address = StrictCharField(required=False, allow_blank=True, max_length=500)
    home_town = StrictCharField(required=False, allow_blank=True, max_length=255)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.ChoiceField(choices=GenderEnum.choices, required=False, allow_blank=True, allow_null=True)
    phone_number = StrictCharField(required=False, allow_blank=True, max_length=50)
    social_links = serializers.ListField(
        child=UserSocialLinkInputSerializer(),
        required=False,
        max_length=50,
    )
    about_you = StrictCharField(required=False, allow_blank=True, max_length=320)
    favourite_quote = StrictCharField(required=False, allow_blank=True, max_length=160)


class UserProfileSerializer(serializers.ModelSerializer):
    current_address = serializers.CharField(source="address", read_only=True)

    class Meta:
        model = UserProfile
        fields = [
            "avatar_url",
            "address",
            "current_address",
            "home_town",
            "city",
            "country",
            "date_of_birth",
            "sex",
            "gender",
            "nationality",
            "hobbies",
            "about_you",
            "favourite_quote",
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
