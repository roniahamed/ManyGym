import uuid
from typing import Optional, Dict, Any
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from rest_framework import serializers

from apps.gyms.models import GymAdminLog
from common.enums import AdminLogCategory, AdminLogActionType


class AdminActorSerializer(serializers.Serializer):
    """
    Representation of the administrator or staff member who performed an action.
    """
    id = serializers.UUIDField(allow_null=True)
    full_name = serializers.CharField(allow_blank=True)
    email = serializers.EmailField(allow_blank=True)
    avatar_url = serializers.CharField(allow_null=True, required=False)


class GymAdminLogSerializer(serializers.ModelSerializer):
    """
    Representation of an administration audit log record matching the UI specification:
    - Admin: actor information (name, avatar, email)
    - Action: human-readable action label
    - Details: specific context / diff
    - Date and time: formatted and raw timestamps
    """
    admin = serializers.SerializerMethodField()
    admin_name = serializers.CharField(source="actor_name", read_only=True)
    category_display = serializers.CharField(source="get_category_display", read_only=True)
    date_and_time = serializers.DateTimeField(source="created_at", read_only=True)
    formatted_date_time = serializers.SerializerMethodField()

    class Meta:
        model = GymAdminLog
        fields = [
            "id",
            "admin",
            "admin_name",
            "action",
            "action_type",
            "category",
            "category_display",
            "details",
            "target_type",
            "target_id",
            "metadata",
            "date_and_time",
            "formatted_date_time",
        ]
        read_only_fields = fields

    def get_admin(self, obj: GymAdminLog) -> Dict[str, Any]:
        actor = obj.actor
        if actor:
            profile = getattr(actor, "profile", None)
            avatar_url = getattr(profile, "avatar_url", None) if profile else None
            first = getattr(actor, "first_name", "") or ""
            last = getattr(actor, "last_name", "") or ""
            full_name = f"{first} {last}".strip() or obj.actor_name or actor.email
            return {
                "id": actor.id,
                "full_name": full_name,
                "email": actor.email,
                "avatar_url": avatar_url,
            }
        return {
            "id": None,
            "full_name": obj.actor_name or "System",
            "email": obj.actor_email or "",
            "avatar_url": None,
        }

    def get_formatted_date_time(self, obj: GymAdminLog) -> str:
        return obj.formatted_date_time


class SanitizedCharField(serializers.CharField):
    """
    CharField that safely strips NUL bytes (\\x00) before validation,
    preventing PostgreSQL DataError crashes while preserving valid search/filter tokens.
    """
    def to_internal_value(self, data):
        if isinstance(data, str):
            data = data.replace("\x00", "")
        return super().to_internal_value(data)


