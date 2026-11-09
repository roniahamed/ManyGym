from datetime import time
from typing import List, Dict, Any, Optional
from django.db import transaction
from apps.gyms.models import (
    Gym,
    GymLocation,
    GymOpeningHours,
    GymSetting,
)
from apps.access_control.models import Role, GymStaffAssignment
from apps.users.models import User
from common.exceptions import DomainValidationError
from common.enums import (
    GymTypeEnum,
    GymGenderRequired,
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
    profile_picture=None,
    cover_photo_url: str = None,
    cover_photo=None,
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

    from common.media import MediaOptimizerService
    resolved_profile_pic = MediaOptimizerService.process_image_upload(
        file=profile_picture,
        url=profile_picture_url,
        subfolder="gyms/profiles",
        max_dims=(800, 800),
        thumb_dims=(200, 200),
    )
    resolved_cover = MediaOptimizerService.process_image_upload(
        file=cover_photo,
        url=cover_photo_url,
        subfolder="gyms/covers",
        max_dims=(1920, 1080),
        thumb_dims=(400, 225),
    )

    gym = Gym.objects.create(
        owner_user=owner_user,
        name=name.strip(),
        primary_type=primary_type,
        secondary_type=secondary_type,
        short_description=short_description.strip() if short_description else None,
        profile_picture_url=resolved_profile_pic,
        cover_photo_url=resolved_cover,
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

    try:
        from apps.gyms.services.geo_services import sync_gym_location_to_redis
        sync_gym_location_to_redis(gym.id, latitude, longitude)
    except Exception:
        pass

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

    # Seed default gym settings
    GymSetting.objects.get_or_create(gym=gym)

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

    from common.media import MediaOptimizerService

    if "profile_picture" in data or "profile_picture_url" in data:
        pic_file = data.pop("profile_picture", None)
        pic_url = data.pop("profile_picture_url", None)
        resolved_pic = MediaOptimizerService.process_image_upload(
            file=pic_file,
            url=pic_url,
            subfolder="gyms/profiles",
            max_dims=(800, 800),
            thumb_dims=(200, 200),
        )
        if resolved_pic is not None or pic_file is not None or pic_url is not None:
            gym.profile_picture_url = resolved_pic

    if "cover_photo" in data or "cover_photo_url" in data:
        cover_file = data.pop("cover_photo", None)
        cover_url = data.pop("cover_photo_url", None)
        resolved_cov = MediaOptimizerService.process_image_upload(
            file=cover_file,
            url=cover_url,
            subfolder="gyms/covers",
            max_dims=(1920, 1080),
            thumb_dims=(400, 225),
        )
        if resolved_cov is not None or cover_file is not None or cover_url is not None:
            gym.cover_photo_url = resolved_cov

    fields_to_update = [
        "name", "primary_type", "secondary_type", "gender_required", "timezone",
    ]
    for f in fields_to_update:
        if f in data and data[f] is not None:
            setattr(gym, f, data[f])

    gym.save()

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType

        log_detail = "Changed the page description" if "short_description" in data else "Updated page information"
        log_admin_action(
            gym=gym,
            actor=data.get("actor") or getattr(gym, "_request_user", None),
            action="Updated page information",
            action_type=AdminLogActionType.UPDATE_PAGE_INFO,
            details=log_detail,
            category=AdminLogCategory.GYM_PROFILE,
            target_type="gym",
            target_id=str(gym.id),
        )
    except Exception:
        pass

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

    try:
        from apps.gyms.services.geo_services import sync_gym_location_to_redis
        sync_gym_location_to_redis(gym.id, latitude, longitude)
    except Exception:
        pass

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
