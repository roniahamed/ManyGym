from rest_framework import serializers
from apps.gyms.models import GymGallery
from common.serializers import StrictCharField
from common.enums import GalleryCategoryEnum, MediaTypeEnum


class GymGalleryItemSerializer(serializers.ModelSerializer):
    resolved_media_url = serializers.CharField(read_only=True)
    resolved_thumbnail_url = serializers.CharField(read_only=True)

    class Meta:
        model = GymGallery
        fields = [
            "id",
            "media_url",
            "original_url",
            "optimized_url",
            "thumbnail_url",
            "resolved_media_url",
            "resolved_thumbnail_url",
            "media_type",
            "category",
            "caption",
            "order_index",
            "processing_status",
            "width",
            "height",
            "size_bytes",
            "optimized_size_bytes",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "original_url",
            "optimized_url",
            "thumbnail_url",
            "resolved_media_url",
            "resolved_thumbnail_url",
            "processing_status",
            "width",
            "height",
            "size_bytes",
            "optimized_size_bytes",
            "created_at",
        ]


class GymGalleryCreateSerializer(serializers.Serializer):
    file = serializers.FileField(required=False, help_text="Direct file upload (picture or video)")
    media_url = StrictCharField(max_length=1000, required=False, help_text="Media URL or local path")
    media_type = serializers.ChoiceField(
        choices=MediaTypeEnum.choices,
        default=MediaTypeEnum.PICTURE,
        required=False,
    )
    category = serializers.ChoiceField(
        choices=GalleryCategoryEnum.choices,
        default=GalleryCategoryEnum.GENERAL,
        required=False,
    )
    caption = StrictCharField(
        max_length=200,
        required=False,
        allow_blank=True,
    )

    def validate(self, attrs):
        if not attrs.get("file") and not attrs.get("media_url"):
            raise serializers.ValidationError("Either 'file' or 'media_url' must be provided.")
        return attrs


class GymGalleryReorderItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(required=True)
    order_index = serializers.IntegerField(required=True, min_value=0)


class GymGalleryReorderSerializer(serializers.Serializer):
    items = serializers.ListField(
        child=GymGalleryReorderItemSerializer(),
        allow_empty=False,
    )
