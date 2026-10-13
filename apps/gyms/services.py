from datetime import time
from typing import List, Dict, Any
from django.db import transaction
from apps.gyms.models import Gym, GymLocation, GymOpeningHours, GymGallery
from apps.access_control.models import Role, GymStaffAssignment
from apps.users.models import User
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.enums import (
    GymTypeEnum,
    GymGenderRequired,
    GalleryCategoryEnum,
    MediaTypeEnum,
    StaffStatus,
)


@transaction.atomic
def create_gym(
    owner_user: User,
    name: str,
    primary_type: str = GymTypeEnum.GENERAL_FITNESS,
    secondary_type: str = None,
    short_description: str = None,
    profile_picture_url: str = None,
    cover_photo_url: str = None,
    gender_required: str = GymGenderRequired.EVERYONE,
    min_age: int = 1,
    timezone: str = "UTC",
    address: str = "Unspecified Location",
    latitude: float = 0.0,
    longitude: float = 0.0,
    city: str = None,
    country: str = None,
    postal_code: str = None,
) -> Gym:
    """
    Initializes a new Gym entity, default primary location, 7-day default operating schedule,
    and assigns the owner as Administrator.
    """
    if short_description and len(short_description.strip()) < 120:
        raise DomainValidationError("Short description must be at least 120 characters long.")

    if min_age < 1 or min_age > 99:
        raise DomainValidationError("Minimum age must be an integer between 1 and 99.")

    gym = Gym.objects.create(
        owner_user=owner_user,
        name=name.strip(),
        primary_type=primary_type,
        secondary_type=secondary_type,
        short_description=short_description.strip() if short_description else None,
        profile_picture_url=profile_picture_url,
        cover_photo_url=cover_photo_url,
        gender_required=gender_required,
        min_age=min_age,
        timezone=timezone,
    )

    # Provision primary map location
    GymLocation.objects.create(
        gym=gym,
        address=address.strip(),
        latitude=latitude,
        longitude=longitude,
        city=city,
        country=country,
        postal_code=postal_code,
        is_primary=True,
    )

    # Seed default 7-day operating hours (0=Sunday ... 6=Saturday)
    default_hours = [
        {"day_of_week": 0, "start_time": time(8, 0), "end_time": time(20, 0), "is_closed": False},
        {"day_of_week": 1, "start_time": time(6, 0), "end_time": time(22, 0), "is_closed": False},
        {"day_of_week": 2, "start_time": time(6, 0), "end_time": time(22, 0), "is_closed": False},
        {"day_of_week": 3, "start_time": time(6, 0), "end_time": time(22, 0), "is_closed": False},
        {"day_of_week": 4, "start_time": time(6, 0), "end_time": time(22, 0), "is_closed": False},
        {"day_of_week": 5, "start_time": time(6, 0), "end_time": time(22, 0), "is_closed": False},
        {"day_of_week": 6, "start_time": time(8, 0), "end_time": time(20, 0), "is_closed": False},
    ]
    for h in default_hours:
        GymOpeningHours.objects.create(
            gym=gym,
            day_of_week=h["day_of_week"],
            start_time=h["start_time"],
            end_time=h["end_time"],
            is_closed=h["is_closed"],
        )

    # Assign owner to Administrator role
    admin_role = Role.objects.filter(slug="administrator").first()
    if admin_role:
        GymStaffAssignment.objects.get_or_create(
            user=owner_user,
            gym=gym,
            role=admin_role,
            defaults={"status": StaffStatus.ACTIVE},
        )

    return gym


@transaction.atomic
def update_gym_overview(gym: Gym, **data) -> Gym:
    """
    Validates and updates gym overview attributes.
    Enforces min 120 characters on description and min_age bounds.
    """
    if "short_description" in data and data["short_description"] is not None:
        desc = data["short_description"].strip()
        if len(desc) < 120:
            raise DomainValidationError("Short description must be at least 120 characters long.")
        gym.short_description = desc

    if "min_age" in data and data["min_age"] is not None:
        if data["min_age"] < 1 or data["min_age"] > 99:
            raise DomainValidationError("Minimum age must be an integer between 1 and 99.")
        gym.min_age = data["min_age"]

    fields_to_update = [
        "name", "profile_picture_url", "cover_photo_url",
        "primary_type", "secondary_type", "gender_required", "timezone",
    ]
    for f in fields_to_update:
        if f in data and data[f] is not None:
            setattr(gym, f, data[f])

    gym.save()
    return gym


