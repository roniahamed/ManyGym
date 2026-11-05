from rest_framework import serializers
from apps.access_control.models import Permission, Role, GymStaffAssignment
from apps.users.rest_api.v1.serializers import UserSerializer
from common.enums import StaffStatus
from common.serializers import StrictCharField, StrictUUIDField


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "topic", "scope_code", "name", "description"]


class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)
    gym_id = serializers.UUIDField(source="gym.id", read_only=True, allow_null=True)

    class Meta:
        model = Role
        fields = [
            "id",
            "name",
            "slug",
            "is_custom",
            "description",
            "gym_id",
            "permissions",
            "created_at",
        ]


class CreateCustomRoleSerializer(serializers.Serializer):
    name = StrictCharField(required=True, max_length=100)
    description = StrictCharField(required=False, allow_blank=True)
    permission_ids = serializers.ListField(
        child=StrictUUIDField(),
        required=False,
        default=list,
    )


class UpdateCustomRoleSerializer(serializers.Serializer):
    name = StrictCharField(required=False, max_length=100)
    description = StrictCharField(required=False, allow_blank=True)
    permission_ids = serializers.ListField(
        child=StrictUUIDField(),
        required=False,
    )


class StaffAssignmentSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    role = RoleSerializer(read_only=True)
    gym_id = serializers.UUIDField(source="gym.id", read_only=True)

    class Meta:
        model = GymStaffAssignment
        fields = [
            "id",
            "user",
            "gym_id",
            "role",
            "status",
            "invited_at",
            "joined_at",
        ]


class InviteStaffSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    role_id = StrictUUIDField(required=True)


class UpdateStaffStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=StaffStatus.choices, required=False, help_text="Staff assignment status ('active' or 'inactive').")
    role_id = StrictUUIDField(required=False, help_text="New Role UUID to reassign to this staff member.")

    def validate(self, attrs):
        if not attrs.get("status") and not attrs.get("role_id"):
            raise serializers.ValidationError("At least one of 'status' or 'role_id' must be provided.")
        return attrs

