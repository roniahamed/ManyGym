import uuid
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from django.db import transaction
from django.core.files.uploadedfile import UploadedFile

from apps.gyms.models import Gym
from apps.users.models import User
from apps.posts.models import GymPost, GymPostMedia
from common.enums import PostPrivacyEnum, MediaTypeEnum, ProcessingStatus
from common.exceptions import DomainValidationError, ResourceNotFoundError
from common.media import MediaOptimizerService

logger = logging.getLogger(__name__)

# File size constraints in bytes
MAX_PICTURE_SIZE_BYTES = 10 * 1024 * 1024    # 10 MB
MAX_VIDEO_SIZE_BYTES = 200 * 1024 * 1024     # 200 MB

ALLOWED_PICTURE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov"}


def validate_media_file(file: UploadedFile) -> str:
    """
    Validates uploaded media file format and size constraints.
    Returns detected MediaTypeEnum ('picture' or 'video').
    Raises DomainValidationError on invalid format or excessive size.
    """
    filename = getattr(file, "name", "")
    ext = Path(filename).suffix.lower()
    content_type = getattr(file, "content_type", "").lower()
    file_size = getattr(file, "size", 0)

    # 1. Determine if picture or video
    if ext in ALLOWED_PICTURE_EXTENSIONS or content_type.startswith("image/"):
        if ext not in ALLOWED_PICTURE_EXTENSIONS:
            raise DomainValidationError(
                f"Unsupported image format '{ext}'. Allowed formats: JPG, JPEG, PNG, WEBP."
            )
        if file_size > MAX_PICTURE_SIZE_BYTES:
            raise DomainValidationError(
                f"Image size exceeds the 10 MB limit ({file_size / (1024 * 1024):.2f} MB)."
            )
        return MediaTypeEnum.PICTURE

    elif ext in ALLOWED_VIDEO_EXTENSIONS or content_type.startswith("video/"):
        if ext not in ALLOWED_VIDEO_EXTENSIONS:
            raise DomainValidationError(
                f"Unsupported video format '{ext}'. Allowed formats: MP4, MOV."
            )
        if file_size > MAX_VIDEO_SIZE_BYTES:
            raise DomainValidationError(
                f"Video size exceeds the 200 MB limit ({file_size / (1024 * 1024):.2f} MB)."
            )
        return MediaTypeEnum.VIDEO

    else:
        raise DomainValidationError(
            f"Unsupported file format '{ext or filename}'. Supported formats are pictures (JPG, JPEG, PNG, WEBP) and videos (MP4, MOV)."
        )


@transaction.atomic
def create_post(
    gym: Gym,
    author_user: User,
    content_text: Optional[str] = None,
    privacy: str = PostPrivacyEnum.PUBLIC,
    media_files: Optional[List[UploadedFile]] = None,
    media_items: Optional[List[Dict[str, Any]]] = None,
) -> GymPost:
    """
    Atomically creates a new community post with text and/or media attachments.
    Business Rules:
    - Text is required unless media attachments are present.
    - Post cannot be entirely empty.
    - Media attachments are validated for format and size limits.
    - Dispatches asynchronous Celery task for image/video optimization.
    """
    text_clean = (content_text or "").strip()
    media_files = media_files or []
    media_items = media_items or []

    # Invariant: A post must contain either text or at least one media item
    if not text_clean and not media_files and not media_items:
        raise DomainValidationError("A post must contain either text or at least one media attachment.")

    if privacy not in PostPrivacyEnum.values:
        raise DomainValidationError(f"Invalid privacy setting '{privacy}'. Choices: {PostPrivacyEnum.values}.")

    post = GymPost.objects.create(
        gym=gym,
        author_user=author_user,
        content_text=text_clean or None,
        privacy=privacy,
    )

    order_index = 0

    # 1. Process directly uploaded media files (multipart/form-data)
    for file in media_files:
        media_type = validate_media_file(file)
        file_size = getattr(file, "size", 0)

        _, public_url = MediaOptimizerService.save_uploaded_file(
            file=file,
            subfolder="posts/media/original",
        )

        media_obj = GymPostMedia.objects.create(
            post=post,
            media_url=public_url,
            original_url=public_url,
            media_type=media_type,
            file_size_bytes=file_size,
            order_index=order_index,
            processing_status=ProcessingStatus.PENDING,
        )
        order_index += 1

        # Dispatch background optimization task after transaction commits
        try:
            from apps.posts.tasks import optimize_post_media_task
            transaction.on_commit(lambda mid=str(media_obj.id): optimize_post_media_task.delay(mid))
        except Exception as e:
            logger.warning(f"Could not enqueue optimization task for post media {media_obj.id}: {e}")

    # 2. Process pre-uploaded media references (JSON metadata)
    for item_data in media_items:
        m_url = (item_data.get("media_url") or "").strip()
        if not m_url:
            raise DomainValidationError("media_url is required for each media item.")
        m_type = item_data.get("media_type", MediaTypeEnum.PICTURE)
        if m_type not in MediaTypeEnum.values:
            raise DomainValidationError(f"Invalid media_type '{m_type}'. Choices: {MediaTypeEnum.values}.")

        f_size = int(item_data.get("file_size_bytes") or 0)
        custom_order = int(item_data.get("order_index") if item_data.get("order_index") is not None else order_index)
        thumb_url = (item_data.get("thumbnail_url") or "").strip() or None

        GymPostMedia.objects.create(
            post=post,
            media_url=m_url,
            original_url=m_url,
            media_type=m_type,
            thumbnail_url=thumb_url,
            file_size_bytes=f_size,
            order_index=custom_order,
            processing_status=ProcessingStatus.COMPLETED if thumb_url else ProcessingStatus.PENDING,
        )
        order_index += 1

    return post


