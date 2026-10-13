import uuid
from pathlib import Path
from datetime import time
from typing import List, Dict, Any
from django.db import transaction
from django.conf import settings
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
    ProcessingStatus,
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
    Atomically validates and updates the full 7-day operating schedule using bulk database operations.
    """
    seen_days = set()
    cleaned_records = {}

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

        cleaned_records[day] = {
            "start_time": start_time,
            "end_time": end_time,
            "is_closed": is_closed,
        }

    # Fetch existing schedule in 1 query
    existing = {h.day_of_week: h for h in GymOpeningHours.objects.filter(gym=gym)}

    to_create = []
    to_update = []
    result_records = []

    for day, fields in cleaned_records.items():
        if day in existing:
            rec = existing[day]
            rec.start_time = fields["start_time"]
            rec.end_time = fields["end_time"]
            rec.is_closed = fields["is_closed"]
            to_update.append(rec)
            result_records.append(rec)
        else:
            rec = GymOpeningHours(
                gym=gym,
                day_of_week=day,
                start_time=fields["start_time"],
                end_time=fields["end_time"],
                is_closed=fields["is_closed"],
            )
            to_create.append(rec)
            result_records.append(rec)

    if to_create:
        GymOpeningHours.objects.bulk_create(to_create)
    if to_update:
        GymOpeningHours.objects.bulk_update(to_update, ["start_time", "end_time", "is_closed"])

    result_records.sort(key=lambda x: x.day_of_week)
    return result_records


@transaction.atomic
def add_gallery_item(
    gym: Gym,
    media_url: str = None,
    file=None,
    media_type: str = MediaTypeEnum.PICTURE,
    category: str = GalleryCategoryEnum.GENERAL,
    caption: str = None,
) -> GymGallery:
    """
    Saves an uploaded media asset locally (or registers an external media URL),
    creates the GymGallery record in PENDING status, retains the original file ('ager ta reke'),
    and dispatches the background Celery task to optimize WebP images & video assets.
    """
    if caption and len(caption) > 200:
        raise DomainValidationError("Caption cannot exceed 200 characters.")

    if not file and not media_url:
        raise DomainValidationError("Either a file upload or a media_url must be provided.")

    final_media_url = media_url
    original_url = media_url

    if file:
        content_type = getattr(file, "content_type", "")
        filename = getattr(file, "name", "upload")
        ext = Path(filename).suffix.lower()
        if content_type.startswith("video/") or ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            media_type = MediaTypeEnum.VIDEO
        else:
            media_type = MediaTypeEnum.PICTURE

        from common.media import MediaOptimizerService
        _, final_media_url = MediaOptimizerService.save_uploaded_file(
            file=file, subfolder="gyms/gallery/original"
        )
        original_url = final_media_url

    last_item = GymGallery.objects.filter(gym=gym).order_by("-order_index").first()
    next_order = (last_item.order_index + 1) if last_item else 0

    item = GymGallery.objects.create(
        gym=gym,
        media_url=final_media_url.strip(),
        original_url=original_url.strip() if original_url else final_media_url.strip(),
        media_type=media_type,
        category=category,
        caption=caption.strip() if caption else None,
        order_index=next_order,
        processing_status=ProcessingStatus.PENDING,
    )

    # Dispatch background optimization task upon commit
    from apps.gyms.tasks import optimize_gallery_media_task
    transaction.on_commit(lambda: optimize_gallery_media_task.delay(str(item.id)))

    return item


@transaction.atomic
def reorder_gallery(gym: Gym, item_orders: List[Dict[str, Any]]) -> None:
    """
    Bulk updates display sequence order for gallery items using bulk_update.
    """
    order_map = {
        str(entry["id"]): entry["order_index"]
        for entry in item_orders
        if "id" in entry and "order_index" in entry
    }
    if not order_map:
        return

    items = list(GymGallery.objects.filter(gym=gym, id__in=order_map.keys()))
    for item in items:
        item.order_index = order_map[str(item.id)]

    GymGallery.objects.bulk_update(items, ["order_index"])


@transaction.atomic
def delete_gallery_item(gym: Gym, item_id: str) -> None:
    """
    Deletes a gallery asset belonging to the gym.
    """
    import uuid
    try:
        uuid.UUID(str(item_id))
    except (ValueError, TypeError, AttributeError):
        raise ResourceNotFoundError("Gallery item not found.")

    item = GymGallery.objects.filter(gym=gym, id=item_id).first()
    if not item:
        raise ResourceNotFoundError("Gallery item not found.")
    item.delete()
