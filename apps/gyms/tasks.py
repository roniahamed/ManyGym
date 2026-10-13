import logging
from celery import shared_task
from apps.gyms.models import GymGallery
from common.enums import MediaTypeEnum, ProcessingStatus
from common.media import MediaOptimizerService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def optimize_gallery_media_task(self, gallery_item_id: str):
    """
    Background Celery task delegating to the reusable MediaOptimizerService:
    1. Loads the locally saved original file.
    2. Keeps the original intact in original_url ('ager ta reke').
    3. Auto-orients with EXIF transpose and compresses images to WebP variants ('new optimisation ta thakbo').
    4. For videos, extracts a poster thumbnail and optionally compresses via FFmpeg.
    5. Updates gallery item with optimized_url, thumbnail_url, and dimensions.
    """
    try:
        item = GymGallery.objects.get(id=gallery_item_id)
    except GymGallery.DoesNotExist:
        logger.warning(f"GymGallery item {gallery_item_id} not found. Retrying...")
        raise self.retry(countdown=2)

    item.processing_status = ProcessingStatus.PROCESSING
    item.save(update_fields=["processing_status"])

    # Determine original source path via reusable resolver
    src_url = item.original_url or item.media_url
    src_path = MediaOptimizerService.get_absolute_path(src_url)

    if not src_path or not src_path.exists():
        logger.error(f"Source file not found at {src_path} for gallery item {gallery_item_id}")
        item.processing_status = ProcessingStatus.FAILED
        item.save(update_fields=["processing_status"])
        return

    try:
        if item.media_type == MediaTypeEnum.PICTURE:
            result = MediaOptimizerService.optimize_image(
                src_path=src_path,
                subfolder="gyms/gallery",
                max_dims=(1920, 1080),
                thumb_dims=(400, 300),
                quality=82,
                thumb_quality=78,
            )
            item.width = result["width"]
            item.height = result["height"]
            item.size_bytes = result["size_bytes"]
            item.optimized_size_bytes = result["optimized_size_bytes"]
            item.optimized_url = result["optimized_url"]
            item.thumbnail_url = result["thumbnail_url"]
            item.media_url = item.optimized_url
            item.processing_status = ProcessingStatus.COMPLETED

        elif item.media_type == MediaTypeEnum.VIDEO:
            result = MediaOptimizerService.optimize_video(
                src_path=src_path,
                subfolder="gyms/gallery",
            )
            item.size_bytes = result["size_bytes"]
            if result.get("optimized_size_bytes"):
                item.optimized_size_bytes = result["optimized_size_bytes"]
            if result.get("thumbnail_url"):
                item.thumbnail_url = result["thumbnail_url"]
            if result.get("optimized_url"):
                item.optimized_url = result["optimized_url"]
                item.media_url = item.optimized_url
            else:
                item.optimized_url = item.original_url

            item.processing_status = ProcessingStatus.COMPLETED

        item.save()
        logger.info(f"Successfully optimized gallery media {gallery_item_id}: optimized_url={item.optimized_url}")

    except Exception as exc:
        logger.error(f"Error optimizing gallery media {gallery_item_id}: {exc}", exc_info=True)
        item.processing_status = ProcessingStatus.FAILED
        item.save(update_fields=["processing_status"])
        raise self.retry(exc=exc, countdown=5)
