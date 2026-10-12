from rest_framework import serializers


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
