from decimal import Decimal
from rest_framework import serializers


class AmenityCatalogItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    group_key = serializers.CharField()


class GymAmenityItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    amenity_id = serializers.UUIDField()
    name = serializers.CharField()
    group_name = serializers.CharField()
    group_display = serializers.CharField()
    is_paid = serializers.BooleanField()
    default_price = serializers.DecimalField(max_digits=10, decimal_places=2)


class GymAmenitiesConfiguredSerializer(serializers.Serializer):
    free_amenities = GymAmenityItemSerializer(many=True)
    paid_amenities = GymAmenityItemSerializer(many=True)
    total_count = serializers.IntegerField()


class PaidAmenityInputSerializer(serializers.Serializer):
    amenity_id = serializers.UUIDField(help_text="UUID of the catalog amenity")
    default_price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0.01"),
        help_text="Price for this paid amenity (e.g. 5.00)",
    )


class SyncGymAmenitiesSerializer(serializers.Serializer):
    free_amenity_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        default=list,
        help_text="List of AmenityCatalog UUIDs that are free / complimentary",
    )
    paid_amenities = PaidAmenityInputSerializer(
        many=True,
        required=False,
        default=list,
        help_text="List of paid amenities with pricing",
    )


class SyncGymAmenitiesResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    free_count = serializers.IntegerField()
    paid_count = serializers.IntegerField()
