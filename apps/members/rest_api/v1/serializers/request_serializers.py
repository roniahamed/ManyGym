from decimal import Decimal
from typing import Optional, Dict, Any
from django.utils import timezone
from rest_framework import serializers

from apps.members.models import MemberRequest
from apps.memberships.models import MembershipPlan
from apps.users.models import User
from common.enums import PaymentMethodEnum
from common.serializers import (
    StrictCharField,
    StrictUUIDField,
    StrictDecimalField,
    validate_uploaded_image,
)


class MemberRequestUserSerializer(serializers.ModelSerializer):
    """Minimal demographic profile of user requesting membership."""
    profile_photo_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "profile_photo_url",
        ]

    def get_profile_photo_url(self, obj: User) -> Optional[str]:
        profile = getattr(obj, "profile", None)
        if profile and getattr(profile, "profile_photo_url", None):
            return profile.profile_photo_url
        return getattr(obj, "avatar_url", None)


class MemberRequestPlanSerializer(serializers.ModelSerializer):
    """Membership plan summary requested by applicant."""
    class Meta:
        model = MembershipPlan
        fields = ["id", "name", "price", "duration_value", "duration_unit", "plan_type"]


class MemberRequestListSerializer(serializers.ModelSerializer):
    """List representation for gym staff reviewing incoming member requests."""
    gym_id = serializers.UUIDField(source="gym.id", read_only=True)
    user = MemberRequestUserSerializer(read_only=True)
    interested_plan = MemberRequestPlanSerializer(read_only=True)
    reviewed_by_name = serializers.SerializerMethodField()
    created_member_id = serializers.UUIDField(source="created_member.id", read_only=True, allow_null=True)

    class Meta:
        model = MemberRequest
        fields = [
            "id",
            "gym_id",
            "user",
            "interested_plan",
            "notes",
            "status",
            "created_member_id",
            "reviewed_by_name",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]

    def get_reviewed_by_name(self, obj: MemberRequest) -> Optional[str]:
        if obj.reviewed_by:
            name = f"{obj.reviewed_by.first_name} {obj.reviewed_by.last_name}".strip()
            return name or obj.reviewed_by.email
        return None


class MemberRequestDetailSerializer(serializers.ModelSerializer):
    """Full detailed representation of a gym member request."""
    gym_id = serializers.UUIDField(source="gym.id", read_only=True)
    gym_name = serializers.CharField(source="gym.name", read_only=True)
    user = MemberRequestUserSerializer(read_only=True)
    interested_plan = MemberRequestPlanSerializer(read_only=True)
    reviewed_by_name = serializers.SerializerMethodField()
    created_member_id = serializers.UUIDField(source="created_member.id", read_only=True, allow_null=True)

    class Meta:
        model = MemberRequest
        fields = [
            "id",
            "gym_id",
            "gym_name",
            "user",
            "interested_plan",
            "notes",
            "status",
            "rejection_reason",
            "created_member_id",
            "reviewed_by_name",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]

    def get_reviewed_by_name(self, obj: MemberRequest) -> Optional[str]:
        if obj.reviewed_by:
            name = f"{obj.reviewed_by.first_name} {obj.reviewed_by.last_name}".strip()
            return name or obj.reviewed_by.email
        return None


class MemberRequestCreateSerializer(serializers.Serializer):
    """Payload sent by an authenticated user requesting to join a gym."""
    interested_plan_id = StrictUUIDField(required=False, allow_null=True)
    notes = StrictCharField(required=False, allow_blank=True, allow_null=True, max_length=500)


class MemberRequestAcceptSerializer(serializers.Serializer):
    """
    Payload provided by gym staff or admin when accepting a joining request.
    Populates all necessary member enrollment details.
    """
    # Membership plan
    plan_id = StrictUUIDField(required=False, allow_null=True)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    assigned_trainer_id = StrictUUIDField(required=False, allow_null=True)
    extra_amenity_ids = serializers.ListField(
        child=StrictUUIDField(),
        required=False,
        default=list,
    )

    # Initial payment
    initial_payment_amount = StrictDecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
        allow_null=True,
    )
    initial_payment_method = serializers.ChoiceField(
        choices=PaymentMethodEnum.choices,
        required=False,
        allow_null=True,
    )
    initial_payment_date = serializers.DateField(required=False, allow_null=True)
    initial_payment_notes = StrictCharField(required=False, allow_blank=True, allow_null=True)

    # Optional member demographic details (defaults to applicant's user profile if omitted)
    first_name = StrictCharField(min_length=1, max_length=100, required=False, allow_blank=True)
    last_name = StrictCharField(min_length=1, max_length=100, required=False, allow_blank=True)
    email = serializers.EmailField(max_length=255, required=False, allow_blank=True)
    phone = StrictCharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    profile_photo = serializers.FileField(required=False, allow_null=True)
    profile_photo_url = StrictCharField(max_length=1000, required=False, allow_blank=True, allow_null=True)
    address = StrictCharField(max_length=500, required=False, allow_blank=True, allow_null=True)
    city = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    country = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    sex = StrictCharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    nationality = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)

    # Emergency Contact
    emergency_contact_name = StrictCharField(max_length=150, required=False, allow_blank=True, allow_null=True)
    emergency_contact_phone = StrictCharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    emergency_contact_relationship = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)

    internal_notes = StrictCharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        if "profile_photo" in attrs and attrs["profile_photo"]:
            validate_uploaded_image(attrs.get("profile_photo"), field_name="profile_photo")

        start = attrs.get("start_date") or timezone.now().date()
        end = attrs.get("end_date")
        if end and end < start:
            raise serializers.ValidationError({"end_date": "Subscription end date cannot be prior to start date."})

        amt = attrs.get("initial_payment_amount")
        method = attrs.get("initial_payment_method")
        if amt and not method:
            raise serializers.ValidationError({
                "initial_payment_method": "Payment method is required when initial payment amount is specified."
            })
        return attrs


class MemberRequestRejectSerializer(serializers.Serializer):
    """Payload sent by staff or admin to reject a member request."""
    rejection_reason = StrictCharField(required=False, allow_blank=True, allow_null=True, max_length=500)