@transaction.atomic
def update_post(
    post: GymPost,
    content_text: Optional[str] = None,
    privacy: Optional[str] = None,
    media_order: Optional[List[Dict[str, Any]]] = None,
) -> GymPost:
    """
    Updates post text, privacy, or re-arranges media attachment display order.
    """
    update_fields = ["updated_at"]

    if content_text is not None:
        text_clean = content_text.strip()
        # Invariant: cannot remove text if there are no media attachments
        if not text_clean and not post.media_attachments.exists():
            raise DomainValidationError("A post cannot be left empty without text or media attachments.")
        post.content_text = text_clean or None
        update_fields.append("content_text")

    if privacy is not None:
        if privacy not in PostPrivacyEnum.values:
            raise DomainValidationError(f"Invalid privacy setting '{privacy}'. Choices: {PostPrivacyEnum.values}.")
        post.privacy = privacy
        update_fields.append("privacy")

    post.save(update_fields=update_fields)

    # Re-order media attachments if requested
    if media_order is not None:
        for order_entry in media_order:
            media_id = order_entry.get("media_id") or order_entry.get("id")
            new_idx = order_entry.get("order_index")
            if media_id and new_idx is not None:
                post.media_attachments.filter(id=media_id).update(order_index=int(new_idx))

    return post


@transaction.atomic
def update_video_thumbnail(
    post_media: GymPostMedia,
    custom_thumbnail_file: UploadedFile,
) -> GymPostMedia:
    """
    Allows gym staff to replace the auto-generated video thumbnail with a custom image.
    """
    if post_media.media_type != MediaTypeEnum.VIDEO:
        raise DomainValidationError("Custom thumbnails can only be uploaded for video attachments.")

    # Validate custom thumbnail image
    filename = getattr(custom_thumbnail_file, "name", "")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_PICTURE_EXTENSIONS:
        raise DomainValidationError(
            f"Unsupported thumbnail image format '{ext}'. Allowed formats: JPG, JPEG, PNG, WEBP."
        )
    if getattr(custom_thumbnail_file, "size", 0) > MAX_PICTURE_SIZE_BYTES:
        raise DomainValidationError("Thumbnail image size exceeds the 10 MB limit.")

    # Save and optimize thumbnail image
    src_path, public_url = MediaOptimizerService.save_uploaded_file(
        file=custom_thumbnail_file,
        subfolder="posts/thumbnails/custom",
    )

    try:
        result = MediaOptimizerService.optimize_image(
            src_path=src_path,
            subfolder="posts/thumbnails/custom",
            max_dims=(1280, 720),
            thumb_dims=(500, 500),
            quality=85,
        )
        post_media.thumbnail_url = result["thumbnail_url"] or result["optimized_url"]
    except Exception as e:
        logger.warning(f"Could not optimize custom thumbnail: {e}, falling back to original upload")
        post_media.thumbnail_url = public_url

    post_media.save(update_fields=["thumbnail_url"])
    return post_media


@transaction.atomic
def delete_post(post: GymPost) -> None:
    """
    Deletes post entity and cleans up associated attachments.
    """
    # Delete associated media files from local disk if present
    for media in post.media_attachments.all():
        for url_field in [media.original_url, media.optimized_url, media.thumbnail_url, media.media_url]:
            if url_field:
                p = MediaOptimizerService.get_absolute_path(url_field)
                if p and p.exists() and p.is_file():
                    try:
                        p.unlink()
                    except OSError:
                        pass

    post.delete()
