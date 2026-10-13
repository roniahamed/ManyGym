from rest_framework import serializers
from apps.gyms.models import Gym, GymLocation, GymOpeningHours, GymGallery
from common.enums import (
    GymTypeEnum,
    GymGenderRequired,
    GalleryCategoryEnum,
    MediaTypeEnum,
)


class GymLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GymLocation
        fields = [
            "id",
            "address",
            "latitude",
            "longitude",
            "city",
            "country",
            "postal_code",
            "is_primary",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


class GymOpeningHoursItemSerializer(serializers.ModelSerializer):
    day_name = serializers.CharField(source="get_day_of_week_display", read_only=True)

    class Meta:
        model = GymOpeningHours
        fields = [
            "id",
            "day_of_week",
            "day_name",
            "start_time",
            "end_time",
            "is_closed",
        ]
        read_only_fields = ["id", "day_name"]


class GymOpeningHoursBulkItemSerializer(serializers.Serializer):
    day_of_week = serializers.IntegerField(min_value=0, max_value=6)
    start_time = serializers.TimeField(required=False, allow_null=True)
    end_time = serializers.TimeField(required=False, allow_null=True)
    is_closed = serializers.BooleanField(default=False)


class GymOpeningHoursBulkUpdateSerializer(serializers.Serializer):
    hours = serializers.ListField(
        child=GymOpeningHoursBulkItemSerializer(),
        allow_empty=False,
    )


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
    media_url = serializers.CharField(max_length=1000, required=False, help_text="Media URL or local path")
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
    caption = serializers.CharField(
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


class GymCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=True)
    primary_type = serializers.ChoiceField(
        choices=GymTypeEnum.choices,
        default=GymTypeEnum.GENERAL_FITNESS,
    )
    secondary_type = serializers.ChoiceField(
        choices=GymTypeEnum.choices,
        required=False,
        allow_null=True,
    )
    short_description = serializers.CharField(
        required=False,
        allow_blank=True,
        min_length=120,
    )
    profile_picture_url = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    cover_photo_url = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    gender_required = serializers.ChoiceField(
        choices=GymGenderRequired.choices,
        default=GymGenderRequired.EVERYONE,
    )
    min_age = serializers.IntegerField(default=1, min_value=1, max_value=99)
    timezone = serializers.CharField(default="UTC", max_length=100)
    address = serializers.CharField(required=False, default="Unspecified Location")
    latitude = serializers.DecimalField(max_digits=10, decimal_places=8, default=0.0)
    longitude = serializers.DecimalField(max_digits=11, decimal_places=8, default=0.0)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)
    country = serializers.CharField(required=False, allow_blank=True, max_length=100)
    postal_code = serializers.CharField(required=False, allow_blank=True, max_length=30)


class GymOverviewUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    primary_type = serializers.ChoiceField(choices=GymTypeEnum.choices, required=False)
    secondary_type = serializers.ChoiceField(choices=GymTypeEnum.choices, required=False, allow_null=True)
    short_description = serializers.CharField(required=False, min_length=120)
    profile_picture_url = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    cover_photo_url = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    gender_required = serializers.ChoiceField(choices=GymGenderRequired.choices, required=False)
    min_age = serializers.IntegerField(required=False, min_value=1, max_value=99)
    timezone = serializers.CharField(required=False, max_length=100)


class GymLocationUpdateSerializer(serializers.Serializer):
    address = serializers.CharField(required=True)
    latitude = serializers.DecimalField(max_digits=10, decimal_places=8, required=True)
    longitude = serializers.DecimalField(max_digits=11, decimal_places=8, required=True)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)
    country = serializers.CharField(required=False, allow_blank=True, max_length=100)
    postal_code = serializers.CharField(required=False, allow_blank=True, max_length=30)


class GymDetailSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    opening_hours_count = serializers.SerializerMethodField()
    gallery_count = serializers.SerializerMethodField()
    owner_email = serializers.CharField(source="owner_user.email", read_only=True)

    class Meta:
        model = Gym
        fields = [
            "id",
            "name",
            "owner_email",
            "profile_picture_url",
            "cover_photo_url",
            "short_description",
            "primary_type",
            "secondary_type",
            "gender_required",
            "min_age",
            "timezone",
            "location",
            "opening_hours_count",
            "gallery_count",
            "created_at",
            "updated_at",
        ]

    def get_location(self, obj):
        prefetched = getattr(obj, "prefetched_primary_locations", None)
        if prefetched is not None:
            primary_loc = prefetched[0] if prefetched else None
        else:
            primary_loc = obj.locations.filter(is_primary=True).first()
        return GymLocationSerializer(primary_loc).data if primary_loc else None

    def get_opening_hours_count(self, obj):
        count = getattr(obj, "annotated_opening_hours_count", None)
        if count is not None:
            return count
        return obj.opening_hours.count()

    def get_gallery_count(self, obj):
        count = getattr(obj, "annotated_gallery_count", None)
        if count is not None:
            return count
        return obj.gallery_items.count()
