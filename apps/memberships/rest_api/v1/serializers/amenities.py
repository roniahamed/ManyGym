from rest_framework import serializers
from apps.memberships.models import PlanIncludedAmenities
from common.serializers import StrictUUIDField


class PlanIncludedAmenitySerializer(serializers.ModelSerializer):
    """
    Representation of an amenity bundled into a membership plan.
    """
    id = serializers.UUIDField(source="gym_amenity.id", read_only=True)
    catalog_id = serializers.UUIDField(source="gym_amenity.amenity.id", read_only=True)
    name = serializers.CharField(source="gym_amenity.amenity.name", read_only=True)
    group = serializers.CharField(source="gym_amenity.amenity.group_name", read_only=True)
    group_name = serializers.CharField(source="gym_amenity.amenity.group_name", read_only=True)
    is_paid = serializers.BooleanField(source="gym_amenity.is_paid", read_only=True)
    is_free = serializers.SerializerMethodField()
    price = serializers.DecimalField(
        source="gym_amenity.default_price",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = PlanIncludedAmenities
        fields = ["id", "catalog_id", "name", "group", "group_name", "is_paid", "is_free", "price"]

    def get_is_free(self, obj) -> bool:
        return not obj.gym_amenity.is_paid


class PlanSyncAmenitiesSerializer(serializers.Serializer):
    """
    Validates bulk synchronization of included amenities.
    """
    amenity_ids = serializers.ListField(child=StrictUUIDField(), required=True)
