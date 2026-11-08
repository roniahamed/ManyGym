from rest_framework import serializers

from apps.enquiries.models import Enquiry
from apps.users.models import User
from apps.gyms.models import Gym
from common.enums import EnquiryTypeEnum, EnquiryStatusEnum
from common.serializers import StrictCharField, StrictUUIDField


class ManygymUserSlimSerializer(serializers.ModelSerializer):
    """
    Slim representation serializer for Manygym registered User object.
    """
    user_id = serializers.UUIDField(source="id", read_only=True)
    full_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    phone = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            "user_id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "avatar_url",
            "phone",
        ]

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_avatar_url(self, obj):
        profile = getattr(obj, "profile", None)
        return getattr(profile, "avatar_url", None)


class EnquiryListSerializer(serializers.ModelSerializer):
    """
    Presentation serializer for Enquiry list and summary views.
    """
    manygym_user = ManygymUserSlimSerializer(read_only=True)
    gym_id = serializers.UUIDField(read_only=True)
    type_display = serializers.CharField(read_only=True)
    status_display = serializers.CharField(read_only=True)
    notes_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Enquiry
        fields = [
            "id",
            "gym_id",
            "manygym_user",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "type",
            "type_display",
            "status",
            "status_display",
            "summary",
            "notes",
            "notes_count",
            "created_at",
            "updated_at",
        ]


class EnquiryDetailSerializer(serializers.ModelSerializer):
    """
    Presentation serializer for full Enquiry dossier view.
    """
    manygym_user = ManygymUserSlimSerializer(read_only=True)
    gym_id = serializers.UUIDField(read_only=True)
    gym_name = serializers.SerializerMethodField()
    type_display = serializers.CharField(read_only=True)
    status_display = serializers.CharField(read_only=True)
    notes_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Enquiry
        fields = [
            "id",
            "gym_id",
            "gym_name",
            "manygym_user",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "type",
            "type_display",
            "status",
            "status_display",
            "summary",
            "notes",
            "notes_count",
            "created_at",
            "updated_at",
        ]

    def get_gym_name(self, obj):
        return obj.gym.name if obj.gym else None


