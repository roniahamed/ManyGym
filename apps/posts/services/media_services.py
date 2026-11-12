import logging
from pathlib import Path
from django.db import transaction
from django.core.files.uploadedfile import UploadedFile
from apps.posts.models import GymPostMedia
from common.enums import MediaTypeEnum
from common.exceptions import DomainValidationError
from common.media import (
    MediaOptimizerService,
    MAX_PICTURE_SIZE_BYTES,
    MAX_VIDEO_SIZE_BYTES,
    ALLOWED_PICTURE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    validate_media_file,
)

logger = logging.getLogger(__name__)


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
