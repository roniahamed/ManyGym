import logging
import re
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from apps.access_control.models import GymStaffAssignment
from apps.gyms.models import Gym, GymBlockedUser, GymSetting
from apps.members.models import Member
from apps.posts.models import GymPost
from apps.posts.selectors import check_posts_age_restriction
from apps.stories.models import Story, StoryView
from apps.stories.permissions import (
    check_story_creation_permission,
    has_gym_story_manage_permission,
)
from apps.users.models import User
from common.enums import (
    AdminLogActionType,
    AdminLogCategory,
    GYM_STORY_PRIVACY_VALUES,
    MediaTypeEnum,
    PostPrivacyEnum,
    ProcessingStatus,
    StaffStatus,
    StoryLifetimeEnum,
    StoryOwnerTypeEnum,
    StoryPrivacyEnum,
    USER_STORY_PRIVACY_VALUES,
)
from common.exceptions import (
    DomainValidationError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from common.media import (
    ALLOWED_PICTURE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    MediaOptimizerService,
    validate_media_file,
)

logger = logging.getLogger(__name__)

_LIFETIME_STRING_PATTERN = re.compile(r"^\s*(\d+)\s*(?:h|hr|hrs|hour|hours|_hours)?\s*$", re.IGNORECASE)
_HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def normalize_lifetime_hours(value) -> int:
    """
    Validates and normalizes story lifetime to one of {6, 12, 18, 24, 48}.
    Defaults to 18 hours when value is None or empty string.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return StoryLifetimeEnum.HOURS_18

    if isinstance(value, bool):
        raise DomainValidationError("Invalid lifetime. Allowed values: 6, 12, 18, 24, or 48 hours.")

    parsed: Optional[int] = None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        match = _LIFETIME_STRING_PATTERN.match(value)
        if match:
            parsed = int(match.group(1))
    else:
        raise DomainValidationError("Invalid lifetime. Allowed values: 6, 12, 18, 24, or 48 hours.")

    if parsed not in StoryLifetimeEnum.values:
        raise DomainValidationError(
            f"Invalid lifetime '{value}'. Allowed values: 6, 12, 18, 24, or 48 hours."
        )
    return parsed


def normalize_story_privacy(privacy: Optional[str], owner_type: str) -> str:
    """
    Validates and normalizes story privacy according to owner_type:
    - Public users ('user'): public, followers, private
    - Gyms ('gym'): public, followers, members_only, private
    """
    if privacy is None or (isinstance(privacy, str) and not privacy.strip()):
        return StoryPrivacyEnum.PUBLIC

    if not isinstance(privacy, str):
        raise DomainValidationError("Privacy must be a valid string.")

    cleaned = privacy.strip().lower().replace(" ", "_")
    if cleaned == "gym_members_only":
        cleaned = StoryPrivacyEnum.MEMBERS_ONLY

    if owner_type == StoryOwnerTypeEnum.USER:
        if cleaned == StoryPrivacyEnum.MEMBERS_ONLY:
            raise DomainValidationError(
                "Public user stories cannot use 'members_only' privacy. Allowed choices: public, followers, private."
            )
        if cleaned not in USER_STORY_PRIVACY_VALUES:
            raise DomainValidationError(
                f"Invalid privacy '{privacy}' for public user story. Allowed choices: {list(USER_STORY_PRIVACY_VALUES)}."
            )
        return cleaned

    if owner_type == StoryOwnerTypeEnum.GYM:
        if cleaned not in GYM_STORY_PRIVACY_VALUES:
            raise DomainValidationError(
                f"Invalid privacy '{privacy}' for gym story. Allowed choices: {list(GYM_STORY_PRIVACY_VALUES)}."
            )
        return cleaned

    raise DomainValidationError(f"Unsupported story owner_type '{owner_type}'.")


def extract_single_media_file(files_mapping) -> Optional[UploadedFile]:
    """
    Extracts a single UploadedFile from request.FILES while strictly enforcing the 1-file limit.
    Supports field names 'file', 'media_file', 'media', or 'files'.
    """
    if not files_mapping:
        return None

    all_files = []
    if hasattr(files_mapping, "lists"):
        for _, file_list in files_mapping.lists():
            all_files.extend(file_list)
    elif isinstance(files_mapping, dict):
        for val in files_mapping.values():
            if isinstance(val, (list, tuple)):
                all_files.extend(val)
            elif val is not None:
                all_files.append(val)

    if not all_files:
        return None

    if len(all_files) > 1:
        raise DomainValidationError(
            "Only 1 media file (image or video) is allowed per story."
        )

    return all_files[0]


def _validate_media_url_and_type(media_url: str, media_type: Optional[str]) -> tuple[str, str]:
    """
    Validates a pre-uploaded or external single media URL and resolves its MediaTypeEnum.
    """
    if not isinstance(media_url, str) or "\x00" in media_url:
        raise DomainValidationError("Invalid media_url.")

    cleaned_url = media_url.strip()
    if not cleaned_url:
        raise DomainValidationError("media_url cannot be empty.")
    if len(cleaned_url) > 1000:
        raise DomainValidationError("media_url cannot exceed 1000 characters.")

    parsed = urlparse(cleaned_url)
    is_http = parsed.scheme in ("http", "https") and bool(parsed.netloc)
    is_local_media = cleaned_url.startswith("/media/")
    if not (is_http or is_local_media):
        raise DomainValidationError("media_url must be a valid http(s) URL or /media/ path.")

    ext = Path(parsed.path).suffix.lower()
    inferred_type: Optional[str] = None
    if ext:
        if ext in ALLOWED_PICTURE_EXTENSIONS:
            inferred_type = MediaTypeEnum.PICTURE
        elif ext in ALLOWED_VIDEO_EXTENSIONS:
            inferred_type = MediaTypeEnum.VIDEO
        else:
            raise DomainValidationError(
                f"Unsupported media file format '{ext}'. Allowed pictures: JPG, JPEG, PNG, WEBP; videos: MP4, MOV."
            )

    if media_type is not None and media_type != "":
        if not isinstance(media_type, str) or media_type not in MediaTypeEnum.values:
            raise DomainValidationError(
                f"Invalid media_type '{media_type}'. Allowed choices: {MediaTypeEnum.values}."
            )
        if inferred_type and inferred_type != media_type:
            raise DomainValidationError(
                f"media_type '{media_type}' does not match media_url file extension '{ext}'."
            )
        resolved_type = media_type
    else:
        resolved_type = inferred_type or MediaTypeEnum.PICTURE

    return cleaned_url, resolved_type


def validate_source_post_access(source_post_id, actor_user: User) -> GymPost:
    """
    Validates that source_post_id exists and is accessible to the story uploader.
    Prevents IDOR leaks of private, deleted, or restricted gym posts.
    """
    try:
        post_uuid = uuid.UUID(str(source_post_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid source_post_id UUID.")

    post = (
        GymPost.objects.select_related("gym", "gym__settings")
        .prefetch_related("media_attachments")
        .filter(id=post_uuid)
        .first()
    )
    if not post:
        raise ResourceNotFoundError("Source post not found.")

    gym = post.gym
    setting = getattr(gym, "settings", None) or GymSetting.objects.filter(gym=gym).first()
    if setting and setting.is_deleted:
        raise ResourceNotFoundError("Source post not found.")

    is_owner_or_staff = (
        actor_user.is_superuser
        or gym.owner_user_id == actor_user.id
        or GymStaffAssignment.objects.filter(
            gym=gym, user=actor_user, status=StaffStatus.ACTIVE
        ).exists()
    )

    if setting and not setting.is_published and not is_owner_or_staff:
        raise ResourceNotFoundError("Source post not found.")

    if setting and setting.is_deactivated and not is_owner_or_staff:
        is_member = Member.objects.filter(gym=gym).filter(
            Q(user=actor_user) | Q(email=actor_user.email)
        ).exists()
        if not is_member:
            raise PermissionDeniedError("Cannot share a post from a deactivated gym.")

    if not is_owner_or_staff and GymBlockedUser.objects.filter(gym=gym, user=actor_user).exists():
        raise PermissionDeniedError("You are blocked by this gym and cannot share its posts.")

    if not check_posts_age_restriction(gym, actor_user):
        raise PermissionDeniedError("You do not meet the age requirement to share this post.")

    if post.privacy == PostPrivacyEnum.PRIVATE and not is_owner_or_staff:
        raise PermissionDeniedError("You do not have permission to share this private post.")

    if post.privacy in (PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY) and not is_owner_or_staff:
        is_member = Member.objects.filter(gym=gym).filter(
            Q(user=actor_user) | Q(email=actor_user.email)
        ).exists()
        if not is_member:
            raise PermissionDeniedError("This source post is restricted to gym members.")

    return post


def _clean_optional_caption(caption: Optional[str]) -> Optional[str]:
    if caption is None:
        return None
    if not isinstance(caption, str) or "\x00" in caption:
        raise DomainValidationError("Invalid caption value.")
    cleaned = caption.strip()
    if len(cleaned) > 500:
        raise DomainValidationError("Story caption cannot exceed 500 characters.")
    return cleaned or None


def _clean_optional_bg_color(background_color: Optional[str]) -> Optional[str]:
    if background_color is None:
        return None
    if not isinstance(background_color, str) or "\x00" in background_color:
        raise DomainValidationError("Invalid background_color value.")
    cleaned = background_color.strip()
    if not cleaned:
        return None
    if not _HEX_COLOR_PATTERN.match(cleaned):
        raise DomainValidationError("background_color must be a valid hex color (e.g. #111827).")
    return cleaned


@transaction.atomic
def create_story(
    user: User,
    owner_type: str = StoryOwnerTypeEnum.USER,
    gym: Optional[Gym] = None,
    source_post_id=None,
    media_file: Optional[UploadedFile] = None,
    media_url: Optional[str] = None,
    media_type: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    file_size_bytes: int = 0,
    duration_seconds: Optional[float] = None,
    lifetime_hours=None,
    privacy: Optional[str] = None,
    caption: Optional[str] = None,
    background_color: Optional[str] = None,
) -> Story:
    """
    Atomically creates a Story uploaded by either a Public User or a Gym.
    Enforces single-media attachment (1 image or 1 video), lifetime selection
    (6, 12, 18 [default], 24, 48 hours), owner-specific privacy rules, and
    optional source_post_id validation.
    """
    check_story_creation_permission(user=user, owner_type=owner_type, gym=gym)

    resolved_lifetime = normalize_lifetime_hours(lifetime_hours)
    resolved_privacy = normalize_story_privacy(privacy, owner_type=owner_type)
    clean_caption = _clean_optional_caption(caption)
    clean_bg = _clean_optional_bg_color(background_color)

    if duration_seconds is not None:
        if isinstance(duration_seconds, bool) or float(duration_seconds) < 0:
            raise DomainValidationError("duration_seconds must be a non-negative number.")
        duration_seconds = float(duration_seconds)

    source_post: Optional[GymPost] = None
    if source_post_id is not None and str(source_post_id).strip() != "":
        source_post = validate_source_post_access(source_post_id, actor_user=user)

    has_file = media_file is not None
    has_url = bool(media_url and str(media_url).strip())

    if has_file and has_url:
        raise DomainValidationError(
            "Provide either a single uploaded media file or a media_url, not both."
        )

    now = timezone.now()
    expires_at = now + timedelta(hours=resolved_lifetime)

    if has_file:
        detected_type = validate_media_file(media_file)
        if media_type and media_type != detected_type:
            raise DomainValidationError(
                f"Uploaded file is a {detected_type}, which does not match media_type '{media_type}'."
            )
        f_size = int(getattr(media_file, "size", 0) or 0)
        _, public_url = MediaOptimizerService.save_uploaded_file(
            file=media_file,
            subfolder="stories/media/original",
        )
        story = Story.objects.create(
            owner_type=owner_type,
            user=user,
            gym=gym if owner_type == StoryOwnerTypeEnum.GYM else None,
            source_post=source_post,
            media_url=public_url,
            original_url=public_url,
            media_type=detected_type,
            file_size_bytes=f_size,
            size_bytes=f_size,
            duration_seconds=duration_seconds,
            caption=clean_caption,
            background_color=clean_bg,
            lifetime_hours=resolved_lifetime,
            privacy=resolved_privacy,
            published_at=now,
            expires_at=expires_at,
            processing_status=ProcessingStatus.PENDING,
        )
        try:
            from apps.stories.tasks import optimize_story_media_task
            transaction.on_commit(lambda sid=str(story.id): optimize_story_media_task.delay(sid))
        except Exception as exc:
            logger.warning(f"Could not enqueue optimization task for story {story.id}: {exc}")

    elif has_url:
        clean_url, resolved_type = _validate_media_url_and_type(media_url, media_type)
        clean_thumb = (thumbnail_url or "").strip() or None
        if clean_thumb and "\x00" in clean_thumb:
            raise DomainValidationError("Invalid thumbnail_url.")
        f_size = max(0, int(file_size_bytes or 0))

        story = Story.objects.create(
            owner_type=owner_type,
            user=user,
            gym=gym if owner_type == StoryOwnerTypeEnum.GYM else None,
            source_post=source_post,
            media_url=clean_url,
            original_url=clean_url,
            thumbnail_url=clean_thumb,
            media_type=resolved_type,
            file_size_bytes=f_size,
            size_bytes=f_size,
            duration_seconds=duration_seconds,
            caption=clean_caption,
            background_color=clean_bg,
            lifetime_hours=resolved_lifetime,
            privacy=resolved_privacy,
            published_at=now,
            expires_at=expires_at,
            processing_status=ProcessingStatus.COMPLETED,
        )

    elif source_post is not None and source_post.media_attachments.exists():
        first_media = source_post.media_attachments.order_by("order_index", "created_at").first()
        inherited_url = first_media.resolved_media_url
        inherited_thumb = first_media.resolved_thumbnail_url
        story = Story.objects.create(
            owner_type=owner_type,
            user=user,
            gym=gym if owner_type == StoryOwnerTypeEnum.GYM else None,
            source_post=source_post,
            media_url=inherited_url,
            original_url=inherited_url,
            thumbnail_url=inherited_thumb,
            media_type=first_media.media_type,
            file_size_bytes=first_media.file_size_bytes or 0,
            size_bytes=first_media.size_bytes or first_media.file_size_bytes or 0,
            width=first_media.width,
            height=first_media.height,
            duration_seconds=duration_seconds,
            caption=clean_caption,
            background_color=clean_bg,
            lifetime_hours=resolved_lifetime,
            privacy=resolved_privacy,
            published_at=now,
            expires_at=expires_at,
            processing_status=ProcessingStatus.COMPLETED,
        )

    else:
        raise DomainValidationError(
            "A single media file (image or video) or media_url is required to upload a story."
        )

    if owner_type == StoryOwnerTypeEnum.GYM and gym is not None:
        try:
            from apps.gyms.services.admin_log_services import log_admin_action
            snippet = f"“{clean_caption[:60]}”" if clean_caption else f"Published a {story.media_type} story"
            log_admin_action(
                gym=gym,
                actor=user,
                action="Published a story",
                action_type=AdminLogActionType.CUSTOM_ACTION,
                details=snippet,
                category=AdminLogCategory.POSTS,
                target_type="story",
                target_id=str(story.id),
            )
        except Exception:
            pass

    return story


@transaction.atomic
def update_story(
    story: Story,
    actor_user: User,
    caption: Optional[str] = None,
    privacy: Optional[str] = None,
    lifetime_hours=None,
    background_color: Optional[str] = None,
    is_archived: Optional[bool] = None,
    update_caption: bool = False,
    update_background_color: bool = False,
) -> Story:
    """
    Updates story metadata, privacy, lifetime, or archive status.
    """
    update_fields = ["updated_at"]

    if update_caption:
        story.caption = _clean_optional_caption(caption)
        update_fields.append("caption")

    if update_background_color:
        story.background_color = _clean_optional_bg_color(background_color)
        update_fields.append("background_color")

    if privacy is not None:
        story.privacy = normalize_story_privacy(privacy, owner_type=story.owner_type)
        update_fields.append("privacy")

    if lifetime_hours is not None:
        new_hours = normalize_lifetime_hours(lifetime_hours)
        story.lifetime_hours = new_hours
        story.expires_at = story.published_at + timedelta(hours=new_hours)
        update_fields.extend(["lifetime_hours", "expires_at"])

    if is_archived is not None:
        if not isinstance(is_archived, bool):
            raise DomainValidationError("is_archived must be a boolean.")
        story.is_archived = is_archived
        update_fields.append("is_archived")

    story.save(update_fields=update_fields)

    if story.owner_type == StoryOwnerTypeEnum.GYM and story.gym is not None:
        try:
            from apps.gyms.services.admin_log_services import log_admin_action
            log_admin_action(
                gym=story.gym,
                actor=actor_user,
                action="Updated a story",
                action_type=AdminLogActionType.CUSTOM_ACTION,
                details=f"Updated story {story.id}",
                category=AdminLogCategory.POSTS,
                target_type="story",
                target_id=str(story.id),
            )
        except Exception:
            pass

    return story


@transaction.atomic
def delete_story(story: Story, actor_user: Optional[User] = None) -> None:
    """
    Permanently deletes a story and cleans up story-owned media files from local storage.
    Never deletes media files shared from a source GymPost.
    """
    if story.owner_type == StoryOwnerTypeEnum.GYM and story.gym is not None:
        try:
            from apps.gyms.services.admin_log_services import log_admin_action
            log_admin_action(
                gym=story.gym,
                actor=actor_user,
                action="Deleted a story",
                action_type=AdminLogActionType.CUSTOM_ACTION,
                details=f"Deleted story {story.id}",
                category=AdminLogCategory.POSTS,
                target_type="story",
                target_id=str(story.id),
            )
        except Exception:
            pass

    # Only delete files stored under stories/ so source_post assets remain intact
    for url_field in {story.original_url, story.optimized_url, story.thumbnail_url, story.media_url}:
        if url_field and "/stories/" in url_field:
            p = MediaOptimizerService.get_absolute_path(url_field)
            if p and p.exists() and p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass

    story.delete()


@transaction.atomic
def record_story_view(story: Story, viewer_user: User) -> tuple[Optional[StoryView], bool]:
    """
    Idempotently records that an authenticated viewer has seen the story.
    Skips counting self-views or internal gym staff views on their own gym's story.
    """
    if not viewer_user or not getattr(viewer_user, "is_authenticated", False):
        return None, False

    if story.owner_type == StoryOwnerTypeEnum.USER and story.user_id == viewer_user.id:
        return None, False

    if story.owner_type == StoryOwnerTypeEnum.GYM and story.gym is not None:
        if has_gym_story_manage_permission(viewer_user, story.gym):
            return None, False

    view_obj, created = StoryView.objects.get_or_create(
        story=story,
        viewer_user=viewer_user,
    )
    if created:
        Story.objects.filter(id=story.id).update(views_count=F("views_count") + 1)
        story.views_count += 1

    return view_obj, created
