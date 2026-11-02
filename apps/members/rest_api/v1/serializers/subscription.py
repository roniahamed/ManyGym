import uuid
from decimal import Decimal
from typing import Dict, Any, List, Optional
from django.utils import timezone
from rest_framework import serializers

from apps.members.models import (
    MemberSubscription,
    MemberExtraAmenities,
    MemberPayment,
)
from common.enums import (
    MembershipStatusEnum,
    PaymentStatusEnum,
    PaymentMethodEnum,
)
from common.serializers import (
    StrictCharField,
    StrictUUIDField,
    StrictDecimalField,
)


class MemberExtraAmenitySerializer(serializers.ModelSerializer):
    amenity_id = serializers.UUIDField(source="gym_amenity.id", read_only=True)
    name = serializers.CharField(source="gym_amenity.amenity.name", read_only=True)
    group_name = serializers.CharField(source="gym_amenity.amenity.group_name", read_only=True)

    class Meta:
        model = MemberExtraAmenities
        fields = [
            "id",
            "amenity_id",
            "name",
            "group_name",
            "extra_fee",
            "is_active",
            "created_at",
        ]


class MemberPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MemberPayment
        fields = [
            "id",
            "amount",
            "payment_method",
            "payment_date",
            "is_initial_payment",
            "notes",
            "created_at",
        ]


class MemberSubscriptionDetailSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan_type = serializers.CharField(source="plan.plan_type", read_only=True)
    plan_price = serializers.DecimalField(source="plan.price", max_digits=10, decimal_places=2, read_only=True)
    joining_fee = serializers.DecimalField(source="plan.joining_fee", max_digits=10, decimal_places=2, read_only=True)
    extra_amenities = MemberExtraAmenitySerializer(many=True, read_only=True)
    payments = MemberPaymentSerializer(many=True, read_only=True)
    total_cost = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()

    class Meta:
        model = MemberSubscription
        fields = [
            "id",
            "plan_id",
            "plan_name",
            "plan_type",
            "plan_price",
            "joining_fee",
            "membership_status",
            "payment_status",
            "start_date",
            "end_date",
            "total_sessions",
            "remaining_sessions",
            "total_cost",
            "total_paid",
            "extra_amenities",
            "payments",
            "created_at",
            "updated_at",
        ]

    def get_total_cost(self, obj: MemberSubscription) -> str:
        base = obj.plan.price + obj.plan.joining_fee
        extras = sum(extra.extra_fee for extra in obj.extra_amenities.all() if extra.is_active)
        return str(base + extras)

    def get_total_paid(self, obj: MemberSubscription) -> str:
        paid = sum(p.amount for p in obj.payments.all())
        return str(paid)


class MemberSubscriptionCreateSerializer(serializers.Serializer):
    """
    Validates creation of a new subscription attached to an existing member.
    """
    plan_id = StrictUUIDField(required=True)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False, allow_null=True)
    extra_amenity_ids = serializers.ListField(child=StrictUUIDField(), required=False, default=list)

    initial_payment_amount = StrictDecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True)
    initial_payment_method = serializers.ChoiceField(choices=PaymentMethodEnum.choices, required=False, allow_null=True)
    initial_payment_date = serializers.DateField(required=False, allow_null=True)
    initial_payment_notes = StrictCharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
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


class MemberSubscriptionStatusTransitionSerializer(serializers.Serializer):
    """
    Validates status transition (active, paused, cancelled).
    """
    membership_status = serializers.ChoiceField(choices=MembershipStatusEnum.choices, required=False)
    status = serializers.ChoiceField(choices=MembershipStatusEnum.choices, required=False)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        st = attrs.get("membership_status") or attrs.get("status")
        if not st:
            raise serializers.ValidationError({"membership_status": "Membership status is required."})
        attrs["membership_status"] = st
        return attrs


class MemberPaymentCreateSerializer(serializers.Serializer):
    """
    Validates recording a payment transaction against a subscription.
    """
    amount = StrictDecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=True)
    payment_method = serializers.ChoiceField(choices=PaymentMethodEnum.choices, required=True)
    payment_date = serializers.DateField(required=False)
    notes = StrictCharField(required=False, allow_blank=True, allow_null=True)


class MemberExtraAmenitiesCreateSerializer(serializers.Serializer):
    """
    Validates attaching extra paid amenities.
    """
    amenity_ids = serializers.ListField(child=StrictUUIDField(), required=True)
