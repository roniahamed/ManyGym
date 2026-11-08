from rest_framework import serializers
from apps.enquiries.models import Enquiry
from apps.users.models import User
from common.enums import EnquiryTypeEnum, EnquiryStatusEnum
from common.serializers import StrictCharField, StrictUUIDField


class ManygymUserSlimSerializer(serializers.ModelSerializer):
    """
    Representation serializer for Manygym User object inside Enquiry.
    """
    user_id = serializers.UUIDField(source="id", read_only=True)
    full_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "user_id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "avatar_url",
        ]

    def get_full_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_avatar_url(self, obj):
        profile = getattr(obj, "profile", None)
        return getattr(profile, "avatar_url", None)


class EnquiryListSerializer(serializers.ModelSerializer):
    """
    Presentation serializer for Enquiry list view.
    """
    manygym_user = ManygymUserSlimSerializer(read_only=True)
    gym_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Enquiry
        fields = [
            "id",
            "gym_id",
            "manygym_user",
            "first_name",
            "last_name",
            "email",
            "phone",
            "type",
            "status",
            "summary",
            "notes",
            "created_at",
            "updated_at",
        ]


class EnquiryDetailSerializer(serializers.ModelSerializer):
    """
    Presentation serializer for full Enquiry dossier.
    """
    manygym_user = ManygymUserSlimSerializer(read_only=True)
    gym_id = serializers.UUIDField(read_only=True, allow_null=True)
    gym_name = serializers.SerializerMethodField()

    class Meta:
        model = Enquiry
        fields = [
            "id",
            "gym_id",
            "gym_name",
            "manygym_user",
            "first_name",
            "last_name",
            "email",
            "phone",
            "type",
            "status",
            "summary",
            "notes",
            "created_at",
            "updated_at",
        ]

    def get_gym_name(self, obj):
        return obj.gym.name if obj.gym else None


class EnquiryCreateSerializer(serializers.Serializer):
    """
    Validation and deserialization serializer for creating a new Enquiry.
    Enforces mandatory:
    - first_name, last_name
    - either email or phone
    """
    first_name = StrictCharField(max_length=100, help_text="First name (required).")
    last_name = StrictCharField(max_length=100, help_text="Last name (required).")
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True, max_length=255)
    phone = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=50)
    manygym_user_id = serializers.UUIDField(required=False, allow_null=True, help_text="Optional Manygym registered User ID.")
    gym_id = serializers.UUIDField(required=False, allow_null=True, help_text="Optional Gym UUID.")
    type = serializers.CharField(required=False, default=EnquiryTypeEnum.GENERAL_INQUIRY)
    status = serializers.CharField(required=False, default=EnquiryStatusEnum.NEW)
    summary = serializers.CharField(required=False, allow_blank=True, default="")
    notes = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        default=list,
        help_text="Optional list of text notes.",
    )

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
        alias_map = {
            "BOOK": EnquiryStatusEnum.BOOKED,
            "BOOKED": EnquiryStatusEnum.BOOKED,
            "VISIT": EnquiryStatusEnum.VISIT,
            "CONTACTED": EnquiryStatusEnum.CONTACTED,
            "NEW": EnquiryStatusEnum.NEW,
        }
        if val in alias_map:
            return alias_map[val]
        raise serializers.ValidationError(
            f"Invalid status '{value}'. Choices: {', '.join([c.value for c in EnquiryStatusEnum])}"
        )

    def validate(self, attrs):
        email = (attrs.get("email") or "").strip()
        phone = (attrs.get("phone") or "").strip()
        if not email and not phone:
            raise serializers.ValidationError("Either Email or Phone number is mandatory.")
        attrs["email"] = email or None
        attrs["phone"] = phone or None
        return attrs


class EnquiryUpdateSerializer(serializers.Serializer):
    """
    Validation and deserialization serializer for updating an existing Enquiry.
    """
    first_name = StrictCharField(required=False, max_length=100)
    last_name = StrictCharField(required=False, max_length=100)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True, max_length=255)
    phone = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=50)
    manygym_user_id = serializers.UUIDField(required=False, allow_null=True)
    type = serializers.CharField(required=False)
    status = serializers.CharField(required=False)
    summary = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        help_text="Full replacement list of text notes.",
    )
    append_note = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Convenience parameter to append a single new text note.",
    )

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
        alias_map = {
            "BOOK": EnquiryStatusEnum.BOOKED,
            "BOOKED": EnquiryStatusEnum.BOOKED,
            "VISIT": EnquiryStatusEnum.VISIT,
            "CONTACTED": EnquiryStatusEnum.CONTACTED,
            "NEW": EnquiryStatusEnum.NEW,
        }
        if val in alias_map:
            return alias_map[val]
        raise serializers.ValidationError(
            f"Invalid status '{value}'. Choices: {', '.join([c.value for c in EnquiryStatusEnum])}"
        )


class EnquiryAddNoteSerializer(serializers.Serializer):
    """
    Serializer for appending a text note to an Enquiry.
    """
    note = serializers.CharField(required=False, allow_blank=False)
    note_text = serializers.CharField(required=False, allow_blank=False)

    def validate(self, attrs):
        text = attrs.get("note") or attrs.get("note_text")
        if not text or not str(text).strip():
            raise serializers.ValidationError("Note text is required.")
        attrs["note_text"] = str(text).strip()
        return attrs