@transaction.atomic
def update_gym_location(
    gym: Gym,
    address: str,
    latitude: float,
    longitude: float,
    city: str = None,
    country: str = None,
    postal_code: str = None,
) -> GymLocation:
    """
    Saves live map pin placement while maintaining editable address string.
    """
    location, _ = GymLocation.objects.get_or_create(
        gym=gym,
        is_primary=True,
        defaults={
            "address": address.strip(),
            "latitude": latitude,
            "longitude": longitude,
            "city": city,
            "country": country,
            "postal_code": postal_code,
        },
    )

    location.address = address.strip()
    location.latitude = latitude
    location.longitude = longitude
    if city is not None:
        location.city = city
    if country is not None:
        location.country = country
    if postal_code is not None:
        location.postal_code = postal_code

    location.save()
    return location


@transaction.atomic
def bulk_update_opening_hours(gym: Gym, hours_list: List[Dict[str, Any]]) -> List[GymOpeningHours]:
    """
    Atomically validates and updates the full 7-day operating schedule.
    """
    updated_records = []
    seen_days = set()

    for item in hours_list:
        day = item["day_of_week"]
        if day < 0 or day > 6:
            raise DomainValidationError(f"Invalid day_of_week: {day}. Must be between 0 (Sunday) and 6 (Saturday).")
        if day in seen_days:
            raise DomainValidationError(f"Duplicate entry for day_of_week: {day}.")
        seen_days.add(day)

        is_closed = item.get("is_closed", False)
        start_time = item.get("start_time")
        end_time = item.get("end_time")

        if not is_closed:
            if not start_time or not end_time:
                raise DomainValidationError(f"Opening hours for day {day} require both start_time and end_time when not closed.")
            if start_time >= end_time:
                raise DomainValidationError(f"start_time must precede end_time for day {day}.")
        else:
            start_time = None
            end_time = None

        record, _ = GymOpeningHours.objects.update_or_create(
            gym=gym,
            day_of_week=day,
            defaults={
                "start_time": start_time,
                "end_time": end_time,
                "is_closed": is_closed,
            },
        )
        updated_records.append(record)

    return updated_records


@transaction.atomic
def add_gallery_item(
    gym: Gym,
    media_url: str,
    media_type: str = MediaTypeEnum.PICTURE,
    category: str = GalleryCategoryEnum.GENERAL,
    caption: str = None,
) -> GymGallery:
    """
    Uploads/registers a photo or video with caption, category, and sequential order_index.
    """
    if caption and len(caption) > 200:
        raise DomainValidationError("Caption cannot exceed 200 characters.")

    # Determine highest order_index
    last_item = GymGallery.objects.filter(gym=gym).order_by("-order_index").first()
    next_order = (last_item.order_index + 1) if last_item else 0

    return GymGallery.objects.create(
        gym=gym,
        media_url=media_url.strip(),
        media_type=media_type,
        category=category,
        caption=caption.strip() if caption else None,
        order_index=next_order,
    )


@transaction.atomic
def reorder_gallery(gym: Gym, item_orders: List[Dict[str, Any]]) -> None:
    """
    Bulk updates display sequence order for gallery items.
    """
    for entry in item_orders:
        item_id = entry.get("id")
        order_idx = entry.get("order_index")
        if item_id is not None and order_idx is not None:
            GymGallery.objects.filter(gym=gym, id=item_id).update(order_index=order_idx)


@transaction.atomic
def delete_gallery_item(gym: Gym, item_id: str) -> None:
    """
    Deletes a gallery asset belonging to the gym.
    """
    item = GymGallery.objects.filter(gym=gym, id=item_id).first()
    if not item:
        raise ResourceNotFoundError("Gallery item not found.")
    item.delete()
