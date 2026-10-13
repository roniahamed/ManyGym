import uuid
from rest_framework import serializers


class StrictCharField(serializers.CharField):
    """CharField that rejects non-string types such as integers, booleans, or lists."""
    def to_internal_value(self, data):
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class StrictUUIDField(serializers.UUIDField):
    """UUIDField that strictly requires string UUID representation, rejecting integers or booleans."""
    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (str, uuid.UUID)):
            self.fail("invalid")
        return super().to_internal_value(data)


class ErrorDetailSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Machine-readable error code", default="VALIDATION_ERROR")
    message = serializers.CharField(help_text="Human-readable explanation of the error")
    details = serializers.DictField(
        help_text="Field-specific validation errors or context dictionary",
        default=dict,
        required=False,
    )


class MessageResponseSerializer(serializers.Serializer):
    message = serializers.CharField(help_text="Operation feedback message")

