from decimal import Decimal
from typing import List, Dict, Any
from django.db import transaction
from apps.amenities.models import AmenityCatalog, GymAmenity
from apps.gyms.models import Gym
from common.exceptions import DomainValidationError
from common.enums import AmenityGroupEnum

# Master catalog seed list defined in system requirement docs (gym profile.md)
MASTER_AMENITIES_CATALOG_DATA = [
    # Group: Changing & Storage
    {"group_name": AmenityGroupEnum.CHANGING_AND_STORAGE, "name": "Changing rooms"},
    {"group_name": AmenityGroupEnum.CHANGING_AND_STORAGE, "name": "Showers"},
    {"group_name": AmenityGroupEnum.CHANGING_AND_STORAGE, "name": "Day-use lockers"},
    {"group_name": AmenityGroupEnum.CHANGING_AND_STORAGE, "name": "Personal lockers"},
    {"group_name": AmenityGroupEnum.CHANGING_AND_STORAGE, "name": "Towel service"},

    # Group: Wellness & Recovery
    {"group_name": AmenityGroupEnum.WELLNESS_AND_RECOVERY, "name": "Sauna"},
    {"group_name": AmenityGroupEnum.WELLNESS_AND_RECOVERY, "name": "Steam room"},
    {"group_name": AmenityGroupEnum.WELLNESS_AND_RECOVERY, "name": "Swimming pool"},
    {"group_name": AmenityGroupEnum.WELLNESS_AND_RECOVERY, "name": "Hot tub"},
    {"group_name": AmenityGroupEnum.WELLNESS_AND_RECOVERY, "name": "Massage room"},

    # Group: Comfort & Convenience
    {"group_name": AmenityGroupEnum.COMFORT_AND_CONVENIENCE, "name": "Air conditioning"},
    {"group_name": AmenityGroupEnum.COMFORT_AND_CONVENIENCE, "name": "Wi-Fi"},
    {"group_name": AmenityGroupEnum.COMFORT_AND_CONVENIENCE, "name": "Drinking water station"},
    {"group_name": AmenityGroupEnum.COMFORT_AND_CONVENIENCE, "name": "Seating area"},

    # Group: Food & Drink
    {"group_name": AmenityGroupEnum.FOOD_AND_DRINK, "name": "Cafe"},
    {"group_name": AmenityGroupEnum.FOOD_AND_DRINK, "name": "Smoothie/protein bar"},
    {"group_name": AmenityGroupEnum.FOOD_AND_DRINK, "name": "Vending machines"},

    # Group: Parking & Transport
    {"group_name": AmenityGroupEnum.PARKING_AND_TRANSPORT, "name": "Parking"},
    {"group_name": AmenityGroupEnum.PARKING_AND_TRANSPORT, "name": "Bicycle parking"},

    # Group: Accessibility
    {"group_name": AmenityGroupEnum.ACCESSIBILITY, "name": "Step-free entrance"},
    {"group_name": AmenityGroupEnum.ACCESSIBILITY, "name": "Lift access"},
    {"group_name": AmenityGroupEnum.ACCESSIBILITY, "name": "Accessible toilet"},
    {"group_name": AmenityGroupEnum.ACCESSIBILITY, "name": "Accessible changing room"},

    # Group: Family Facilities
    {"group_name": AmenityGroupEnum.FAMILY_FACILITIES, "name": "Childcare"},
    {"group_name": AmenityGroupEnum.FAMILY_FACILITIES, "name": "Children’s waiting area"},
]


@transaction.atomic
def seed_amenity_catalog() -> None:
    """
    Seeds the system master amenity catalog across the 7 domain categories.
    Idempotent execution.
    """
    for entry in MASTER_AMENITIES_CATALOG_DATA:
        AmenityCatalog.objects.get_or_create(
            group_name=entry["group_name"],
            name=entry["name"],
        )


@transaction.atomic
def sync_gym_amenities(
    gym: Gym,
    free_amenity_ids: List[str],
    paid_amenities: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Synchronizes free vs paid amenity selections for a gym.
    Enforces the core Business Invariant: An amenity CANNOT be both free and paid simultaneously.
    """
    free_set = {str(aid) for aid in free_amenity_ids}
    paid_map = {}
    for p in paid_amenities:
        aid = str(p["amenity_id"])
        price = Decimal(str(p.get("default_price", "0.00")))
        paid_map[aid] = price

    paid_set = set(paid_map.keys())

    # Mutual Exclusion Invariant Check
    conflict = free_set.intersection(paid_set)
    if conflict:
        conflicting_catalog = AmenityCatalog.objects.filter(id__in=conflict).values_list("name", flat=True)
        names_str = ", ".join(conflicting_catalog)
        raise DomainValidationError(
            f"Mutual exclusion violation: The following amenities cannot be selected as both free and paid: {names_str}."
        )

    all_selected_ids = free_set.union(paid_set)

    # Validate that all IDs exist in AmenityCatalog
    valid_catalogs = {str(c.id): c for c in AmenityCatalog.objects.filter(id__in=all_selected_ids)}
    missing = all_selected_ids - set(valid_catalogs.keys())
    if missing:
        raise DomainValidationError(f"Invalid amenity catalog IDs provided: {list(missing)}.")

    # Fetch existing configurations in 1 query
    existing_map = {str(ga.amenity_id): ga for ga in GymAmenity.objects.filter(gym=gym)}

    # Remove any amenities not in the new selection
    to_delete_ids = set(existing_map.keys()) - all_selected_ids
    if to_delete_ids:
        GymAmenity.objects.filter(gym=gym, amenity_id__in=to_delete_ids).delete()

    to_create = []
    to_update = []

    # Sync Free Amenities
    for fid in free_set:
        if fid in existing_map:
            inst = existing_map[fid]
            if inst.is_paid or inst.default_price != Decimal("0.00"):
                inst.is_paid = False
                inst.default_price = Decimal("0.00")
                to_update.append(inst)
        else:
            to_create.append(
                GymAmenity(gym=gym, amenity_id=fid, is_paid=False, default_price=Decimal("0.00"))
            )

    # Sync Paid Amenities
    for pid, price in paid_map.items():
        if pid in existing_map:
            inst = existing_map[pid]
            if not inst.is_paid or inst.default_price != price:
                inst.is_paid = True
                inst.default_price = price
                to_update.append(inst)
        else:
            to_create.append(
                GymAmenity(gym=gym, amenity_id=pid, is_paid=True, default_price=price)
            )

    if to_create:
        GymAmenity.objects.bulk_create(to_create)
    if to_update:
        GymAmenity.objects.bulk_update(to_update, ["is_paid", "default_price"])

    return {
        "free_count": len(free_set),
        "paid_count": len(paid_set),
    }
