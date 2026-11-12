import logging
from celery import shared_task
from PIL import Image
from apps.posts.models import GymPostMedia, PostComment
from common.enums import CommentMediaTypeEnum, MediaTypeEnum, ProcessingStatus
from common.media import MediaOptimizerService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def optimize_post_media_task(self, post_media_id: str):
    """
    Asynchronous Celery task to optimize post media:
    - Compresses images to WebP and creates a square/feed thumbnail.
    - Generates video poster thumbnails via ffmpeg and compresses videos.
    """
    try:
        item = GymPostMedia.objects.get(id=post_media_id)
    except GymPostMedia.DoesNotExist:
        logger.warning(f"GymPostMedia {post_media_id} not found. Retrying...")
        raise self.retry(countdown=2)

    item.processing_status = ProcessingStatus.PROCESSING
    item.save(update_fields=["processing_status"])

    src_url = item.original_url or item.media_url
    src_path = MediaOptimizerService.get_absolute_path(src_url)

    if not src_path or not src_path.exists():
        logger.error(f"Source file not found at {src_path} for post media {post_media_id}")
        item.processing_status = ProcessingStatus.FAILED
        item.save(update_fields=["processing_status"])
        return

    try:
        if item.media_type == MediaTypeEnum.PICTURE:
            result = MediaOptimizerService.optimize_image(
                src_path=src_path,
                subfolder="posts/media",
                max_dims=(1920, 1080),
                thumb_dims=(500, 500),
                quality=82,
                thumb_quality=80,
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
                subfolder="posts/media",
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
        logger.info(f"Successfully optimized post media {post_media_id}")

    except Exception as exc:
        logger.error(f"Error optimizing post media {post_media_id}: {exc}", exc_info=True)
        item.processing_status = ProcessingStatus.FAILED
        item.save(update_fields=["processing_status"])
        raise self.retry(exc=exc, countdown=5)


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def optimize_comment_media_task(self, comment_id: str):
    """
    Asynchronous Celery task to optimize comment media attachments:
    - Photos: converts to optimized WebP + thumbnail.
    - Videos: generates poster thumbnail via ffmpeg and compresses MP4.
    - GIFs: preserves animation frames while recording dimensions and file size.
    """
    try:
        comment = PostComment.objects.get(id=comment_id)
    except PostComment.DoesNotExist:
        logger.warning(f"PostComment {comment_id} not found. Retrying...")
        raise self.retry(countdown=2)

    if not comment.media_type:
        return

    comment.processing_status = ProcessingStatus.PROCESSING
    comment.save(update_fields=["processing_status"])

    src_url = comment.original_url or comment.active_media_url
    src_path = MediaOptimizerService.get_absolute_path(src_url)

    if not src_path or not src_path.exists():
        logger.error(f"Source file not found at {src_path} for comment {comment_id}")
        comment.processing_status = ProcessingStatus.FAILED
        comment.save(update_fields=["processing_status"])
        return

    try:
        if comment.media_type == CommentMediaTypeEnum.PHOTO:
            result = MediaOptimizerService.optimize_image(
                src_path=src_path,
                subfolder="posts/comments/photos",
                max_dims=(1280, 1280),
                thumb_dims=(400, 400),
                quality=82,
                thumb_quality=80,
            )
            comment.width = result["width"]
            comment.height = result["height"]
            comment.size_bytes = result["size_bytes"]
            comment.optimized_size_bytes = result["optimized_size_bytes"]
            comment.optimized_url = result["optimized_url"]
            comment.thumbnail_url = result["thumbnail_url"]
            comment.comment_photo = result["optimized_url"]
            comment.processing_status = ProcessingStatus.COMPLETED

        elif comment.media_type == CommentMediaTypeEnum.VIDEO:
            result = MediaOptimizerService.optimize_video(
                src_path=src_path,
                subfolder="posts/comments/videos",
            )
            comment.size_bytes = result["size_bytes"]
            if result.get("optimized_size_bytes"):
                comment.optimized_size_bytes = result["optimized_size_bytes"]
            if result.get("thumbnail_url"):
                comment.thumbnail_url = result["thumbnail_url"]
            if result.get("optimized_url"):
                comment.optimized_url = result["optimized_url"]
                comment.comment_video = result["optimized_url"]
            else:
                comment.optimized_url = comment.original_url
            comment.processing_status = ProcessingStatus.COMPLETED

        elif comment.media_type == CommentMediaTypeEnum.GIF:
            with Image.open(src_path) as gif_img:
                comment.width, comment.height = gif_img.size
            comment.size_bytes = src_path.stat().st_size
            comment.optimized_size_bytes = comment.size_bytes
            comment.optimized_url = comment.original_url or comment.comment_gif
            comment.processing_status = ProcessingStatus.COMPLETED

        comment.save()
        logger.info(f"Successfully optimized media for comment {comment_id}")

    except Exception as exc:
        logger.error(f"Error optimizing comment media {comment_id}: {exc}", exc_info=True)
        comment.processing_status = ProcessingStatus.FAILED
        comment.save(update_fields=["processing_status"])
        raise self.retry(exc=exc, countdown=5)
