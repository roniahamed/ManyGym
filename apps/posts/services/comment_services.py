import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from PIL import Image
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import F, Q
from django.db.models.functions import Greatest
from django.utils import timezone

from apps.access_control.models import GymStaffAssignment
from apps.gyms.models import Gym, GymBlockedUser, GymSetting
from apps.posts.models import GymPost, PostComment
from apps.posts.selectors import get_post_detail_by_id
from apps.users.models import User, UserBlockedUser
from common.enums import (
    CommentMediaTypeEnum,
    PostOwnerTypeEnum,
    ProcessingStatus,
    StaffStatus,
    TokenContextType,
)
from common.exceptions import (
    DomainValidationError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from common.media import (
    ALLOWED_PICTURE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    MAX_PICTURE_SIZE_BYTES,
    MAX_VIDEO_SIZE_BYTES,
    MediaOptimizerService,
)

logger = logging.getLogger(__name__)

MAX_COMMENT_TEXT_LENGTH = 5000
MAX_COMMENT_DEPTH = 10
ALLOWED_GIF_EXTENSIONS = {".gif"}
ALLOWED_PHOTO_URL_EXTENSIONS = ALLOWED_PICTURE_EXTENSIONS | {".avif", ".bmp", ".heic", ".tiff", ".jfif"}
ALLOWED_VIDEO_URL_EXTENSIONS = ALLOWED_VIDEO_EXTENSIONS | {".webm"}
DISALLOWED_URL_EXTENSIONS = {".exe", ".sh", ".bat", ".cmd", ".php", ".js", ".html", ".htm", ".svg"}

UNSET = object()


def _unlink_local_media_urls(urls: List[Optional[str]]) -> None:
    """Removes local media files on disk for deleted or replaced comment attachments."""
    seen = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        if not str(url).startswith("/media/"):
            continue
        path = MediaOptimizerService.get_absolute_path(url)
        if path and path.exists() and path.is_file():
            try:
                path.unlink()
            except OSError:
                logger.warning(f"Failed to remove local comment media file {path}")


def _validate_comment_text(comment_text: Optional[str]) -> Optional[str]:
    if comment_text is None:
        return None
    if not isinstance(comment_text, str) or "\x00" in comment_text:
        raise DomainValidationError("Invalid comment_text value.")
    cleaned = comment_text.strip()
    if len(cleaned) > MAX_COMMENT_TEXT_LENGTH:
        raise DomainValidationError(
            f"comment_text cannot exceed {MAX_COMMENT_TEXT_LENGTH} characters."
        )
    return cleaned or None


def _validate_comment_photo_file(file: UploadedFile) -> None:
    filename = getattr(file, "name", "") or ""
    if "\x00" in filename:
        raise DomainValidationError("Invalid filename.")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_PICTURE_EXTENSIONS:
        raise DomainValidationError(
            f"Unsupported comment photo format '{ext}'. Allowed formats: JPG, JPEG, PNG, WEBP."
        )
    file_size = getattr(file, "size", 0) or 0
    if file_size > MAX_PICTURE_SIZE_BYTES:
        raise DomainValidationError(
            f"Comment photo size exceeds the 10 MB limit ({file_size / (1024 * 1024):.2f} MB)."
        )


def _validate_comment_video_file(file: UploadedFile) -> None:
    filename = getattr(file, "name", "") or ""
    if "\x00" in filename:
        raise DomainValidationError("Invalid filename.")
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise DomainValidationError(
            f"Unsupported comment video format '{ext}'. Allowed formats: MP4, MOV."
        )
    file_size = getattr(file, "size", 0) or 0
    if file_size > MAX_VIDEO_SIZE_BYTES:
        raise DomainValidationError(
            f"Comment video size exceeds the 200 MB limit ({file_size / (1024 * 1024):.2f} MB)."
        )


def _validate_comment_gif_file(file: UploadedFile) -> Tuple[Optional[int], Optional[int]]:
    filename = getattr(file, "name", "") or ""
    if "\x00" in filename:
        raise DomainValidationError("Invalid filename.")
    ext = Path(filename).suffix.lower()
    content_type = (getattr(file, "content_type", "") or "").lower()
    if ext not in ALLOWED_GIF_EXTENSIONS and content_type != "image/gif":
        raise DomainValidationError(
            f"Unsupported comment GIF format '{ext}'. Allowed format: GIF."
        )
    file_size = getattr(file, "size", 0) or 0
    if file_size > MAX_PICTURE_SIZE_BYTES:
        raise DomainValidationError(
            f"Comment GIF size exceeds the 10 MB limit ({file_size / (1024 * 1024):.2f} MB)."
        )
    try:
        if hasattr(file, "seek"):
            file.seek(0)
        with Image.open(file) as gif_img:
            dims = gif_img.size
        if hasattr(file, "seek"):
            file.seek(0)
        return dims
    except Exception:
        raise DomainValidationError("Uploaded comment_gif is not a valid GIF image.")


def _validate_comment_media_url(url: str, media_kind: str) -> str:
    if not isinstance(url, str) or "\x00" in url:
        raise DomainValidationError(f"Invalid {media_kind} URL.")
    cleaned = url.strip()
    if not cleaned:
        raise DomainValidationError(f"{media_kind} URL cannot be empty.")
    if len(cleaned) > 1000:
        raise DomainValidationError(f"{media_kind} URL cannot exceed 1000 characters.")

    parsed = urlparse(cleaned)
    is_http = parsed.scheme in ("http", "https") and bool(parsed.netloc)
    is_local_media = cleaned.startswith("/media/")
    if not (is_http or is_local_media):
        raise DomainValidationError(f"{media_kind} must be a valid http(s) URL or /media/ path.")

    ext = Path(parsed.path).suffix.lower()
    if ext in DISALLOWED_URL_EXTENSIONS:
        raise DomainValidationError(f"Unsupported {media_kind} URL file extension '{ext}'.")

    if media_kind == CommentMediaTypeEnum.PHOTO and ext and ext not in ALLOWED_PHOTO_URL_EXTENSIONS:
        raise DomainValidationError(
            f"Unsupported comment photo URL extension '{ext}'. Allowed: JPG, JPEG, PNG, WEBP."
        )
    if media_kind == CommentMediaTypeEnum.VIDEO and ext and ext not in ALLOWED_VIDEO_URL_EXTENSIONS:
        raise DomainValidationError(
            f"Unsupported comment video URL extension '{ext}'. Allowed: MP4, MOV, WEBM."
        )
    if media_kind == CommentMediaTypeEnum.GIF and ext in (ALLOWED_VIDEO_URL_EXTENSIONS - {".gif"}):
        raise DomainValidationError(
            f"comment_gif cannot reference a video file extension '{ext}'."
        )

    return cleaned


def _resolve_media_payload(
    photo_file: Optional[UploadedFile] = None,
    video_file: Optional[UploadedFile] = None,
    gif_file: Optional[UploadedFile] = None,
    photo_url: Any = UNSET,
    video_url: Any = UNSET,
    gif_url: Any = UNSET,
) -> Dict[str, Any]:
    """
    Validates and normalizes comment media inputs (uploaded file or URL).
    Returns a descriptor dict indicating:
    - mode: 'none' | 'clear' | 'set'
    - media_type: 'photo' | 'video' | 'gif' | None
    - file: UploadedFile | None
    - url: str | None
    - gif_dims: tuple[int, int] | None
    """
    provided_kinds: List[str] = []

    has_photo_url = photo_url is not UNSET and bool(str(photo_url or "").strip())
    has_video_url = video_url is not UNSET and bool(str(video_url or "").strip())
    has_gif_url = gif_url is not UNSET and bool(str(gif_url or "").strip())

    if photo_file is not None and has_photo_url:
        raise DomainValidationError("Provide either an uploaded comment_photo file or URL, not both.")
    if video_file is not None and has_video_url:
        raise DomainValidationError("Provide either an uploaded comment_video file or URL, not both.")
    if gif_file is not None and has_gif_url:
        raise DomainValidationError("Provide either an uploaded comment_gif file or URL, not both.")

    if photo_file is not None or has_photo_url:
        provided_kinds.append(CommentMediaTypeEnum.PHOTO)
    if video_file is not None or has_video_url:
        provided_kinds.append(CommentMediaTypeEnum.VIDEO)
    if gif_file is not None or has_gif_url:
        provided_kinds.append(CommentMediaTypeEnum.GIF)

    if len(provided_kinds) > 1:
        raise DomainValidationError(
            "A comment can contain at most one media attachment (comment_photo, comment_video, or comment_gif)."
        )

    if not provided_kinds:
        explicit_clear = (
            (photo_url is None or (isinstance(photo_url, str) and not photo_url.strip()))
            or (video_url is None or (isinstance(video_url, str) and not video_url.strip()))
            or (gif_url is None or (isinstance(gif_url, str) and not gif_url.strip()))
        )
        return {
            "mode": "clear" if explicit_clear else "none",
            "media_type": None,
            "file": None,
            "url": None,
            "gif_dims": None,
            "cleared_fields": {
                k
                for k, v in (
                    (CommentMediaTypeEnum.PHOTO, photo_url),
                    (CommentMediaTypeEnum.VIDEO, video_url),
                    (CommentMediaTypeEnum.GIF, gif_url),
                )
                if v is not UNSET and (v is None or (isinstance(v, str) and not v.strip()))
            },
        }

    kind = provided_kinds[0]
    if kind == CommentMediaTypeEnum.PHOTO:
        if photo_file is not None:
            _validate_comment_photo_file(photo_file)
            return {"mode": "set", "media_type": kind, "file": photo_file, "url": None, "gif_dims": None}
        return {
            "mode": "set",
            "media_type": kind,
            "file": None,
            "url": _validate_comment_media_url(str(photo_url), kind),
            "gif_dims": None,
        }

    if kind == CommentMediaTypeEnum.VIDEO:
        if video_file is not None:
            _validate_comment_video_file(video_file)
            return {"mode": "set", "media_type": kind, "file": video_file, "url": None, "gif_dims": None}
        return {
            "mode": "set",
            "media_type": kind,
            "file": None,
            "url": _validate_comment_media_url(str(video_url), kind),
            "gif_dims": None,
        }

    # GIF
    if gif_file is not None:
        gif_dims = _validate_comment_gif_file(gif_file)
        return {"mode": "set", "media_type": kind, "file": gif_file, "url": None, "gif_dims": gif_dims}
    return {
        "mode": "set",
        "media_type": kind,
        "file": None,
        "url": _validate_comment_media_url(str(gif_url), kind),
        "gif_dims": None,
    }


def _apply_media_to_comment(
    comment: PostComment,
    media_spec: Dict[str, Any],
    duration_seconds: Any = UNSET,
) -> Tuple[bool, List[str]]:
    """
    Applies resolved media attachment descriptor to a PostComment instance (unsaved or saved).
    Returns: (needs_async_optimization, old_local_urls_to_unlink)
    """
    old_urls: List[str] = []
    for existing_url in (
        comment.comment_photo,
        comment.comment_video,
        comment.comment_gif,
        comment.original_url,
        comment.optimized_url,
        comment.thumbnail_url,
    ):
        if existing_url:
            old_urls.append(existing_url)

    if duration_seconds is not UNSET:
        if duration_seconds is None:
            comment.duration_seconds = None
        else:
            if isinstance(duration_seconds, bool) or float(duration_seconds) < 0:
                raise DomainValidationError("duration_seconds must be a non-negative number.")
            comment.duration_seconds = float(duration_seconds)

    if media_spec["mode"] == "none":
        return False, []

    if media_spec["mode"] == "clear":
        cleared_fields = media_spec.get("cleared_fields") or set()
        # Only clear existing media if the cleared field matches the currently active media_type (or all cleared)
        if comment.media_type and comment.media_type not in cleared_fields:
            return False, []
        comment.comment_photo = None
        comment.comment_video = None
        comment.comment_gif = None
        comment.media_type = None
        comment.original_url = None
        comment.optimized_url = None
        comment.thumbnail_url = None
        comment.width = None
        comment.height = None
        comment.size_bytes = None
        comment.optimized_size_bytes = None
        comment.file_size_bytes = 0
        comment.duration_seconds = None
        comment.processing_status = ProcessingStatus.COMPLETED
        return False, old_urls

    # Reset all media columns before applying the new attachment
    comment.comment_photo = None
    comment.comment_video = None
    comment.comment_gif = None
    comment.original_url = None
    comment.optimized_url = None
    comment.thumbnail_url = None
    comment.width = None
    comment.height = None
    comment.size_bytes = None
    comment.optimized_size_bytes = None
    comment.file_size_bytes = 0

    kind = media_spec["media_type"]
    uploaded_file: Optional[UploadedFile] = media_spec["file"]
    resolved_url: Optional[str] = media_spec["url"]

    comment.media_type = kind

    if uploaded_file is not None:
        f_size = int(getattr(uploaded_file, "size", 0) or 0)
        subfolder_map = {
            CommentMediaTypeEnum.PHOTO: "posts/comments/photos/original",
            CommentMediaTypeEnum.VIDEO: "posts/comments/videos/original",
            CommentMediaTypeEnum.GIF: "posts/comments/gifs",
        }
        _, public_url = MediaOptimizerService.save_uploaded_file(
            file=uploaded_file,
            subfolder=subfolder_map[kind],
        )
        comment.original_url = public_url
        comment.file_size_bytes = f_size
        comment.size_bytes = f_size

        if kind == CommentMediaTypeEnum.PHOTO:
            comment.comment_photo = public_url
            comment.processing_status = ProcessingStatus.PENDING
            return True, old_urls
        if kind == CommentMediaTypeEnum.VIDEO:
            comment.comment_video = public_url
            comment.processing_status = ProcessingStatus.PENDING
            return True, old_urls

        # Animated GIFs are served directly to preserve animation frames
        comment.comment_gif = public_url
        comment.optimized_url = public_url
        comment.optimized_size_bytes = f_size
        if media_spec.get("gif_dims"):
            comment.width, comment.height = media_spec["gif_dims"]
        comment.processing_status = ProcessingStatus.COMPLETED
        return False, old_urls

    # Pre-uploaded or external URL
    comment.original_url = resolved_url
    comment.optimized_url = resolved_url
    comment.processing_status = ProcessingStatus.COMPLETED
    if kind == CommentMediaTypeEnum.PHOTO:
        comment.comment_photo = resolved_url
    elif kind == CommentMediaTypeEnum.VIDEO:
        comment.comment_video = resolved_url
    else:
        comment.comment_gif = resolved_url
    return False, old_urls


def _collect_ancestor_comment_ids(parent_comment: Optional[PostComment]) -> List[uuid.UUID]:
    """Walks the parent chain up to root_comment to gather ancestor IDs for counter updates."""
    ancestor_ids: List[uuid.UUID] = []
    current = parent_comment
    seen = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        ancestor_ids.append(current.id)
        if not current.source_comment_id:
            break
        current = (
            PostComment.objects.only("id", "source_comment_id")
            .filter(id=current.source_comment_id)
            .first()
        )
    return ancestor_ids


def validate_comment_target(
    actor_user: User,
    source_post_id=None,
    source_comment_id=None,
) -> Tuple[GymPost, Optional[PostComment]]:
    """
    Validates target post and optional parent comment for commenting/replying.
    Enforces post privacy, user/gym blocklists, lifecycle checks, and nesting depth cap.
    """
    if not actor_user or not getattr(actor_user, "is_authenticated", False):
        raise PermissionDeniedError("Authentication credentials were not provided.")

    actor_setting = actor_user.get_settings()
    if actor_setting.is_deleted or actor_setting.is_deactivated:
        raise PermissionDeniedError("Your account is deactivated or deleted.")

    parsed_post_uuid: Optional[uuid.UUID] = None
    if source_post_id is not None and str(source_post_id).strip() != "":
        try:
            parsed_post_uuid = uuid.UUID(str(source_post_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid source_post_id UUID.")

    source_comment: Optional[PostComment] = None
    if source_comment_id is not None and str(source_comment_id).strip() != "":
        try:
            comment_uuid = uuid.UUID(str(source_comment_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid source_comment_id UUID.")

        source_comment = (
            PostComment.objects.select_related(
                "user",
                "user__settings",
                "gym",
                "gym__settings",
                "source_post",
            )
            .filter(id=comment_uuid)
            .first()
        )
        if not source_comment:
            raise ResourceNotFoundError("Parent comment not found.")

        if parsed_post_uuid is not None and source_comment.source_post_id != parsed_post_uuid:
            raise DomainValidationError(
                "source_comment_id does not belong to the specified source_post_id."
            )
        parsed_post_uuid = source_comment.source_post_id

        parent_author = source_comment.user
        parent_setting = parent_author.get_settings()
        is_self = actor_user.is_superuser or actor_user.id == parent_author.id
        if parent_setting.is_deleted or (parent_setting.is_deactivated and not is_self):
            raise ResourceNotFoundError("Parent comment not found.")

        if not is_self:
            is_blocked = UserBlockedUser.objects.filter(
                Q(blocker=parent_author, blocked_user=actor_user)
                | Q(blocker=actor_user, blocked_user=parent_author)
            ).exists()
            if is_blocked:
                raise PermissionDeniedError("You cannot reply to this user's comment.")

        if source_comment.owner_type == PostOwnerTypeEnum.GYM and source_comment.gym:
            gym_setting = getattr(source_comment.gym, "settings", None) or GymSetting.objects.filter(
                gym=source_comment.gym
            ).first()
            if gym_setting and gym_setting.is_deleted:
                raise ResourceNotFoundError("Parent comment not found.")
            if not actor_user.is_superuser and GymBlockedUser.objects.filter(
                gym=source_comment.gym, user=actor_user
            ).exists():
                raise PermissionDeniedError("You have been blocked by this gym.")

        if source_comment.depth >= MAX_COMMENT_DEPTH:
            raise DomainValidationError(
                f"Maximum nested comment depth ({MAX_COMMENT_DEPTH}) reached."
            )

    if parsed_post_uuid is None:
        raise DomainValidationError("source_post_id is required.")

    source_post = get_post_detail_by_id(
        post_id=parsed_post_uuid,
        requesting_user=actor_user,
        for_management=False,
    )

    return source_post, source_comment


@transaction.atomic
def create_comment(
    actor_user: User,
    source_post_id=None,
    source_comment_id=None,
    owner_type: str = PostOwnerTypeEnum.USER,
    gym: Optional[Gym] = None,
    comment_text: Optional[str] = None,
    photo_file: Optional[UploadedFile] = None,
    video_file: Optional[UploadedFile] = None,
    gif_file: Optional[UploadedFile] = None,
    photo_url: Any = UNSET,
    video_url: Any = UNSET,
    gif_url: Any = UNSET,
    duration_seconds: Any = UNSET,
) -> PostComment:
    """
    Atomically creates a comment on a post or a nested reply on an existing comment.
    Validates target visibility, enforces single-media attachment (photo/video/gif),
    maintains exact post & ancestor reply counts, and schedules async media optimization.
    """
    if owner_type not in PostOwnerTypeEnum.values:
        raise DomainValidationError(f"Unsupported owner_type '{owner_type}'.")
    if owner_type == PostOwnerTypeEnum.GYM and gym is None:
        raise DomainValidationError("A gym is required when commenting as a gym.")
    if owner_type == PostOwnerTypeEnum.USER and gym is not None:
        raise DomainValidationError("Personal user comments cannot be bound to a gym.")

    source_post, source_comment = validate_comment_target(
        actor_user=actor_user,
        source_post_id=source_post_id,
        source_comment_id=source_comment_id,
    )

    cleaned_text = _validate_comment_text(comment_text)
    media_spec = _resolve_media_payload(
        photo_file=photo_file,
        video_file=video_file,
        gif_file=gif_file,
        photo_url=photo_url,
        video_url=video_url,
        gif_url=gif_url,
    )

    if not cleaned_text and media_spec["mode"] != "set":
        raise DomainValidationError(
            "A comment must contain either comment_text or a media attachment (comment_photo, comment_video, or comment_gif)."
        )

    if source_comment is not None:
        depth = source_comment.depth + 1
        root_comment_id = source_comment.root_comment_id or source_comment.id
        reply_to_user = source_comment.user
    else:
        depth = 0
        root_comment_id = None
        reply_to_user = None

    comment = PostComment(
        source_post=source_post,
        source_comment=source_comment,
        root_comment_id=root_comment_id,
        depth=depth,
        user=actor_user,
        reply_to_user=reply_to_user,
        owner_type=owner_type,
        gym=gym if owner_type == PostOwnerTypeEnum.GYM else None,
        comment_text=cleaned_text,
        processing_status=ProcessingStatus.COMPLETED,
    )

    needs_async, _ = _apply_media_to_comment(
        comment=comment,
        media_spec=media_spec,
        duration_seconds=duration_seconds,
    )
    comment.save()

    # Maintain atomic counters on post and ancestor comments
    GymPost.objects.filter(id=source_post.id).update(comments_count=F("comments_count") + 1)

    if source_comment is not None:
        PostComment.objects.filter(id=source_comment.id).update(
            replies_count=F("replies_count") + 1
        )
        ancestor_ids = _collect_ancestor_comment_ids(source_comment)
        if ancestor_ids:
            PostComment.objects.filter(id__in=ancestor_ids).update(
                total_replies_count=F("total_replies_count") + 1
            )

    if needs_async:
        try:
            from apps.posts.tasks import optimize_comment_media_task
            transaction.on_commit(lambda cid=str(comment.id): optimize_comment_media_task.delay(cid))
        except Exception as exc:
            logger.warning(f"Could not enqueue optimization task for comment {comment.id}: {exc}")

    return comment


@transaction.atomic
def update_comment(
    comment: PostComment,
    comment_text: Any = UNSET,
    photo_file: Optional[UploadedFile] = None,
    video_file: Optional[UploadedFile] = None,
    gif_file: Optional[UploadedFile] = None,
    photo_url: Any = UNSET,
    video_url: Any = UNSET,
    gif_url: Any = UNSET,
    remove_media: bool = False,
    duration_seconds: Any = UNSET,
) -> PostComment:
    """
    Updates a comment's text and/or media attachment while preserving the
    non-empty and single-media invariants.
    """
    changed = False

    if comment_text is not UNSET:
        cleaned_text = _validate_comment_text(comment_text)
        if cleaned_text != comment.comment_text:
            comment.comment_text = cleaned_text
            changed = True

    if remove_media:
        media_spec: Dict[str, Any] = {
            "mode": "clear",
            "media_type": None,
            "file": None,
            "url": None,
            "gif_dims": None,
            "cleared_fields": {
                CommentMediaTypeEnum.PHOTO,
                CommentMediaTypeEnum.VIDEO,
                CommentMediaTypeEnum.GIF,
            },
        }
    else:
        media_spec = _resolve_media_payload(
            photo_file=photo_file,
            video_file=video_file,
            gif_file=gif_file,
            photo_url=photo_url,
            video_url=video_url,
            gif_url=gif_url,
        )

    needs_async, old_urls = _apply_media_to_comment(
        comment=comment,
        media_spec=media_spec,
        duration_seconds=duration_seconds,
    )
    if media_spec["mode"] != "none" or duration_seconds is not UNSET:
        changed = True

    if not comment.comment_text and not comment.active_media_url:
        raise DomainValidationError(
            "A comment cannot be left empty without comment_text or a media attachment."
        )

    if changed:
        comment.is_edited = True
        comment.edited_at = timezone.now()
        comment.save()

        if old_urls:
            transaction.on_commit(lambda urls=list(old_urls): _unlink_local_media_urls(urls))

        if needs_async:
            try:
                from apps.posts.tasks import optimize_comment_media_task
                transaction.on_commit(lambda cid=str(comment.id): optimize_comment_media_task.delay(cid))
            except Exception as exc:
                logger.warning(f"Could not enqueue optimization task for comment {comment.id}: {exc}")

    return comment


def _collect_descendant_comments(comment: PostComment) -> List[PostComment]:
    """
    Collects all descendant comments under `comment` in O(1) query for the thread
    so counters and local media files are accurately cleaned up on cascade delete.
    """
    if comment.total_replies_count == 0 and comment.replies_count == 0:
        return []

    if comment.source_comment_id is None:
        return list(
            PostComment.objects.filter(root_comment_id=comment.id).only(
                "id",
                "comment_photo",
                "comment_video",
                "comment_gif",
                "original_url",
                "optimized_url",
                "thumbnail_url",
            )
        )

    # Descendant subtree belongs to the same root_comment with strictly greater depth
    thread_nodes = list(
        PostComment.objects.filter(
            root_comment_id=comment.root_comment_id,
            depth__gt=comment.depth,
        ).only(
            "id",
            "source_comment_id",
            "comment_photo",
            "comment_video",
            "comment_gif",
            "original_url",
            "optimized_url",
            "thumbnail_url",
        )
    )
    children_map: Dict[uuid.UUID, List[PostComment]] = {}
    for node in thread_nodes:
        children_map.setdefault(node.source_comment_id, []).append(node)

    descendants: List[PostComment] = []
    queue: List[uuid.UUID] = [comment.id]
    while queue:
        curr_id = queue.pop(0)
        for child in children_map.get(curr_id, []):
            descendants.append(child)
            queue.append(child.id)
    return descendants


@transaction.atomic
def delete_comment(comment: PostComment) -> int:
    """
    Deletes a comment and its nested reply subtree, atomically decrements
    GymPost.comments_count and ancestor reply counters, and removes orphaned local files.
    Returns total number of deleted comment rows (1 + descendants).
    """
    descendants = _collect_descendant_comments(comment)
    total_deleted = 1 + len(descendants)

    urls_to_cleanup: List[Optional[str]] = []
    for node in [comment, *descendants]:
        urls_to_cleanup.extend(
            [
                node.comment_photo,
                node.comment_video,
                node.comment_gif,
                node.original_url,
                node.optimized_url,
                node.thumbnail_url,
            ]
        )

    source_post_id = comment.source_post_id
    parent_comment_id = comment.source_comment_id
    ancestor_ids = _collect_ancestor_comment_ids(comment.source_comment) if parent_comment_id else []

    comment.delete()

    GymPost.objects.filter(id=source_post_id).update(
        comments_count=Greatest(F("comments_count") - total_deleted, 0)
    )

    if parent_comment_id:
        PostComment.objects.filter(id=parent_comment_id).update(
            replies_count=Greatest(F("replies_count") - 1, 0)
        )
    if ancestor_ids:
        PostComment.objects.filter(id__in=ancestor_ids).update(
            total_replies_count=Greatest(F("total_replies_count") - total_deleted, 0)
        )

    if urls_to_cleanup:
        transaction.on_commit(lambda urls=urls_to_cleanup: _unlink_local_media_urls(urls))

    return total_deleted


def _user_can_manage_gym_posts(user: User, gym: Optional[Gym]) -> bool:
    if not user or not getattr(user, "is_authenticated", False) or not gym:
        return False
    if user.is_superuser or gym.owner_user_id == user.id:
        return True
    assignment = (
        GymStaffAssignment.objects.select_related("role")
        .filter(gym=gym, user=user, status=StaffStatus.ACTIVE)
        .first()
    )
    if not assignment or not assignment.role:
        return False
    return assignment.role.permissions.filter(scope_code="posts:manage").exists()


def check_comment_edit_permission(request, comment: PostComment) -> None:
    """Only the comment author (or authorized gym staff for a gym-authored comment) can edit."""
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionDeniedError("Authentication credentials were not provided.")

    setting = user.get_settings()
    if setting.is_deleted or setting.is_deactivated:
        raise PermissionDeniedError("Your account is deactivated or deleted.")

    if user.is_superuser:
        return

    token_context = getattr(request, "token_context", TokenContextType.PERSONAL)
    token_gym_id = getattr(request, "gym_id", None)

    if comment.owner_type == PostOwnerTypeEnum.GYM and comment.gym:
        if token_context == TokenContextType.GYM and token_gym_id and str(comment.gym_id) != str(token_gym_id):
            raise ResourceNotFoundError("Comment not found.")
        if _user_can_manage_gym_posts(user, comment.gym):
            return
        raise PermissionDeniedError("You do not have permission to edit this gym comment.")

    if comment.user_id == user.id:
        return

    raise PermissionDeniedError("You do not have permission to edit this comment.")


def check_comment_delete_permission(request, comment: PostComment) -> None:
    """
    Allows comment deletion by:
    - Comment author (or gym staff with 'posts:manage' if comment was made as a gym)
    - Parent post owner (user post author, or gym owner/staff with 'posts:manage' on gym post)
    - Superuser
    """
    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionDeniedError("Authentication credentials were not provided.")

    setting = user.get_settings()
    if setting.is_deleted or setting.is_deactivated:
        raise PermissionDeniedError("Your account is deactivated or deleted.")

    if user.is_superuser:
        return

    token_context = getattr(request, "token_context", TokenContextType.PERSONAL)
    token_gym_id = getattr(request, "gym_id", None)

    # Comment owner check
    if comment.owner_type == PostOwnerTypeEnum.GYM and comment.gym:
        if token_context != TokenContextType.GYM or not token_gym_id or str(comment.gym_id) == str(token_gym_id):
            if _user_can_manage_gym_posts(user, comment.gym):
                return
    elif comment.user_id == user.id:
        return

    # Post owner / moderation check
    post = comment.source_post
    if post.owner_type == PostOwnerTypeEnum.USER or post.gym is None:
        if post.author_user_id == user.id:
            return
    elif post.gym is not None:
        if token_context == TokenContextType.GYM and token_gym_id and str(post.gym_id) != str(token_gym_id):
            raise ResourceNotFoundError("Comment not found.")
        if _user_can_manage_gym_posts(user, post.gym):
            return

    raise PermissionDeniedError("You do not have permission to delete this comment.")
