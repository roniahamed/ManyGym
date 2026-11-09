from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from common.serializers import StrictCharField, AbsoluteMediaURLField
from common.enums import GymTypeEnum
from apps.gyms.rest_api.v1.serializers.profile_serializers import (
    GymLocationSerializer,
    GymOpeningHoursItemSerializer,
)


class GymSearchQuerySerializer(serializers.Serializer):
    """
    Validates query parameters for searching nearby gyms.
    Supports either live location coordinates with radius (default 20 km) OR city selection,
    along with category filtering and keyword search.
    """
    latitude = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=-90.0,
        max_value=90.0,
        help_text="User's live latitude from browser Geolocation API (-90.0 to 90.0).",
    )
    longitude = serializers.FloatField(
        required=False,
        allow_null=True,
        min_value=-180.0,
        max_value=180.0,
        help_text="User's live longitude from browser Geolocation API (-180.0 to 180.0).",
    )
    radius = serializers.FloatField(
        required=False,
        default=20.0,
        min_value=0.1,
        max_value=500.0,
        help_text="Search radius in kilometers. Defaults to 20 km.",
    )
    category = serializers.ChoiceField(
        choices=GymTypeEnum.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Filter gyms by fitness category (matches primary or secondary type).",
    )
    city = StrictCharField(
        required=False,
        allow_blank=True,
        max_length=100,
        help_text="Filter gyms by city name (e.g. Dhaka, New York, London).",
    )
    search = StrictCharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Keyword search matching gym name, description, address, or city.",
    )
    q = StrictCharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Alias for search keyword.",
    )

    def validate(self, attrs):
        lat = attrs.get("latitude")
        lon = attrs.get("longitude")

        if (lat is not None and lon is None) or (lat is None and lon is not None):
            raise serializers.ValidationError(
                {"coordinates": "Both 'latitude' and 'longitude' must be provided together for live location radius search."}
            )

        # Consolidate 'q' into 'search' if search is not explicitly given
        if not attrs.get("search") and attrs.get("q"):
            attrs["search"] = attrs["q"]

        return attrs


class GymSearchItemSerializer(serializers.Serializer):
    """
    Projection serializer for gym listings in nearby / area search results.
    Includes primary location coordinates, computed distance, open status, and amenities preview.
    """
    id = serializers.UUIDField()
    name = serializers.CharField()
    profile_picture_url = AbsoluteMediaURLField(allow_null=True)
    cover_photo_url = AbsoluteMediaURLField(allow_null=True)
    short_description = serializers.CharField(allow_null=True)
    primary_type = serializers.CharField()
    primary_type_display = serializers.CharField()
    secondary_type = serializers.CharField(allow_null=True)
    secondary_type_display = serializers.CharField(allow_null=True)
    gender_required = serializers.CharField()
    gender_required_display = serializers.CharField()
    min_age = serializers.IntegerField()
    timezone = serializers.CharField()
    location = GymLocationSerializer(allow_null=True)
    distance_km = serializers.FloatField(
        allow_null=True,
        help_text="Computed distance in kilometers from user's live coordinates (null if searched by city without coordinates).",
    )
    is_open_now = serializers.BooleanField(help_text="Whether gym is currently open based on operating schedule.")
    today_opening_hours = serializers.CharField(help_text="Operating hours string for today (e.g. '08:00 - 20:00' or 'Closed').")
    amenities_preview = serializers.ListField(
        child=serializers.CharField(),
        help_text="Prominent amenities available at this gym.",
    )
    followers_count = serializers.IntegerField(help_text="Total active followers of this gym.")
    is_following = serializers.BooleanField(help_text="Whether the requesting user currently follows this gym.")
    created_at = serializers.DateTimeField()


class GymOwnerPublicSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class GymTodayStatusSerializer(serializers.Serializer):
    is_open_now = serializers.BooleanField()
    today_hours = serializers.CharField()


class GymAmenityItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    amenity_id = serializers.CharField()
    name = serializers.CharField()
    group_name = serializers.CharField()
    group_display = serializers.CharField()
    is_paid = serializers.BooleanField()
    default_price = serializers.CharField()


class GymAmenitiesBreakdownSerializer(serializers.Serializer):
    free_amenities = GymAmenityItemSerializer(many=True)
    paid_amenities = GymAmenityItemSerializer(many=True)
    total_count = serializers.IntegerField()


class GymGalleryItemDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    media_url = AbsoluteMediaURLField()
    media_type = serializers.CharField()
    category = serializers.CharField()
    category_display = serializers.CharField()
    caption = serializers.CharField(allow_null=True)
    order_index = serializers.IntegerField()
    original_url = AbsoluteMediaURLField(allow_null=True)
    optimized_url = AbsoluteMediaURLField(allow_null=True)
    thumbnail_url = AbsoluteMediaURLField(allow_null=True)
    processing_status = serializers.CharField()


class MembershipPlanPreviewSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    description = serializers.CharField(allow_null=True)
    plan_type = serializers.CharField()
    plan_type_display = serializers.CharField()
    price = serializers.CharField()
    duration_value = serializers.IntegerField()
    duration_unit = serializers.CharField()
    duration_unit_display = serializers.CharField()
    joining_fee = serializers.CharField()


class GymSocialStatsSerializer(serializers.Serializer):
    followers_count = serializers.IntegerField()
    members_count = serializers.IntegerField()
    is_following = serializers.BooleanField()


class GymPublicDetailSerializer(serializers.Serializer):
    """
    Comprehensive public gym details representation:
    - Overview information & branding assets
    - Primary location and branch locations
    - 7-day schedule with live open/closed indicator
    - Amenities grouped into complimentary vs paid
    - Media gallery assets with optimized and thumbnail WebP variants
    - Active membership plan pricing
    - Social follower & member statistics
    """
    id = serializers.UUIDField()
    name = serializers.CharField()
    profile_picture_url = AbsoluteMediaURLField(allow_null=True)
    cover_photo_url = AbsoluteMediaURLField(allow_null=True)
    short_description = serializers.CharField(allow_null=True)
    primary_type = serializers.CharField()
    primary_type_display = serializers.CharField()
    secondary_type = serializers.CharField(allow_null=True)
    secondary_type_display = serializers.CharField(allow_null=True)
    gender_required = serializers.CharField()
    gender_required_display = serializers.CharField()
    min_age = serializers.IntegerField()
    timezone = serializers.CharField()
    created_at = serializers.DateTimeField()
    owner_public = GymOwnerPublicSerializer()
    location = GymLocationSerializer(allow_null=True)
    locations = GymLocationSerializer(many=True)
    today_status = GymTodayStatusSerializer()
    operating_hours = GymOpeningHoursItemSerializer(many=True)
    amenities = GymAmenitiesBreakdownSerializer()
    gallery = GymGalleryItemDetailSerializer(many=True)
    membership_plans = MembershipPlanPreviewSerializer(many=True)
    social = GymSocialStatsSerializer()

