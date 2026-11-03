from rest_framework import serializers
from apps.gyms.models import GymAdminLog
from common.enums import AdminLogCategory, AdminLogActionType


class AdminActorSerializer(serializers.Serializer):
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

    def get_admin(self, obj: GymAdminLog) -> dict:
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


class GymAdminLogCreateSerializer(serializers.Serializer):
    """
    Serializer for creating custom administration logs via API.
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

    def validate_action(self, value):
        cleaned = value.strip() if value else ""
        if not cleaned:
            raise serializers.ValidationError("Action cannot be blank.")
        if "\x00" in value:
            raise serializers.ValidationError("Null characters are not allowed.")
        return cleaned

    def validate_details(self, value):
        if value and "\x00" in value:
            raise serializers.ValidationError("Null characters are not allowed.")
        return value


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

