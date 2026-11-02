from rest_framework import serializers

from apps.routines.models import (
    MemberRoutine,
    MemberRoutineDay,
    MemberRoutineExercise,
)
from apps.routines.rest_api.v1.serializers.base_serializers import (
    StrictCharField,
    DayInputSerializer,
)
from common.enums import (
    RoutineFormatEnum,
    RoutineLevelEnum,
)


class MemberRoutineExerciseSerializer(serializers.ModelSerializer):
    class Meta:
        model = MemberRoutineExercise
        fields = [
            "id",
            "exercise_name",
            "sets",
            "reps_or_duration",
            "rest_seconds",
            "notes",
            "sort_order",
        ]


class MemberRoutineDaySerializer(serializers.ModelSerializer):
    exercises = MemberRoutineExerciseSerializer(many=True, read_only=True)

    class Meta:
        model = MemberRoutineDay
        fields = [
            "id",
            "day_of_week",
            "session_number",
            "is_rest_day",
            "workout_title",
            "workday_note",
            "sort_order",
            "exercises",
        ]


class MemberRoutineListSerializer(serializers.ModelSerializer):
    prescribed_by_staff_name = serializers.SerializerMethodField()
    source_template_name = serializers.SerializerMethodField()
    days_count = serializers.SerializerMethodField()

    class Meta:
        model = MemberRoutine
        fields = [
            "id",
            "member_id",
            "source_template_id",
            "source_template_name",
            "routine_name",
            "routine_format",
            "level",
            "is_active",
            "notes",
            "days_count",
            "prescribed_by_staff_id",
            "prescribed_by_staff_name",
            "assigned_at",
            "updated_at",
        ]

    def get_prescribed_by_staff_name(self, obj) -> str | None:
        if obj.prescribed_by_staff and obj.prescribed_by_staff.user:
            u = obj.prescribed_by_staff.user
            return f"{u.first_name} {u.last_name}".strip() or u.email
        return None

    def get_source_template_name(self, obj) -> str | None:
        return obj.source_template.template_name if obj.source_template else None

    def get_days_count(self, obj) -> int:
        if hasattr(obj, "annotated_days_count"):
            return obj.annotated_days_count
        if hasattr(obj, "_prefetched_objects_cache") and "days" in obj._prefetched_objects_cache:
            return len(obj.days.all())
        return obj.days.count() if hasattr(obj, "days") else 0


class MemberRoutineDetailSerializer(MemberRoutineListSerializer):
    days = MemberRoutineDaySerializer(many=True, read_only=True)

    class Meta(MemberRoutineListSerializer.Meta):
        fields = MemberRoutineListSerializer.Meta.fields + ["days"]


class MemberRoutineAssignSerializer(serializers.Serializer):
    source_template_id = serializers.UUIDField(required=False, allow_null=True)
    routine_name = StrictCharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    routine_format = serializers.ChoiceField(
        choices=RoutineFormatEnum.choices,
        required=False,
        allow_null=True,
    )
    level = serializers.ChoiceField(
        choices=RoutineLevelEnum.choices,
        required=False,
        allow_null=True,
    )
    notes = StrictCharField(required=False, allow_blank=True, allow_null=True)
    days = DayInputSerializer(many=True, required=False)

    def validate(self, attrs):
        source_template_id = attrs.get("source_template_id")
        routine_name = (attrs.get("routine_name") or "").strip()

        if not source_template_id and not routine_name:
            raise serializers.ValidationError(
                "Either a source_template_id or a routine_name must be provided to prescribe a routine."
            )
        return attrs


class MemberRoutineUpdateSerializer(serializers.Serializer):
    routine_name = StrictCharField(max_length=255, required=False)
    level = serializers.ChoiceField(choices=RoutineLevelEnum.choices, required=False)
    notes = StrictCharField(required=False, allow_blank=True, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    days = DayInputSerializer(many=True, required=False)

    def validate_routine_name(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("Routine name cannot be blank.")
        return val
