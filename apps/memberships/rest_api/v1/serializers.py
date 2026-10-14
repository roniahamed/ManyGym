import uuid
from decimal import Decimal
from typing import Dict, Any, List
from rest_framework import serializers
from apps.memberships.models import MembershipPlan, PlanIncludedAmenities
from common.enums import (
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    PaymentScheduleEnum,
)
from common.serializers import StrictCharField, StrictUUIDField


class PlanIncludedAmenitySerializer(serializers.ModelSerializer):
    """
    Representation of an amenity bundled into a membership plan.
    """
    id = serializers.UUIDField(source="gym_amenity.id", read_only=True)
    catalog_id = serializers.UUIDField(source="gym_amenity.amenity.id", read_only=True)
    name = serializers.CharField(source="gym_amenity.amenity.name", read_only=True)
    group = serializers.CharField(source="gym_amenity.amenity.group_name", read_only=True)
    group_name = serializers.CharField(source="gym_amenity.amenity.group_name", read_only=True)
    is_paid = serializers.BooleanField(source="gym_amenity.is_paid", read_only=True)
    is_free = serializers.SerializerMethodField()
    price = serializers.DecimalField(
        source="gym_amenity.default_price",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = PlanIncludedAmenities
        fields = ["id", "catalog_id", "name", "group", "group_name", "is_paid", "is_free", "price"]

    def get_is_free(self, obj) -> bool:
        return not obj.gym_amenity.is_paid


class MembershipPlanListSerializer(serializers.ModelSerializer):
    """
    Summary view of a membership plan for directory listings.
    """
    duration_display = serializers.SerializerMethodField()
    included_amenities_count = serializers.SerializerMethodField()

    class Meta:
        model = MembershipPlan
        fields = [
            "id",
            "name",
            "description",
            "plan_status",
            "plan_type",
            "price",
            "duration_value",
            "duration_unit",
            "duration_display",
            "joining_fee",
            "payment_schedule",
            "included_amenities_count",
            "created_at",
            "updated_at",
        ]

    def get_duration_display(self, obj: MembershipPlan) -> str:
        val = obj.duration_value
        unit = obj.duration_unit
        if val > 1 and not unit.endswith("s"):
            unit_display = f"{unit}s"
        else:
            unit_display = unit
        return f"{val} {unit_display.capitalize()}"

    def get_included_amenities_count(self, obj: MembershipPlan) -> int:
        # 1. Direct SQL aggregation annotation
        annotated = getattr(obj, "annotated_amenities_count", None)
        if annotated is not None:
            return annotated
        # 2. In-memory prefetch cache inspection (avoids extra query)
        if hasattr(obj, "_prefetched_objects_cache") and "included_amenities" in obj._prefetched_objects_cache:
            return len(obj._prefetched_objects_cache["included_amenities"])
        # 3. Fallback
        return obj.included_amenities.count()


class MembershipPlanDetailSerializer(serializers.ModelSerializer):
    """
    Full 5-step details of a membership plan, including bundled amenities.
    """
    duration_display = serializers.SerializerMethodField()
    included_amenities = PlanIncludedAmenitySerializer(many=True, read_only=True)
    included_amenity_ids = serializers.SerializerMethodField()

    class Meta:
        model = MembershipPlan
        fields = [
            "id",
            "gym_id",
            "name",
            "description",
            "plan_status",
            "plan_type",
            "price",
            "duration_value",
            "duration_unit",
            "duration_display",
            "joining_fee",
            "payment_schedule",
            "installment_schedule_config",
            "included_amenities",
            "included_amenity_ids",
            "cancellation_policy",
            "refund_policy",
            "created_at",
            "updated_at",
        ]

    def get_duration_display(self, obj: MembershipPlan) -> str:
        val = obj.duration_value
        unit = obj.duration_unit
        if val > 1 and not unit.endswith("s"):
            unit_display = f"{unit}s"
        else:
            unit_display = unit
        return f"{val} {unit_display.capitalize()}"

    def get_included_amenity_ids(self, obj: MembershipPlan) -> List[str]:
        return [str(link.gym_amenity_id) for link in obj.included_amenities.all()]


class MembershipPlanCreateSerializer(serializers.Serializer):
    """
    Validates payload for creating a 5-step membership plan.
    """
    name = StrictCharField(min_length=2, max_length=255, required=True)
    description = StrictCharField(required=False, allow_blank=True, allow_null=True)
    plan_status = serializers.ChoiceField(
        choices=PlanStatusEnum.choices,
        default=PlanStatusEnum.DRAFT,
        required=False,
    )
    plan_type = serializers.ChoiceField(
        choices=PlanTypeEnum.choices,
        required=True,
    )
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=True,
    )
    duration_value = serializers.IntegerField(min_value=1, required=True)
    duration_unit = serializers.ChoiceField(
        choices=DurationUnitEnum.choices,
        required=True,
    )
    joining_fee = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
        default=Decimal("0.00"),
        required=False,
    )
    payment_schedule = serializers.ChoiceField(
        choices=PaymentScheduleEnum.choices,
        default=PaymentScheduleEnum.FULL_PAYMENT,
        required=False,
    )
    installment_schedule_config = serializers.JSONField(
        required=False,
        allow_null=True,
    )
    cancellation_policy = StrictCharField(required=False, allow_blank=True, allow_null=True)
    refund_policy = StrictCharField(required=False, allow_blank=True, allow_null=True)
    included_amenity_ids = serializers.ListField(
        child=StrictUUIDField(),
        required=False,
        default=list,
    )

    def validate_description(self, value: str) -> str:
        if value:
            stripped = value.strip()
            if stripped and len(stripped) < 50:
                raise serializers.ValidationError("Description must be at least 50 characters long when provided.")
            return stripped
        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        plan_type = attrs.get("plan_type")
        duration_unit = attrs.get("duration_unit")

        if plan_type == PlanTypeEnum.TIME_BASED:
            valid_units = [DurationUnitEnum.DAY, DurationUnitEnum.WEEK, DurationUnitEnum.MONTH]
            if duration_unit not in valid_units:
                raise serializers.ValidationError({
                    "duration_unit": f"For time-based plans, duration unit must be one of: {', '.join(valid_units)}."
                })
        elif plan_type == PlanTypeEnum.SESSION_BASED:
            if duration_unit != DurationUnitEnum.SESSION:
                raise serializers.ValidationError({
                    "duration_unit": "For session-based plans, duration unit must be 'session'."
                })

        payment_schedule = attrs.get("payment_schedule", PaymentScheduleEnum.FULL_PAYMENT)
        installment_config = attrs.get("installment_schedule_config")
        if payment_schedule == PaymentScheduleEnum.INSTALMENTS and not installment_config:
            raise serializers.ValidationError({
                "installment_schedule_config": "Installment schedule configuration is required when payment schedule is 'instalments'."
            })

        return attrs


