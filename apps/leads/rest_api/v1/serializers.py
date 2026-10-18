import uuid
from decimal import Decimal
from rest_framework import serializers

from common.enums import (
    LeadStageEnum,
    NotJoiningReasonStandard,
    LeadSourceEnum,
    FitnessGoalEnum,
    PaymentMethodEnum,
)
from apps.leads.models import (
    Lead,
    LeadCustomReasons,
    LeadFitnessGoals,
    LeadNextMove,
    LeadNotes,
)


class StrictCharField(serializers.CharField):
    """CharField that enforces strict string types, preventing silent coercion of numbers or booleans."""
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError("This field must be a valid string.")
        return super().to_internal_value(data)


class LeadCustomReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadCustomReasons
        fields = ["id", "gym_id", "reason_name", "created_at"]
        read_only_fields = ["id", "gym_id", "created_at"]


class LeadCustomReasonCreateSerializer(serializers.Serializer):
    reason_name = StrictCharField(max_length=255, required=True)

    def validate_reason_name(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("Reason name cannot be blank.")
        return val


class LeadNextMoveSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeadNextMove
        fields = ["id", "lead_id", "scheduled_date", "short_description", "is_completed", "created_at"]
        read_only_fields = ["id", "lead_id", "created_at"]


class LeadNextMoveCreateSerializer(serializers.Serializer):
    scheduled_date = serializers.DateField(required=True)
    short_description = StrictCharField(max_length=255, required=True)

    def validate_short_description(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("Description cannot be blank.")
        return val


class LeadNextMoveUpdateSerializer(serializers.Serializer):
    is_completed = serializers.BooleanField(required=False)
    scheduled_date = serializers.DateField(required=False)
    short_description = StrictCharField(max_length=255, required=False)

    def validate_short_description(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("Description cannot be blank.")
        return val


class LeadNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = LeadNotes
        fields = ["id", "lead_id", "author_staff_id", "author_name", "note_text", "created_at"]
        read_only_fields = ["id", "lead_id", "author_staff_id", "author_name", "created_at"]

    def get_author_name(self, obj) -> str:
        if obj.author_staff and obj.author_staff.user:
            u = obj.author_staff.user
            return f"{u.first_name} {u.last_name}".strip() or u.email
        return "Gym Staff"


class LeadNoteCreateSerializer(serializers.Serializer):
    note_text = StrictCharField(required=True)
    author_staff_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_note_text(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("Note text cannot be empty.")
        return val


class LeadListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    interested_plan = serializers.SerializerMethodField()
    assigned_staff = serializers.SerializerMethodField()
    converted_member = serializers.SerializerMethodField()
    not_joining_custom_reason = serializers.SerializerMethodField()
    fitness_goals = serializers.SerializerMethodField()
    pending_next_moves_count = serializers.SerializerMethodField()

    class Meta:
        model = Lead
        fields = [
            "id",
            "gym_id",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "email",
            "stage",
            "source",
            "expected_start_date",
            "trial_booked_at",
            "not_joining_reason_standard",
            "not_joining_custom_reason",
            "interested_plan",
            "assigned_staff",
            "converted_member",
            "fitness_goals",
            "pending_next_moves_count",
            "created_at",
            "updated_at",
        ]

    def get_interested_plan(self, obj):
        if obj.interested_plan:
            return {"id": str(obj.interested_plan.id), "name": obj.interested_plan.name}
        return None

    def get_assigned_staff(self, obj):
        if obj.assigned_staff and obj.assigned_staff.user:
            u = obj.assigned_staff.user
            name = f"{u.first_name} {u.last_name}".strip() or u.email
            return {"id": str(obj.assigned_staff.id), "name": name}
        return None

    def get_converted_member(self, obj):
        if obj.converted_member:
            return {
                "id": str(obj.converted_member.id),
                "full_name": obj.converted_member.full_name,
            }
        return None

    def get_not_joining_custom_reason(self, obj):
        if obj.not_joining_custom_reason:
            return {
                "id": str(obj.not_joining_custom_reason.id),
                "reason_name": obj.not_joining_custom_reason.reason_name,
            }
        return None

    def get_fitness_goals(self, obj) -> list:
        # Relies on prefetch_related("fitness_goals")
        return [fg.goal for fg in obj.fitness_goals.all()]

    def get_pending_next_moves_count(self, obj) -> int:
        if hasattr(obj, "annotated_pending_moves"):
            return obj.annotated_pending_moves
        if hasattr(obj, "_prefetched_objects_cache") and "next_moves" in obj._prefetched_objects_cache:
            return sum(1 for nm in obj.next_moves.all() if not nm.is_completed)
        return obj.next_moves.filter(is_completed=False).count()


class LeadDetailSerializer(LeadListSerializer):
    next_moves = LeadNextMoveSerializer(many=True, read_only=True)
    notes = LeadNoteSerializer(many=True, read_only=True)

    class Meta(LeadListSerializer.Meta):
        fields = LeadListSerializer.Meta.fields + ["next_moves", "notes"]


class LeadCreateSerializer(serializers.Serializer):
    first_name = StrictCharField(max_length=100, required=True)
    last_name = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    phone = StrictCharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    email = serializers.EmailField(max_length=255, required=False, allow_blank=True, allow_null=True)
    interested_plan_id = serializers.UUIDField(required=False, allow_null=True)
    assigned_staff_id = serializers.UUIDField(required=False, allow_null=True)
    source = serializers.ChoiceField(choices=LeadSourceEnum.choices, default=LeadSourceEnum.WALK_IN)
    stage = serializers.ChoiceField(choices=LeadStageEnum.choices, default=LeadStageEnum.NEW)
    expected_start_date = serializers.DateField(required=False, allow_null=True)
    trial_booked_at = serializers.DateTimeField(required=False, allow_null=True)
    not_joining_reason_standard = serializers.ChoiceField(
        choices=NotJoiningReasonStandard.choices,
        required=False,
        allow_null=True,
    )
    not_joining_custom_reason_id = serializers.UUIDField(required=False, allow_null=True)
    fitness_goals = serializers.ListField(
        child=serializers.ChoiceField(choices=FitnessGoalEnum.choices),
        required=False,
        default=list,
    )
    initial_note = StrictCharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, attrs):
        phone = (attrs.get("phone") or "").strip()
        email = (attrs.get("email") or "").strip()
        if not phone and not email:
            raise serializers.ValidationError("At least one contact method (phone or email) is required.")

        stage = attrs.get("stage", LeadStageEnum.NEW)
        if stage == LeadStageEnum.NOT_JOINING:
            if not attrs.get("not_joining_reason_standard") and not attrs.get("not_joining_custom_reason_id"):
                raise serializers.ValidationError(
                    "A standard reason or custom gym reason is required when lead is marked as 'not_joining'."
                )
        return attrs


class LeadUpdateSerializer(serializers.Serializer):
    first_name = StrictCharField(max_length=100, required=False)
    last_name = StrictCharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    phone = StrictCharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    email = serializers.EmailField(max_length=255, required=False, allow_blank=True, allow_null=True)
    interested_plan_id = serializers.UUIDField(required=False, allow_null=True)
    assigned_staff_id = serializers.UUIDField(required=False, allow_null=True)
    source = serializers.ChoiceField(choices=LeadSourceEnum.choices, required=False)
    stage = serializers.ChoiceField(choices=LeadStageEnum.choices, required=False)
    expected_start_date = serializers.DateField(required=False, allow_null=True)
    trial_booked_at = serializers.DateTimeField(required=False, allow_null=True)
    not_joining_reason_standard = serializers.ChoiceField(
        choices=NotJoiningReasonStandard.choices,
        required=False,
        allow_null=True,
    )
    not_joining_custom_reason_id = serializers.UUIDField(required=False, allow_null=True)
    fitness_goals = serializers.ListField(
        child=serializers.ChoiceField(choices=FitnessGoalEnum.choices),
        required=False,
    )


class LeadStageUpdateSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=LeadStageEnum.choices, required=True)
    not_joining_reason_standard = serializers.ChoiceField(
        choices=NotJoiningReasonStandard.choices,
        required=False,
        allow_null=True,
    )
    not_joining_custom_reason_id = serializers.UUIDField(required=False, allow_null=True)
    custom_reason_name = StrictCharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    trial_booked_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        stage = attrs.get("stage")
        if stage == LeadStageEnum.NOT_JOINING:
            if (
                not attrs.get("not_joining_reason_standard")
                and not attrs.get("not_joining_custom_reason_id")
                and not attrs.get("custom_reason_name")
            ):
                raise serializers.ValidationError(
                    "A standard reason or custom gym reason must be provided when stage is marked as 'not_joining'."
                )
        return attrs


class LeadConvertToMemberSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField(required=False, allow_null=True)
    last_name = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    member_email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    assigned_trainer_id = serializers.UUIDField(required=False, allow_null=True)
    start_date = serializers.DateField(required=False, allow_null=True)
    end_date = serializers.DateField(required=False, allow_null=True)
    extra_amenity_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
    )
    initial_payment_amount = serializers.DecimalField(
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
    initial_payment_notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    sex = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)
    nationality = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    emergency_contact_name = serializers.CharField(max_length=150, required=False, allow_blank=True, allow_null=True)
    emergency_contact_phone = serializers.CharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    emergency_contact_relationship = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    address = serializers.CharField(max_length=500, required=False, allow_blank=True, allow_null=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    country = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)


class LeadMetricsSerializer(serializers.Serializer):
    total_leads = serializers.IntegerField()
    new = serializers.IntegerField()
    contacted = serializers.IntegerField()
    visit_trial_booked = serializers.IntegerField()
    joined = serializers.IntegerField()
    not_joining = serializers.IntegerField()
    conversion_rate_percentage = serializers.FloatField()
    pending_next_moves_count = serializers.IntegerField()


class ReasonsDirectorySerializer(serializers.Serializer):
    standard_reasons = serializers.ListField(child=serializers.DictField())
    custom_reasons = LeadCustomReasonSerializer(many=True)