class GymAdminLogsFilterSerializer(serializers.Serializer):
    """
    Validates and normalizes query parameters for filtering, searching,
    and paginating Gym Admin Logs.
    """
    gym_id = serializers.UUIDField(required=False, allow_null=True)
    category = SanitizedCharField(max_length=50, required=False, allow_blank=True)
    action_type = SanitizedCharField(max_length=100, required=False, allow_blank=True)
    actor_id = SanitizedCharField(max_length=100, required=False, allow_blank=True)
    start_date = SanitizedCharField(max_length=100, required=False, allow_blank=True)
    end_date = SanitizedCharField(max_length=100, required=False, allow_blank=True)
    search = SanitizedCharField(max_length=255, required=False, allow_blank=True)
    page = serializers.IntegerField(required=False, default=1)
    page_size = serializers.IntegerField(required=False, default=20)

    def validate_category(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = value.strip().replace("\x00", "")
        return cleaned or None

    def validate_action_type(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = value.strip().replace("\x00", "")
        return cleaned or None

    def validate_actor_id(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = value.strip().replace("\x00", "")
        if not cleaned:
            return None
        try:
            uuid.UUID(cleaned)
        except (ValueError, TypeError):
            raise serializers.ValidationError("Invalid actor_id UUID.")
        return cleaned

    def validate_start_date(self, value: Optional[str]):
        if not value:
            return None
        cleaned = value.strip().replace("\x00", "")
        if not cleaned:
            return None
        try:
            parsed = parse_datetime(cleaned) or parse_date(cleaned)
        except (ValueError, TypeError, OverflowError):
            raise serializers.ValidationError("Invalid start_date format. Expected ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).")
        if not parsed:
            raise serializers.ValidationError("Invalid start_date format. Expected ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).")
        if not hasattr(parsed, "hour"):
            parsed = timezone.datetime.combine(
                parsed,
                timezone.datetime.min.time(),
                tzinfo=timezone.get_current_timezone(),
            )
        return parsed

    def validate_end_date(self, value: Optional[str]):
        if not value:
            return None
        cleaned = value.strip().replace("\x00", "")
        if not cleaned:
            return None
        try:
            parsed = parse_datetime(cleaned) or parse_date(cleaned)
        except (ValueError, TypeError, OverflowError):
            raise serializers.ValidationError("Invalid end_date format. Expected ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).")
        if not parsed:
            raise serializers.ValidationError("Invalid end_date format. Expected ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).")
        if not hasattr(parsed, "hour"):
            parsed = timezone.datetime.combine(
                parsed,
                timezone.datetime.max.time(),
                tzinfo=timezone.get_current_timezone(),
            )
        return parsed

    def validate_search(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = value.replace("\x00", "").strip()
        return cleaned or None

    def validate_page(self, value: Any) -> int:
        try:
            val = int(value)
        except (ValueError, TypeError, OverflowError):
            return 1
        return max(1, min(val, 100_000))

    def validate_page_size(self, value: Any) -> int:
        try:
            val = int(value)
        except (ValueError, TypeError, OverflowError):
            return 20
        return max(1, min(val, 100))


class GymAdminLogsExportFilterSerializer(GymAdminLogsFilterSerializer):
    """
    Validates query parameters for exporting Admin Logs as CSV or JSON.
    """
    format = serializers.CharField(required=False, default="csv")

    def validate_format(self, value: str) -> str:
        cleaned = (value or "csv").strip().lower()
        if cleaned not in ["csv", "json"]:
            raise serializers.ValidationError(
                f"Unsupported export format '{cleaned}'. Supported formats: 'csv', 'json'."
            )
        return cleaned


class GymAdminLogCreateSerializer(serializers.Serializer):
    """
    Serializer for recording custom administration logs via API.
    """
    action = serializers.CharField(max_length=255, required=True)
    action_type = serializers.ChoiceField(
        choices=AdminLogActionType.choices,
        default=AdminLogActionType.CUSTOM_ACTION,
        required=False,
    )
    category = serializers.ChoiceField(
        choices=AdminLogCategory.choices,
        default=AdminLogCategory.GENERAL,
        required=False,
    )
    details = serializers.CharField(allow_blank=True, required=False, default="")
    target_type = serializers.CharField(max_length=100, allow_null=True, required=False, default=None)
    target_id = serializers.CharField(max_length=100, allow_null=True, required=False, default=None)
    metadata = serializers.DictField(required=False, default=dict)

    def validate_action(self, value: str) -> str:
        if not isinstance(value, str):
            value = str(value)
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Action cannot be blank.")
        if "\x00" in value:
            raise serializers.ValidationError("Null characters are not allowed.")
        return cleaned

    def validate_details(self, value: Optional[str]) -> str:
        if value and "\x00" in value:
            raise serializers.ValidationError("Null characters are not allowed.")
        return value or ""


class GymAdminLogsPaginatedResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()
    results = GymAdminLogSerializer(many=True)


class GymAdminLogsMetricsSerializer(serializers.Serializer):
    total_logs = serializers.IntegerField()
    logs_today = serializers.IntegerField()
    by_category = serializers.DictField(child=serializers.IntegerField())
    recent_logs = GymAdminLogSerializer(many=True)


class KeyValueOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class AdminLogOptionsResponseSerializer(serializers.Serializer):
    categories = KeyValueOptionSerializer(many=True)
    action_types = KeyValueOptionSerializer(many=True)
