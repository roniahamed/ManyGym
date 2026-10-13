import os
import uuid
import shutil
import logging
import subprocess
from pathlib import Path
from PIL import Image, ImageOps
from django.conf import settings

logger = logging.getLogger(__name__)


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
        Optimizes an image:
        - Auto-orients via EXIF transpose
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

        with Image.open(src_path) as img:
            # 1. EXIF orientation correction
            try:
                transposed = ImageOps.exif_transpose(img)
                if transposed is not None:
                    img = transposed
            except Exception as e:
                logger.warning(f"EXIF transpose error on {src_path}: {e}")

            # 2. Preserve alpha or convert to RGB
            if img.mode == "P":
                img = img.convert("RGBA" if "transparency" in img.info else "RGB")
            elif img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

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
