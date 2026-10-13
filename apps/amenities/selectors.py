from typing import Dict, List, Any
from apps.amenities.models import AmenityCatalog, GymAmenity
from common.enums import AmenityGroupEnum


def get_master_catalog() -> Dict[str, Any]:
    """
    Returns the master catalog items organized by group for grouped UI checkboxes.
    """
    catalog_items = AmenityCatalog.objects.all().order_by("group_name", "name")
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    # Initialize all 7 groups
    for group_key, group_label in AmenityGroupEnum.choices:
        grouped[group_label] = []

    group_label_map = dict(AmenityGroupEnum.choices)

    for item in catalog_items:
        display_group = group_label_map.get(item.group_name, item.group_name)
        if display_group not in grouped:
            grouped[display_group] = []
        grouped[display_group].append({
            "id": str(item.id),
            "name": item.name,
            "group_key": item.group_name,
        })

    return grouped


def get_gym_configured_amenities(gym_id: str) -> Dict[str, Any]:
    """
    Returns a gym's configured amenities separated into free and paid lists.
    """
    amenities = (
        GymAmenity.objects.filter(gym_id=gym_id)
        .select_related("amenity")
        .order_by("amenity__group_name", "amenity__name")
    )

    free_list = []
    paid_list = []

    for a in amenities:
        item_data = {
            "id": str(a.id),
            "amenity_id": str(a.amenity.id),
            "name": a.amenity.name,
            "group_name": a.amenity.group_name,
            "group_display": a.amenity.get_group_name_display(),
            "is_paid": a.is_paid,
            "default_price": str(a.default_price),
        }
        if a.is_paid:
            paid_list.append(item_data)
        else:
            free_list.append(item_data)

    return {
        "free_amenities": free_list,
        "paid_amenities": paid_list,
        "total_count": len(free_list) + len(paid_list),
    }
