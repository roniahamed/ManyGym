from rest_framework import serializers

from apps.leads.models import (
    LeadCustomReasons,
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
