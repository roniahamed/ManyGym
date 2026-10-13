from typing import Dict, List, Any, Iterator
from django.db.models import Count, Q
from apps.amenities.models import AmenityCatalog, GymAmenity
from common.enums import AmenityGroupEnum


def stream_master_catalog() -> Iterator[AmenityCatalog]:
    """
    Generator streaming master catalog items lazily using field projection and iterator().
    """
    return (
        AmenityCatalog.objects.all()
        .only("id", "name", "group_name")
        .order_by("group_name", "name")
        .iterator(chunk_size=100)
    )


def get_master_catalog() -> Dict[str, Any]:
    """
    Returns the master catalog items organized by group for grouped UI checkboxes,
    efficiently memory-streamed via generator.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    # Initialize all 7 groups
    for group_key, group_label in AmenityGroupEnum.choices:
        grouped[group_label] = []

    group_label_map = dict(AmenityGroupEnum.choices)

    for item in stream_master_catalog():
        display_group = group_label_map.get(item.group_name, item.group_name)
        if display_group not in grouped:
            grouped[display_group] = []
        grouped[display_group].append({
            "id": str(item.id),
            "name": item.name,
            "group_key": item.group_name,
        })

    return grouped


def stream_gym_configured_amenities(gym_id: str) -> Iterator[Dict[str, Any]]:
    """
    Generator streaming gym configured amenities lazily with field projection and select_related.
    """
    amenities = (
        GymAmenity.objects.filter(gym_id=gym_id)
        .select_related("amenity")
        .only(
            "id",
            "is_paid",
            "default_price",
            "amenity__id",
            "amenity__name",
            "amenity__group_name",
        )
        .order_by("amenity__group_name", "amenity__name")
        .iterator(chunk_size=100)
    )

    for a in amenities:
        yield {
            "id": str(a.id),
            "amenity_id": str(a.amenity.id),
            "name": a.amenity.name,
            "group_name": a.amenity.group_name,
            "group_display": a.amenity.get_group_name_display(),
            "is_paid": a.is_paid,
            "default_price": str(a.default_price),
        }


def get_gym_configured_amenities(gym_id: str) -> Dict[str, Any]:
    """
    Returns a gym's configured amenities separated into free and paid lists,
    utilizing lazy streaming and SQL Count aggregations.
    """
    # SQL Count Aggregation
    stats = GymAmenity.objects.filter(gym_id=gym_id).aggregate(
        total_count=Count("id"),
        free_count=Count("id", filter=Q(is_paid=False)),
        paid_count=Count("id", filter=Q(is_paid=True)),
    )

    free_list = []
    paid_list = []

    for item_data in stream_gym_configured_amenities(gym_id):
        if item_data["is_paid"]:
            paid_list.append(item_data)
        else:
            free_list.append(item_data)

    return {
        "free_amenities": free_list,
        "paid_amenities": paid_list,
        "total_count": stats["total_count"] or 0,
    }
