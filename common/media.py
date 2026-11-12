import os
import uuid
import shutil
import logging
import subprocess
from pathlib import Path
from PIL import Image, ImageOps
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_PICTURE_SIZE_BYTES = 10 * 1024 * 1024    # 10 MB
MAX_VIDEO_SIZE_BYTES = 200 * 1024 * 1024     # 200 MB

ALLOWED_PICTURE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov"}


def validate_media_file(file) -> str:
    """
    Validates uploaded media file format and size constraints.
    Returns detected MediaTypeEnum ('picture' or 'video').
    Raises DomainValidationError on invalid format, null bytes, or excessive size.
    """
    from common.enums import MediaTypeEnum
    from common.exceptions import DomainValidationError

    filename = getattr(file, "name", "") or ""
    if "\x00" in filename:
        raise DomainValidationError("Invalid filename.")

    ext = Path(filename).suffix.lower()
    content_type = (getattr(file, "content_type", "") or "").lower()
    file_size = getattr(file, "size", 0) or 0

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

    if ext in ALLOWED_VIDEO_EXTENSIONS or content_type.startswith("video/"):
        if ext not in ALLOWED_VIDEO_EXTENSIONS:
            raise DomainValidationError(
                f"Unsupported video format '{ext}'. Allowed formats: MP4, MOV."
            )
        if file_size > MAX_VIDEO_SIZE_BYTES:
            raise DomainValidationError(
                f"Video size exceeds the 200 MB limit ({file_size / (1024 * 1024):.2f} MB)."
            )
        return MediaTypeEnum.VIDEO

    raise DomainValidationError(
        f"Unsupported file format '{ext or filename}'. Supported formats are pictures (JPG, JPEG, PNG, WEBP) and videos (MP4, MOV)."
    )


