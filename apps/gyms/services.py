import uuid
import logging
from pathlib import Path
from datetime import time
from typing import List, Dict, Any, Optional
from django.db import transaction
from apps.gyms.models import (
    Gym,
    GymLocation,
    GymOpeningHours,
    GymGallery,
    GymSetting,
    GymBlockedUser,
    GymFollow,
)
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

logger = logging.getLogger(__name__)


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


def get_or_create_gym_settings(gym: Gym) -> GymSetting:
    """
    Retrieves existing settings or auto-provisions default settings for the gym.

    Args:
        gym: Gym entity.

    Returns:
        GymSetting model instance.
    """
    settings_obj, _ = GymSetting.objects.get_or_create(gym=gym)
    return settings_obj


@transaction.atomic
def update_gym_settings(gym: Gym, **data: Any) -> GymSetting:
    """
    Updates gym configuration fields across Display, Alerts, Audience, and Access & Control.
    Delegates lifecycle transitions to GymSetting domain methods.

    Args:
        gym: Target Gym entity.
        **data: Attribute key-value pairs to update.

    Returns:
        Updated GymSetting model instance.
    """
    settings_obj = get_or_create_gym_settings(gym)

    allowed_fields = {
        "language",
        "video_autoplay",
        "dark_mode",
        "admin_logs_alerts",
        "issues_alerts",
        "who_can_message",
        "who_can_send_joining_request",
        "who_can_see_members",
        "who_can_see_followers",
        "who_can_see_following",
        "posts_age_restriction",
        "is_deactivated",
        "is_published",
        "is_deleted",
    }

    for field, val in data.items():
        if field not in allowed_fields or val is None:
            continue

        if field == "is_deactivated":
            settings_obj.deactivate() if val else settings_obj.reactivate()
        elif field == "is_published":
            settings_obj.publish() if val else settings_obj.unpublish()
        elif field == "is_deleted":
            settings_obj.soft_delete() if val else settings_obj.restore()
        else:
            setattr(settings_obj, field, val)

    settings_obj.save()
    logger.info("Updated settings for gym %s (%s)", gym.name, gym.id)
    return settings_obj


@transaction.atomic
def block_user_for_gym(
    gym: Gym,
    user_id: str,
    blocked_by_user: Optional[User] = None,
    reason: Optional[str] = None,
) -> GymBlockedUser:
    """
    Blocks a user from interacting with the gym.
    Validates user existence, enforces that the gym owner cannot be blocked,
    and creates the block record idempotently.

    Args:
        gym: Gym imposing the block.
        user_id: UUID string of the user being blocked.
        blocked_by_user: Optional User initiating the block.
        reason: Optional justification note for the block.

    Returns:
        GymBlockedUser model instance.

    Raises:
        DomainValidationError: If user_id is malformed or targets the gym owner.
        ResourceNotFoundError: If the target user account does not exist.
    """
    try:
        uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid user_id.")

    target_user = User.objects.filter(id=user_id).first()
    if not target_user:
        raise ResourceNotFoundError("User to block not found.")

    if target_user.id == gym.owner_user_id:
        raise DomainValidationError("Gym owner cannot be blocked.")

    blocked_obj, created = GymBlockedUser.objects.get_or_create(
        gym=gym,
        user=target_user,
        defaults={
            "blocked_by": blocked_by_user,
            "reason": reason.strip() if reason else None,
        },
    )
    if created:
        logger.info("Blocked user %s on gym %s by %s", target_user.email, gym.name, blocked_by_user)
    return blocked_obj


