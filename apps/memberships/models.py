import uuid
from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError
from common.enums import (
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    PaymentScheduleEnum,
)


class MembershipPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="membership_plans",
        db_index=True,
    )
    # Step 1: Basic Info
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    plan_status = models.CharField(
        max_length=20,
        choices=PlanStatusEnum.choices,
        default=PlanStatusEnum.DRAFT,
        db_index=True,
    )

    # Step 2: Plan Type & Pricing
    plan_type = models.CharField(
        max_length=20,
        choices=PlanTypeEnum.choices,
        db_index=True,
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_value = models.PositiveIntegerField(
        help_text="e.g. 3 for 3 months or 10 for 10 sessions"
    )
    duration_unit = models.CharField(
        max_length=20,
        choices=DurationUnitEnum.choices,
    )

    # Step 3: Payments & Fees
    joining_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    payment_schedule = models.CharField(
        max_length=20,
        choices=PaymentScheduleEnum.choices,
        default=PaymentScheduleEnum.FULL_PAYMENT,
    )
    installment_schedule_config = models.JSONField(
        blank=True,
        null=True,
        help_text="Configuration parameters for installment payments if payment_schedule is instalments",
    )

    # Step 5: Terms & Policies
    cancellation_policy = models.TextField(blank=True, null=True)
    refund_policy = models.TextField(blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "membership_plans"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["gym", "plan_status"]),
            models.Index(fields=["gym", "plan_type"]),
            models.Index(fields=["gym", "-created_at"], name="idx_plan_gym_created"),
            models.Index(fields=["gym", "plan_status", "plan_type"], name="idx_plan_gym_status_type"),
            models.Index(fields=["gym", "name"], name="idx_plan_gym_name"),
        ]

    def clean(self):
        super().clean()
        errors = {}

        # 1. Description validation: min 50 characters if provided
        if self.description:
            desc_stripped = self.description.strip()
            if len(desc_stripped) < 50:
                errors["description"] = "Description must be at least 50 characters long when provided."

        # 2. Plan type and duration unit coherence
        if self.plan_type == PlanTypeEnum.TIME_BASED:
            valid_units = [DurationUnitEnum.DAY, DurationUnitEnum.WEEK, DurationUnitEnum.MONTH]
            if self.duration_unit not in valid_units:
                errors["duration_unit"] = f"For time-based plans, duration unit must be one of: {', '.join(valid_units)}."
        elif self.plan_type == PlanTypeEnum.SESSION_BASED:
            if self.duration_unit != DurationUnitEnum.SESSION:
                errors["duration_unit"] = "For session-based plans, duration unit must be 'session'."

        # 3. Numeric bounds
        if self.price is not None and self.price < Decimal("0.00"):
            errors["price"] = "Price cannot be negative."

        if self.joining_fee is not None and self.joining_fee < Decimal("0.00"):
            errors["joining_fee"] = "Joining fee cannot be negative."

        if self.duration_value is not None and self.duration_value < 1:
            errors["duration_value"] = "Duration value must be at least 1."

        # 4. Payment schedule & installments
        if self.payment_schedule == PaymentScheduleEnum.INSTALMENTS:
            if not self.installment_schedule_config:
                errors["installment_schedule_config"] = "Installment schedule configuration is required when payment schedule is set to 'instalments'."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.get_plan_status_display()}) - {self.gym.name}"


class PlanIncludedAmenities(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plan = models.ForeignKey(
        MembershipPlan,
        on_delete=models.CASCADE,
        related_name="included_amenities",
    )
    gym_amenity = models.ForeignKey(
        "amenities.GymAmenity",
        on_delete=models.CASCADE,
        related_name="plan_inclusions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "plan_included_amenities"
        unique_together = ("plan", "gym_amenity")
        indexes = [
            models.Index(fields=["plan", "gym_amenity"]),
        ]

    def clean(self):
        super().clean()
        # Ensure the amenity belongs to the same gym as the plan
        if self.plan_id and self.gym_amenity_id:
            if self.plan.gym_id != self.gym_amenity.gym_id:
                raise ValidationError("Included amenity must belong to the same gym as the membership plan.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.plan.name} -> {self.gym_amenity.amenity.name}"
