from rest_framework import serializers


class StrictCharField(serializers.CharField):
    """CharField that enforces strict string types, preventing silent coercion of numbers or booleans."""
    def to_internal_value(self, data):
        if not isinstance(data, str):
            raise serializers.ValidationError("This field must be a valid string.")
        return super().to_internal_value(data)


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