@transaction.atomic
def unblock_user_for_gym(gym: Gym, user_id: str) -> bool:
    """
    Unblocks a previously restricted user account from the gym.

    Args:
        gym: Gym lifting the block.
        user_id: UUID string of the user to unblock.

    Returns:
        True upon successful removal.

    Raises:
        DomainValidationError: If user_id is malformed.
        ResourceNotFoundError: If the user is not currently blocked by this gym.
    """
    try:
        uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid user_id.")

    deleted_count, _ = GymBlockedUser.objects.filter(gym=gym, user_id=user_id).delete()
    if deleted_count == 0:
        raise ResourceNotFoundError("Blocked user not found for this gym.")

    logger.info("Unblocked user %s from gym %s", user_id, gym.name)
    return True


@transaction.atomic
def apply_access_control_action(gym: Gym, action: str, user: User) -> GymSetting:
    """
    Applies an administrative lifecycle state transition to the gym.

    Supported actions:
        - deactivate: Suspend gym activities.
        - reactivate: Restore active gym operations.
        - unpublish: Hide gym profile from public discovery.
        - publish: Make gym profile publicly visible.
        - delete: Mark gym as soft-deleted.
        - restore: Recover gym from soft-deleted status.

    Args:
        gym: Target Gym entity.
        action: Lifecycle action code.
        user: Authenticated staff member or owner executing the transition.

    Returns:
        Updated GymSetting model instance.

    Raises:
        DomainValidationError: If an unknown action is supplied.
    """
    settings_obj = get_or_create_gym_settings(gym)

    action_handlers = {
        "deactivate": settings_obj.deactivate,
        "reactivate": settings_obj.reactivate,
        "unpublish": settings_obj.unpublish,
        "publish": settings_obj.publish,
        "delete": settings_obj.soft_delete,
        "restore": settings_obj.restore,
    }

    handler = action_handlers.get(action)
    if not handler:
        raise DomainValidationError(f"Invalid access control action '{action}'.")

    handler()
    settings_obj.save()
    logger.info("Applied access control '%s' to gym %s by user %s", action, gym.name, user.email)
    return settings_obj


@transaction.atomic
def follow_gym(user: User, gym_id) -> tuple[GymFollow, bool]:
    """
    Enables an authenticated user to follow a Gym entity.
    Checks:
    - Target gym exists, is not deleted, and is not deactivated.
    - User is not blocked by the gym.
    Returns:
    - (GymFollow instance, created: bool)
    """
    if isinstance(gym_id, Gym):
        gym = gym_id
        gym_uuid = gym.id
    else:
        try:
            gym_uuid = uuid.UUID(str(gym_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid gym ID.")

        try:
            gym = Gym.objects.select_related("settings").get(id=gym_uuid)
        except Gym.DoesNotExist:
            raise ResourceNotFoundError("Gym not found.")

    settings_obj = gym.get_settings()
    if settings_obj.is_deleted or settings_obj.is_deactivated:
        raise DomainValidationError("This gym is currently inactive or unavailable.")

    # Check if user is blocked by gym
    if GymBlockedUser.objects.filter(gym=gym, user=user).exists():
        raise PermissionDeniedError("You are blocked from following this gym.")

    follow_instance, created = GymFollow.objects.get_or_create(
        user=user,
        gym=gym,
    )
    return follow_instance, created


@transaction.atomic
def unfollow_gym(user: User, gym_id) -> bool:
    """
    Unfollows a gym previously followed by user.
    """
    try:
        gym_uuid = uuid.UUID(str(gym_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid gym ID.")

    deleted_count, _ = GymFollow.objects.filter(user=user, gym_id=gym_uuid).delete()
    if deleted_count == 0:
        raise ResourceNotFoundError("You are not currently following this gym.")

    return True


def auto_follow_gym_for_member(user: User, gym: Gym) -> Optional[GymFollow]:
    """
    Automatically follows a gym when a member connects their user account.
    Gym members can unfollow later at their own discretion.
    Uses single-query atomic insert with ON CONFLICT DO NOTHING to eliminate savepoints and extra queries.
    """
    if not user or not gym:
        return None
    created = GymFollow.objects.bulk_create([GymFollow(user=user, gym=gym)], ignore_conflicts=True)
    return created[0] if created else None

