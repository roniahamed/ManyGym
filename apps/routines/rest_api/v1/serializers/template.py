from rest_framework import serializers

from apps.routines.models import (
    RoutineTemplate,
    RoutineTemplateDay,
    RoutineTemplateExercise,
)
from apps.routines.rest_api.v1.serializers.base import (
    StrictCharField,
    DayInputSerializer,
)
from common.enums import (
    RoutineFormatEnum,
    RoutineLevelEnum,
    FitnessGoalEnum,
)


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