class MembershipPlanUpdateSerializer(serializers.Serializer):
    """
    Validates payload for updating an existing membership plan.
    """
    name = StrictCharField(min_length=2, max_length=255, required=False)
    description = StrictCharField(required=False, allow_blank=True, allow_null=True)
    plan_status = serializers.ChoiceField(
        choices=PlanStatusEnum.choices,
        required=False,
    )
    plan_type = serializers.ChoiceField(
        choices=PlanTypeEnum.choices,
        required=False,
    )
    price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
    )
    duration_value = serializers.IntegerField(min_value=1, required=False)
    duration_unit = serializers.ChoiceField(
        choices=DurationUnitEnum.choices,
        required=False,
    )
    joining_fee = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.00"),
        required=False,
    )
    payment_schedule = serializers.ChoiceField(
        choices=PaymentScheduleEnum.choices,
        required=False,
    )
    installment_schedule_config = serializers.JSONField(
        required=False,
        allow_null=True,
    )
    cancellation_policy = StrictCharField(required=False, allow_blank=True, allow_null=True)
    refund_policy = StrictCharField(required=False, allow_blank=True, allow_null=True)
    included_amenity_ids = serializers.ListField(
        child=StrictUUIDField(),
        required=False,
    )

    def validate_description(self, value: str) -> str:
        if value is not None:
            stripped = value.strip()
            if stripped and len(stripped) < 50:
                raise serializers.ValidationError("Description must be at least 50 characters long when provided.")
            return stripped
        return value


class PlanStatusTransitionSerializer(serializers.Serializer):
    """
    Validates status transition (draft, active, archived).
    """
    plan_status = serializers.ChoiceField(choices=PlanStatusEnum.choices, required=True)


class PlanSyncAmenitiesSerializer(serializers.Serializer):
    """
    Validates bulk synchronization of included amenities.
    """
    amenity_ids = serializers.ListField(child=StrictUUIDField(), required=True)