class EnquiryCreateSerializer(serializers.Serializer):
    """
    Validation and deserialization serializer for creating a new Enquiry.
    Enforces mandatory:
    - gym_id
    - first_name, last_name
    - either email or phone
    """
    gym_id = StrictUUIDField(required=True, allow_null=False, help_text="Gym UUID to which this enquiry belongs (required).")
    first_name = StrictCharField(max_length=100, help_text="First name (required).")
    last_name = StrictCharField(max_length=100, help_text="Last name (required).")
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True, max_length=255)
    phone = StrictCharField(required=False, allow_null=True, allow_blank=True, max_length=50)
    manygym_user_id = StrictUUIDField(required=False, allow_null=True, help_text="Optional Manygym registered User ID.")
    type = StrictCharField(required=False, default=EnquiryTypeEnum.GENERAL_INQUIRY)
    status = StrictCharField(required=False, default=EnquiryStatusEnum.NEW)
    summary = StrictCharField(required=False, allow_blank=True, default="")
    notes = serializers.ListField(
        child=StrictCharField(allow_blank=False),
        required=False,
        default=list,
        help_text="Optional list of text notes.",
    )

    def validate_gym_id(self, value):
        if not value:
            raise serializers.ValidationError("gym_id is required.")
        if not Gym.objects.filter(id=value).exists():
            raise serializers.ValidationError("Gym with the provided ID does not exist.")
        return value

    def validate_first_name(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError("First name cannot be empty or whitespace.")
        return str(value).strip()

    def validate_last_name(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError("Last name cannot be empty or whitespace.")
        return str(value).strip()

    def validate_email(self, value):
        if value is None:
            return None
        val = str(value).strip().lower()
        return val if val else None

    def validate_phone(self, value):
        if value is None:
            return None
        val = str(value).strip()
        return val if val else None

    def validate_type(self, value):
        if not value:
            return EnquiryTypeEnum.GENERAL_INQUIRY
        val = str(value).strip().upper()
        if val not in {c.value for c in EnquiryTypeEnum}:
            raise serializers.ValidationError(
                f"Invalid type '{value}'. Choices: {', '.join([c.value for c in EnquiryTypeEnum])}"
            )
        return val

    def validate_status(self, value):
        if not value:
            return EnquiryStatusEnum.NEW
        val = str(value).strip().upper()
        status_alias_map = {
            "BOOK": EnquiryStatusEnum.BOOKED,
            "BOOKED": EnquiryStatusEnum.BOOKED,
            "VISIT": EnquiryStatusEnum.VISIT,
            "CONTACTED": EnquiryStatusEnum.CONTACTED,
            "NEW": EnquiryStatusEnum.NEW,
        }
        if val in status_alias_map:
            return status_alias_map[val]
        raise serializers.ValidationError(
            f"Invalid status '{value}'. Choices: {', '.join([c.value for c in EnquiryStatusEnum])}"
        )

    def validate(self, attrs):
        email = attrs.get("email")
        phone = attrs.get("phone")
        if not email and not phone:
            raise serializers.ValidationError("Either Email or Phone number is mandatory.")
        return attrs


class EnquiryUpdateSerializer(serializers.Serializer):
    """
    Validation and deserialization serializer for updating an existing Enquiry.
    """
    first_name = StrictCharField(required=False, max_length=100)
    last_name = StrictCharField(required=False, max_length=100)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True, max_length=255)
    phone = StrictCharField(required=False, allow_null=True, allow_blank=True, max_length=50)
    gym_id = StrictUUIDField(required=False, allow_null=False)
    manygym_user_id = StrictUUIDField(required=False, allow_null=True)
    type = StrictCharField(required=False)
    status = StrictCharField(required=False)
    summary = StrictCharField(required=False, allow_blank=True)
    notes = serializers.ListField(
        child=StrictCharField(allow_blank=False),
        required=False,
        help_text="Full replacement list of text notes.",
    )
    append_note = StrictCharField(
        required=False,
        allow_blank=False,
        help_text="Convenience parameter to append a single new text note.",
    )

    def validate_gym_id(self, value):
        if value is None:
            raise serializers.ValidationError("gym_id cannot be null.")
        if not Gym.objects.filter(id=value).exists():
            raise serializers.ValidationError("Gym with the provided ID does not exist.")
        return value

    def validate_first_name(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError("First name cannot be empty or whitespace.")
        return str(value).strip()

    def validate_last_name(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError("Last name cannot be empty or whitespace.")
        return str(value).strip()

    def validate_email(self, value):
        if value is None:
            return None
        val = str(value).strip().lower()
        return val if val else None

    def validate_phone(self, value):
        if value is None:
            return None
        val = str(value).strip()
        return val if val else None

    def validate_type(self, value):
        if not value:
            return value
        val = str(value).strip().upper()
        if val not in {c.value for c in EnquiryTypeEnum}:
            raise serializers.ValidationError(
                f"Invalid type '{value}'. Choices: {', '.join([c.value for c in EnquiryTypeEnum])}"
            )
        return val

    def validate_status(self, value):
        if not value:
            return value
        val = str(value).strip().upper()
        status_alias_map = {
            "BOOK": EnquiryStatusEnum.BOOKED,
            "BOOKED": EnquiryStatusEnum.BOOKED,
            "VISIT": EnquiryStatusEnum.VISIT,
            "CONTACTED": EnquiryStatusEnum.CONTACTED,
            "NEW": EnquiryStatusEnum.NEW,
        }
        if val in status_alias_map:
            return status_alias_map[val]
        raise serializers.ValidationError(
            f"Invalid status '{value}'. Choices: {', '.join([c.value for c in EnquiryStatusEnum])}"
        )

    def validate(self, attrs):
        # If both email and phone are explicitly provided as empty/None, reject
        has_email_key = "email" in attrs
        has_phone_key = "phone" in attrs
        if has_email_key and has_phone_key:
            if not attrs.get("email") and not attrs.get("phone"):
                raise serializers.ValidationError("Either Email or Phone number is mandatory.")
        return attrs


class EnquiryAddNoteSerializer(serializers.Serializer):
    """
    Serializer for appending a text note to an Enquiry.
    """
    note = StrictCharField(required=False, allow_blank=False)
    note_text = StrictCharField(required=False, allow_blank=False)

    def validate(self, attrs):
        text = attrs.get("note") or attrs.get("note_text")
        if not text or not str(text).strip():
            raise serializers.ValidationError("Note text cannot be empty.")
        attrs["note_text"] = str(text).strip()
        return attrs
