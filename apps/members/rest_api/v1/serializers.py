import uuid
from decimal import Decimal
from typing import Dict, Any, List, Optional
from rest_framework import serializers

from apps.members.models import (
    Member,
    MemberSubscription,
    MemberExtraAmenities,
    MemberPayment,
)
from common.enums import (
    MemberJoiningStatus,
    MembershipStatusEnum,
    PaymentStatusEnum,
    PaymentMethodEnum,
)
from common.serializers import (
    StrictCharField,
    StrictUUIDField,
    StrictIntegerField,
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


class MemberListSerializer(serializers.ModelSerializer):
    """
    Summary view for the Member Directory listing table.
    """
    full_name = serializers.CharField(read_only=True)
    current_plan_name = serializers.SerializerMethodField()
    membership_status = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()
    expiry_date = serializers.SerializerMethodField()
    assigned_trainer = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = [
            "id",
            "full_name",
            "first_name",
            "last_name",
            "email",
            "phone",
            "profile_photo_url",
            "joining_status",
            "current_plan_name",
            "membership_status",
            "payment_status",
            "expiry_date",
            "assigned_trainer",
            "created_at",
        ]

    def _get_current_subscription(self, obj: Member) -> Optional[MemberSubscription]:
        # Fast in-memory inspection from prefetched subscriptions with per-instance memoization
        if hasattr(obj, "_cached_curr_sub"):
            return obj._cached_curr_sub
        if hasattr(obj, "_prefetched_objects_cache") and "subscriptions" in obj._prefetched_objects_cache:
            subs = obj._prefetched_objects_cache["subscriptions"]
            sub = subs[0] if subs else None
        else:
            sub = obj.subscriptions.first()
        obj._cached_curr_sub = sub
        return sub

    def get_current_plan_name(self, obj: Member) -> Optional[str]:
        sub = self._get_current_subscription(obj)
        return sub.plan.name if sub else None

    def get_membership_status(self, obj: Member) -> Optional[str]:
        sub = self._get_current_subscription(obj)
        return sub.membership_status if sub else None

    def get_payment_status(self, obj: Member) -> Optional[str]:
        sub = self._get_current_subscription(obj)
        return sub.payment_status if sub else None

    def get_expiry_date(self, obj: Member) -> Optional[str]:
        sub = self._get_current_subscription(obj)
        return str(sub.end_date) if sub else None

    def get_assigned_trainer(self, obj: Member) -> Optional[Dict[str, Any]]:
        if hasattr(obj, "_cached_assigned_trainer_dict"):
            return obj._cached_assigned_trainer_dict
        trainer = obj.assigned_trainer
        if not trainer:
            res = None
        else:
            res = {
                "id": str(trainer.id),
                "name": trainer.user.full_name,
                "email": trainer.user.email,
            }
        obj._cached_assigned_trainer_dict = res
        return res


class MemberDetailSerializer(serializers.ModelSerializer):
    """
    Complete dossier representation of a gym member.
    """
    full_name = serializers.CharField(read_only=True)
    assigned_trainer = serializers.SerializerMethodField()
    active_subscription = serializers.SerializerMethodField()
    subscriptions = MemberSubscriptionDetailSerializer(many=True, read_only=True)

    class Meta:
        model = Member
        fields = [
            "id",
            "gym_id",
            "user_id",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "profile_photo_url",
            "address",
            "city",
            "country",
            "date_of_birth",
            "sex",
            "nationality",
            "emergency_contact_name",
            "emergency_contact_phone",
            "emergency_contact_relationship",
            "joining_status",
            "invitation_sent_at",
            "internal_notes",
            "assigned_trainer",
            "active_subscription",
            "subscriptions",
            "created_at",
            "updated_at",
        ]

    def get_assigned_trainer(self, obj: Member) -> Optional[Dict[str, Any]]:
        trainer = obj.assigned_trainer
        if not trainer:
            return None
        return {
            "id": str(trainer.id),
            "name": trainer.user.full_name,
            "email": trainer.user.email,
        }

    def get_active_subscription(self, obj: Member) -> Optional[Dict[str, Any]]:
        subs = obj.subscriptions.all()
        active = next((s for s in subs if s.membership_status in [MembershipStatusEnum.ACTIVE, MembershipStatusEnum.SCHEDULED]), None)
        if not active and subs:
            active = subs[0]
        return MemberSubscriptionDetailSerializer(active).data if active else None


class MemberCreateSerializer(serializers.Serializer):
    """
    Validates payload for onboarding a new gym member and optional initial subscription.
    """
    first_name = StrictCharField(min_length=1, max_length=100, required=True)
    last_name = StrictCharField(min_length=1, max_length=100, required=True)
    email = serializers.EmailField(max_length=255, required=True)
    phone = StrictCharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    profile_photo_url = StrictCharField(max_length=1000, required=False, allow_blank=True, allow_null=True)
    address = StrictCharField(max_length=500, required=False, allow_blank=True, allow_null=True)
    city = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    country = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    sex = StrictCharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    nationality = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)

    emergency_contact_name = StrictCharField(max_length=150, required=False, allow_blank=True, allow_null=True)
    emergency_contact_phone = StrictCharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    emergency_contact_relationship = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    assigned_trainer_id = StrictUUIDField(required=False, allow_null=True)
    internal_notes = StrictCharField(required=False, allow_blank=True, allow_null=True)

    # Optional initial subscription
    plan_id = StrictUUIDField(required=False, allow_null=True)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    extra_amenity_ids = serializers.ListField(child=StrictUUIDField(), required=False, default=list)

    # Optional initial payment
    initial_payment_amount = StrictDecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"), required=False, allow_null=True)
    initial_payment_method = serializers.ChoiceField(choices=PaymentMethodEnum.choices, required=False, allow_null=True)
    initial_payment_date = serializers.DateField(required=False, allow_null=True)
    initial_payment_notes = StrictCharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        amt = attrs.get("initial_payment_amount")
        method = attrs.get("initial_payment_method")
        if amt and not method:
            raise serializers.ValidationError({
                "initial_payment_method": "Payment method is required when initial payment amount is specified."
            })
        return attrs


class MemberUpdateSerializer(serializers.Serializer):
    """
    Validates partial update of member demographic details or trainer assignment.
    """
    first_name = StrictCharField(min_length=1, max_length=100, required=False)
    last_name = StrictCharField(min_length=1, max_length=100, required=False)
    email = serializers.EmailField(max_length=255, required=False)
    phone = StrictCharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    profile_photo_url = StrictCharField(max_length=1000, required=False, allow_blank=True, allow_null=True)
    address = StrictCharField(max_length=500, required=False, allow_blank=True, allow_null=True)
    city = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    country = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    sex = StrictCharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    nationality = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)

    emergency_contact_name = StrictCharField(max_length=150, required=False, allow_blank=True, allow_null=True)
    emergency_contact_phone = StrictCharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    emergency_contact_relationship = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    assigned_trainer_id = StrictUUIDField(required=False, allow_null=True)
    internal_notes = StrictCharField(required=False, allow_blank=True, allow_null=True)


class MemberAcceptInvitationSerializer(serializers.Serializer):
    """
    Validates token payload for accepting onboarding invite.
    """
    token = StrictCharField(min_length=10, max_length=255, required=False)
    invitation_token = StrictCharField(min_length=10, max_length=255, required=False)

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        tok = attrs.get("token") or attrs.get("invitation_token")
        if not tok:
            raise serializers.ValidationError({"token": "Invitation token is required."})
        attrs["token"] = tok
        return attrs


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
