import logging
from celery import shared_task
from apps.stories.models import Story
from common.enums import MediaTypeEnum, ProcessingStatus
from common.media import MediaOptimizerService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def optimize_story_media_task(self, story_id: str):
    """
    Asynchronous Celery task to optimize uploaded story media:
    - Compresses images to WebP and generates a thumbnail.
    - Extracts video poster thumbnails via ffmpeg and compresses videos.
    """
    try:
        story = Story.objects.get(id=story_id)
    except Story.DoesNotExist:
        logger.warning(f"Story {story_id} not found. Retrying...")
        raise self.retry(countdown=2)

    story.processing_status = ProcessingStatus.PROCESSING
    story.save(update_fields=["processing_status"])

    src_url = story.original_url or story.media_url
    src_path = MediaOptimizerService.get_absolute_path(src_url)

    if not src_path or not src_path.exists():
        logger.error(f"Source file not found at {src_path} for story {story_id}")
        story.processing_status = ProcessingStatus.FAILED
        story.save(update_fields=["processing_status"])
        return

    try:
        if story.media_type == MediaTypeEnum.PICTURE:
            result = MediaOptimizerService.optimize_image(
                src_path=src_path,
                subfolder="stories/media",
                max_dims=(1920, 1920),
                thumb_dims=(500, 500),
                quality=82,
                thumb_quality=80,
            )
            story.width = result["width"]
            story.height = result["height"]
            story.size_bytes = result["size_bytes"]
            story.optimized_size_bytes = result["optimized_size_bytes"]
            story.optimized_url = result["optimized_url"]
            story.thumbnail_url = result["thumbnail_url"]
            story.media_url = story.optimized_url
            story.processing_status = ProcessingStatus.COMPLETED

        elif story.media_type == MediaTypeEnum.VIDEO:
            result = MediaOptimizerService.optimize_video(
                src_path=src_path,
                subfolder="stories/media",
            )
            story.size_bytes = result["size_bytes"]
            if result.get("optimized_size_bytes"):
                story.optimized_size_bytes = result["optimized_size_bytes"]
            if result.get("thumbnail_url"):
                story.thumbnail_url = result["thumbnail_url"]
            if result.get("optimized_url"):
                story.optimized_url = result["optimized_url"]
                story.media_url = story.optimized_url
            else:
                story.optimized_url = story.original_url

            story.processing_status = ProcessingStatus.COMPLETED

        story.save()
        logger.info(f"Successfully optimized story media for story {story_id}")

    except Exception as exc:
        logger.error(f"Error optimizing story media {story_id}: {exc}", exc_info=True)
        story.processing_status = ProcessingStatus.FAILED
        story.save(update_fields=["processing_status"])
        raise self.retry(exc=exc, countdown=5)

