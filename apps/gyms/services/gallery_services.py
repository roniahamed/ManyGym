import uuid
from pathlib import Path
from typing import List, Dict, Any
from django.db import transaction
from apps.gyms.models import Gym, GymGallery
from common.exceptions import DomainValidationError, ResourceNotFoundError
from common.enums import GalleryCategoryEnum, MediaTypeEnum, ProcessingStatus


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
    try:
        uuid.UUID(str(item_id))
    except (ValueError, TypeError, AttributeError):
        raise ResourceNotFoundError("Gallery item not found.")

    item = GymGallery.objects.filter(gym=gym, id=item_id).first()
    if not item:
        raise ResourceNotFoundError("Gallery item not found.")
    item.delete()