class MediaOptimizerService:
    """
    Central reusable service for saving, optimizing, and resizing images and videos.
    Can be used by Gym Gallery, User Avatars, Gym Covers, Feeds, and Post attachments.
    """

    @staticmethod
    def get_absolute_path(url_or_path: str) -> Path | None:
        """Resolves a media URL or relative path to an absolute filesystem Path."""
        if not url_or_path:
            return None
        media_url = getattr(settings, "MEDIA_URL", "/media/")
        if url_or_path.startswith(media_url):
            rel = url_or_path[len(media_url):]
            return Path(settings.MEDIA_ROOT) / rel
        if url_or_path.startswith("/media/"):
            rel = url_or_path[7:]
            return Path(settings.MEDIA_ROOT) / rel
        path_obj = Path(url_or_path)
        if path_obj.is_absolute() and path_obj.exists():
            return path_obj
        return Path(settings.MEDIA_ROOT) / url_or_path

    @classmethod
    def save_uploaded_file(cls, file, subfolder: str = "gyms/gallery/original") -> tuple[Path, str]:
        """
        Saves an uploaded file chunk to the specified subfolder under MEDIA_ROOT.
        Returns: (absolute_file_path, public_media_url)
        """
        dest_dir = Path(settings.MEDIA_ROOT) / subfolder
        dest_dir.mkdir(parents=True, exist_ok=True)

        filename = getattr(file, "name", "upload")
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        local_target_path = dest_dir / unique_name

        with open(local_target_path, "wb+") as destination:
            for chunk in file.chunks():
                destination.write(chunk)

        media_url_base = getattr(settings, "MEDIA_URL", "/media/").rstrip("/")
        public_url = f"{media_url_base}/{subfolder.strip('/')}/{unique_name}"
        return local_target_path, public_url

    @classmethod
    def fix_orientation(cls, img: Image.Image) -> Image.Image:
        """
        Corrects image orientation using EXIF metadata.
        Prevents mobile camera photos from appearing rotated (e.g. 90 deg sideways or upside down).
        Transposes pixel data to match the intended orientation and strips the orientation tag
        to prevent downstream viewers or browsers from performing double-rotation.
        """
        try:
            transposed = ImageOps.exif_transpose(img)
            if transposed is not None:
                img = transposed
        except Exception as e:
            logger.warning(f"EXIF transpose encountered an issue: {e}")
            try:
                exif = img.getexif() if hasattr(img, "getexif") else None
                orientation = exif.get(0x0112) if exif else None
                if orientation == 2:
                    img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                elif orientation == 3:
                    img = img.transpose(Image.Transpose.ROTATE_180)
                elif orientation == 4:
                    img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                elif orientation == 5:
                    img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT).transpose(Image.Transpose.ROTATE_90)
                elif orientation == 6:
                    img = img.transpose(Image.Transpose.ROTATE_270)
                elif orientation == 7:
                    img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT).transpose(Image.Transpose.ROTATE_270)
                elif orientation == 8:
                    img = img.transpose(Image.Transpose.ROTATE_90)
            except Exception as fallback_err:
                logger.warning(f"Fallback orientation correction failed: {fallback_err}")
        return img

    @classmethod
    def normalize_color_mode(cls, img: Image.Image) -> Image.Image:
        """
        Normalizes any color mode (Palette P, CMYK, Grayscale L, 1-bit, LA)
        to standard RGB or RGBA compatible with WebP encoding.
        """
        if img.mode == "P":
            return img.convert("RGBA" if "transparency" in img.info else "RGB")
        if img.mode == "CMYK":
            return img.convert("RGB")
        if img.mode in ("RGBA", "LA"):
            return img.convert("RGBA")
        if img.mode != "RGB":
            return img.convert("RGB")
        return img

    @classmethod
    def convert_and_save_webp(
        cls,
        file,
        subfolder: str = "media",
        max_dims: tuple[int, int] = (1920, 1080),
        thumb_dims: tuple[int, int] = (400, 300),
        quality: int = 82,
        thumb_quality: int = 78,
    ) -> dict:
        """
        Directly converts any uploaded image format (JPEG, PNG, GIF, BMP, TIFF, WEBP, HEIC, etc.)
        to standardized, optimized WebP format with an accompanying thumbnail.

        Ensures:
        - Image orientation is properly corrected (EXIF transpose) to prevent rotated photos from mobile devices.
        - Color modes are safely converted (CMYK/P/LA -> RGB/RGBA) so WebP conversion never fails.
        - Directly saved as .webp on disk without needing unoptimized raw files.
        - Returns a dictionary containing URLs, dimensions, and file sizes.
        """
        if hasattr(file, "seek"):
            file.seek(0)

        try:
            raw_img = Image.open(file)
        except Exception as e:
            from common.exceptions import DomainValidationError
            raise DomainValidationError(f"Invalid or unreadable image file: {e}")

        # 1. EXIF orientation correction (prevents sideways / rotated pictures)
        img = cls.fix_orientation(raw_img)

        # 2. Color mode normalization
        img = cls.normalize_color_mode(img)

        width, height = img.size
        unique_id = uuid.uuid4().hex

        opt_dir = Path(settings.MEDIA_ROOT) / subfolder / "optimized"
        thumb_dir = Path(settings.MEDIA_ROOT) / subfolder / "thumbnails"
        opt_dir.mkdir(parents=True, exist_ok=True)
        thumb_dir.mkdir(parents=True, exist_ok=True)

        media_url_base = getattr(settings, "MEDIA_URL", "/media/").rstrip("/")

        # 3. High-res WebP optimized variant
        opt_img = img.copy()
        opt_img.thumbnail(max_dims, Image.Resampling.LANCZOS)
        opt_path = opt_dir / f"{unique_id}.webp"
        opt_img.save(opt_path, format="WEBP", quality=quality, method=6)

        # 4. WebP Thumbnail variant
        thumb_img = img.copy()
        thumb_img.thumbnail(thumb_dims, Image.Resampling.LANCZOS)
        thumb_path = thumb_dir / f"{unique_id}_thumb.webp"
        thumb_img.save(thumb_path, format="WEBP", quality=thumb_quality, method=6)

        opt_url = f"{media_url_base}/{subfolder.strip('/')}/optimized/{unique_id}.webp"
        thumb_url = f"{media_url_base}/{subfolder.strip('/')}/thumbnails/{unique_id}_thumb.webp"

        return {
            "width": width,
            "height": height,
            "optimized_url": opt_url,
            "thumbnail_url": thumb_url,
            "optimized_path": opt_path,
            "thumbnail_path": thumb_path,
            "optimized_size_bytes": opt_path.stat().st_size,
            "thumbnail_size_bytes": thumb_path.stat().st_size,
        }

    @classmethod
    def process_image_upload(
        cls,
        file=None,
        url: str | None = None,
        subfolder: str = "media",
        max_dims: tuple[int, int] = (1920, 1080),
        thumb_dims: tuple[int, int] = (400, 300),
        max_size_bytes: int = 10 * 1024 * 1024,
    ) -> str | None:
        """
        Unified helper to process image uploads across all apps:
        1. Validates size if file is provided.
        2. Corrects EXIF orientation so mobile pictures are never rotated.
        3. Directly converts any image format to WebP and saves as .webp.
        4. Returns the optimized WebP public URL.
        5. If only `url` is provided, returns sanitized `url`.
        """
        if file:
            from common.exceptions import DomainValidationError

            if getattr(file, "size", 0) > max_size_bytes:
                max_mb = max_size_bytes // (1024 * 1024)
                raise DomainValidationError(f"Image file cannot exceed {max_mb}MB.")

            result = cls.convert_and_save_webp(
                file=file,
                subfolder=subfolder.strip("/"),
                max_dims=max_dims,
                thumb_dims=thumb_dims,
            )
            return result.get("optimized_url")

        if url and str(url).strip():
            return str(url).strip()

        return None

    @classmethod
    def optimize_image(
        cls,
        src_path: Path,
        subfolder: str = "gyms/gallery",
        max_dims: tuple[int, int] = (1920, 1080),
        thumb_dims: tuple[int, int] = (400, 300),
        quality: int = 82,
        thumb_quality: int = 78,
    ) -> dict:
        """
        Optimizes an existing image file on disk:
        - Auto-orients via EXIF transpose (prevents rotated mobile photos)
        - Normalizes color mode to RGB / RGBA
        - Converts to high-res WebP (method=6)
        - Generates small WebP thumbnail (method=6)
        Returns: dictionary with optimized_url, thumbnail_url, width, height, size_bytes, optimized_size_bytes.
        """
        if not src_path or not src_path.exists():
            raise FileNotFoundError(f"Source file not found at {src_path}")

        stem = src_path.stem
        opt_dir = Path(settings.MEDIA_ROOT) / subfolder / "optimized"
        thumb_dir = Path(settings.MEDIA_ROOT) / subfolder / "thumbnails"
        opt_dir.mkdir(parents=True, exist_ok=True)
        thumb_dir.mkdir(parents=True, exist_ok=True)

        media_url_base = getattr(settings, "MEDIA_URL", "/media/").rstrip("/")

        with Image.open(src_path) as raw_img:
            # 1. EXIF orientation correction
            img = cls.fix_orientation(raw_img)

            # 2. Preserve alpha or convert to RGB
            img = cls.normalize_color_mode(img)

            width, height = img.size

            # 3. High-res WebP optimized variant
            opt_img = img.copy()
            opt_img.thumbnail(max_dims, Image.Resampling.LANCZOS)
            opt_file_path = opt_dir / f"{stem}_optimized.webp"
            opt_img.save(opt_file_path, format="WEBP", quality=quality, method=6)

            # 4. WebP Thumbnail variant
            thumb_img = img.copy()
            thumb_img.thumbnail(thumb_dims, Image.Resampling.LANCZOS)
            thumb_file_path = thumb_dir / f"{stem}_thumb.webp"
            thumb_img.save(thumb_file_path, format="WEBP", quality=thumb_quality, method=6)

            return {
                "width": width,
                "height": height,
                "size_bytes": src_path.stat().st_size,
                "optimized_size_bytes": opt_file_path.stat().st_size,
                "optimized_url": f"{media_url_base}/{subfolder.strip('/')}/optimized/{stem}_optimized.webp",
                "thumbnail_url": f"{media_url_base}/{subfolder.strip('/')}/thumbnails/{stem}_thumb.webp",
            }

    @classmethod
    def optimize_video(
        cls,
        src_path: Path,
        subfolder: str = "gyms/gallery",
    ) -> dict:
        """
        Extracts video poster thumbnail and optionally compresses high-bitrate video via FFmpeg.
        Returns: dictionary with thumbnail_url, optimized_url, size_bytes, optimized_size_bytes.
        """
        if not src_path or not src_path.exists():
            raise FileNotFoundError(f"Source video not found at {src_path}")

        stem = src_path.stem
        opt_dir = Path(settings.MEDIA_ROOT) / subfolder / "optimized"
        thumb_dir = Path(settings.MEDIA_ROOT) / subfolder / "thumbnails"
        opt_dir.mkdir(parents=True, exist_ok=True)
        thumb_dir.mkdir(parents=True, exist_ok=True)

        media_url_base = getattr(settings, "MEDIA_URL", "/media/").rstrip("/")
        size_bytes = src_path.stat().st_size

        ffmpeg_bin = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
        thumb_file_path = thumb_dir / f"{stem}_poster.jpg"
        thumbnail_url = None
        optimized_url = None
        optimized_size_bytes = None

        if os.path.exists(ffmpeg_bin):
            # Extract video poster frame
            cmd_thumb = [
                ffmpeg_bin, "-y", "-ss", "00:00:01",
                "-i", str(src_path), "-vframes", "1", "-q:v", "2",
                str(thumb_file_path),
            ]
            subprocess.run(cmd_thumb, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

            if thumb_file_path.exists():
                thumbnail_url = f"{media_url_base}/{subfolder.strip('/')}/thumbnails/{stem}_poster.jpg"

            # Transcode/compress video via H.264
            opt_video_path = opt_dir / f"{stem}_opt.mp4"
            cmd_opt = [
                ffmpeg_bin, "-y", "-i", str(src_path),
                "-vcodec", "libx264", "-crf", "26", "-preset", "fast",
                "-c:a", "aac", "-b:a", "128k",
                str(opt_video_path),
            ]
            subprocess.run(cmd_opt, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

            if opt_video_path.exists() and opt_video_path.stat().st_size < size_bytes:
                optimized_size_bytes = opt_video_path.stat().st_size
                optimized_url = f"{media_url_base}/{subfolder.strip('/')}/optimized/{stem}_opt.mp4"

        return {
            "size_bytes": size_bytes,
            "optimized_size_bytes": optimized_size_bytes,
            "thumbnail_url": thumbnail_url,
            "optimized_url": optimized_url,
        }
