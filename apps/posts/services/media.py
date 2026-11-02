import logging
from pathlib import Path
from django.db import transaction
from django.core.files.uploadedfile import UploadedFile
from apps.posts.models import GymPostMedia
from common.enums import MediaTypeEnum
from common.exceptions import DomainValidationError
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
