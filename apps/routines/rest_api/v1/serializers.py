import uuid
from rest_framework import serializers

from apps.routines.models import (
    RoutineTemplate,
    RoutineTemplateGoal,
    RoutineTemplateDay,
    RoutineTemplateExercise,
    MemberRoutine,
    MemberRoutineDay,
    MemberRoutineExercise,
)
from common.enums import (
    RoutineFormatEnum,
    RoutineLevelEnum,
    FitnessGoalEnum,
)


class StrictCharField(serializers.CharField):
    """CharField that enforces strict string types, preventing silent coercion of numbers or booleans."""
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError("This field must be a valid string.")
        return super().to_internal_value(data)


# ==============================================================================
# ROUTINE TEMPLATE SERIALIZERS
# ==============================================================================

class RoutineTemplateExerciseSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoutineTemplateExercise
        fields = [
            "id",
            "exercise_name",
            "sets",
            "reps_or_duration",
            "rest_seconds",
            "notes",
            "sort_order",
        ]


class RoutineTemplateDaySerializer(serializers.ModelSerializer):
    exercises = RoutineTemplateExerciseSerializer(many=True, read_only=True)

    class Meta:
        model = RoutineTemplateDay
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


class RoutineTemplateListSerializer(serializers.ModelSerializer):
    goals = serializers.SerializerMethodField()
    created_by_staff_name = serializers.SerializerMethodField()
    days_count = serializers.SerializerMethodField()
    total_exercises_count = serializers.SerializerMethodField()

    class Meta:
        model = RoutineTemplate
        fields = [
            "id",
            "gym_id",
            "template_name",
            "routine_format",
            "level",
            "goals",
            "notes",
            "days_count",
            "total_exercises_count",
            "created_by_staff_id",
            "created_by_staff_name",
            "created_at",
            "updated_at",
        ]

    def get_goals(self, obj) -> list:
        return [g.goal for g in obj.goals.all()]

    def get_created_by_staff_name(self, obj) -> str | None:
        if obj.created_by_staff and obj.created_by_staff.user:
            u = obj.created_by_staff.user
            return f"{u.first_name} {u.last_name}".strip() or u.email
        return None

    def get_days_count(self, obj) -> int:
        if hasattr(obj, "annotated_days_count"):
            return obj.annotated_days_count
        if hasattr(obj, "_prefetched_objects_cache") and "days" in obj._prefetched_objects_cache:
            return len(obj.days.all())
        return obj.days.count() if hasattr(obj, "days") else 0

    def get_total_exercises_count(self, obj) -> int:
        if hasattr(obj, "annotated_exercises_count"):
            return obj.annotated_exercises_count
        if hasattr(obj, "_prefetched_objects_cache") and "days" in obj._prefetched_objects_cache:
            return sum(len(d.exercises.all()) for d in obj.days.all())
        return 0


class RoutineTemplateDetailSerializer(RoutineTemplateListSerializer):
    days = RoutineTemplateDaySerializer(many=True, read_only=True)

    class Meta(RoutineTemplateListSerializer.Meta):
        fields = RoutineTemplateListSerializer.Meta.fields + ["days"]


class ExerciseInputSerializer(serializers.Serializer):
    exercise_name = StrictCharField(max_length=255, required=True)
    sets = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    reps_or_duration = StrictCharField(max_length=100, required=True)
    rest_seconds = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    notes = StrictCharField(required=False, allow_blank=True, allow_null=True)
    sort_order = serializers.IntegerField(required=False, default=0)

    def validate_exercise_name(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("Exercise name cannot be blank.")
        return val

    def validate_reps_or_duration(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("Reps or duration cannot be blank.")
        return val


class DayInputSerializer(serializers.Serializer):
    day_of_week = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=7)
    session_number = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    is_rest_day = serializers.BooleanField(required=False, default=False)
    workout_title = StrictCharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    workday_note = StrictCharField(required=False, allow_blank=True, allow_null=True)
    sort_order = serializers.IntegerField(required=False, default=0)
    exercises = ExerciseInputSerializer(many=True, required=False, default=list)


class RoutineTemplateCreateSerializer(serializers.Serializer):
    template_name = StrictCharField(max_length=255, required=True)
    routine_format = serializers.ChoiceField(
        choices=RoutineFormatEnum.choices,
        default=RoutineFormatEnum.WEEKLY,
    )
    level = serializers.ChoiceField(
        choices=RoutineLevelEnum.choices,
        default=RoutineLevelEnum.BEGINNER,
    )
    notes = StrictCharField(required=False, allow_blank=True, allow_null=True)
    goals = serializers.ListField(
        child=serializers.ChoiceField(choices=FitnessGoalEnum.choices),
        required=False,
        default=list,
    )
    days = DayInputSerializer(many=True, required=False, default=list)

    def validate_template_name(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("Template name cannot be blank.")
        return val


class RoutineTemplateUpdateSerializer(serializers.Serializer):
    template_name = StrictCharField(max_length=255, required=False)
    routine_format = serializers.ChoiceField(choices=RoutineFormatEnum.choices, required=False)
    level = serializers.ChoiceField(choices=RoutineLevelEnum.choices, required=False)
    notes = StrictCharField(required=False, allow_blank=True, allow_null=True)
    goals = serializers.ListField(
        child=serializers.ChoiceField(choices=FitnessGoalEnum.choices),
        required=False,
    )
    days = DayInputSerializer(many=True, required=False)

    def validate_template_name(self, value):
        val = value.strip()
        if not val:
            raise serializers.ValidationError("Template name cannot be blank.")
        return val


# ==============================================================================
# MEMBER ROUTINE SERIALIZERS
# ==============================================================================

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
