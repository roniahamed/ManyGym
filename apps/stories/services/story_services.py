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

from apps.gyms.models import Gym
from apps.posts.models import GymPost
from apps.posts.services.post_services import validate_source_post_access
from apps.stories.models import Story, StoryView, StoryReply
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
    ProcessingStatus,
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

    elif source_post is not None:
        inherited_media = None
        if source_post.media_attachments.exists():
            inherited_media = source_post.media_attachments.order_by("order_index", "created_at").first()
        elif source_post.is_repost and source_post.source_post_id:
            try:
                root_post = validate_source_post_access(source_post.source_post_id, actor_user=user)
                if root_post.media_attachments.exists():
                    inherited_media = root_post.media_attachments.order_by("order_index", "created_at").first()
            except (PermissionDeniedError, ResourceNotFoundError):
                inherited_media = None

        if inherited_media is None:
            raise DomainValidationError(
                "A single media file (image or video) or media_url is required to upload a story."
            )

        inherited_url = inherited_media.resolved_media_url
        inherited_thumb = inherited_media.resolved_thumbnail_url
        story = Story.objects.create(
            owner_type=owner_type,
            user=user,
            gym=gym if owner_type == StoryOwnerTypeEnum.GYM else None,
            source_post=source_post,
            media_url=inherited_url,
            original_url=inherited_url,
            thumbnail_url=inherited_thumb,
            media_type=inherited_media.media_type,
            file_size_bytes=inherited_media.file_size_bytes or 0,
            size_bytes=inherited_media.size_bytes or inherited_media.file_size_bytes or 0,
            width=inherited_media.width,
            height=inherited_media.height,
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


@transaction.atomic
def create_story_reply(
    story: Story,
    user: User,
    message: str,
    owner_type: str = StoryOwnerTypeEnum.USER,
    gym: Optional[Gym] = None,
    media_url: Optional[str] = None,
) -> StoryReply:
    """
    Creates a reply / comment message on an active, non-expired moment/story.
    Validates permissions, sanitizes message content, increments story replies counter,
    links direct message conversation if applicable, and sends in-app notifications.
    """
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionDeniedError("Authentication is required to reply to a moment.")

    if story.is_expired:
        raise DomainValidationError("Cannot reply to an expired moment.")

    if getattr(story, "is_archived", False):
        raise DomainValidationError("Cannot reply to an archived moment.")

    cleaned_msg = (message or "").strip()
    if not cleaned_msg:
        raise DomainValidationError("Reply message cannot be empty.")
    if len(cleaned_msg) > 1000:
        raise DomainValidationError("Reply message cannot exceed 1000 characters.")

    # Validate viewer access to story
    from apps.stories.selectors.story_selectors import get_story_detail
    get_story_detail(story.id, requesting_user=user, for_management=False)

    # Resolve linked conversation and dispatch chat message if messaging module is active
    conversation_id = None
    try:
        import base64
        import json
        from apps.messaging.models import (
            ConversationParticipant,
            EncryptedMessage,
            MessageDeliveryStatusEnum,
            MessageSenderTypeEnum,
        )
        from apps.messaging.services.conversation_services import (
            get_or_create_user_to_user_conversation,
            get_or_create_user_to_gym_conversation,
        )
        from apps.messaging.services.device_key_services import broadcast_realtime_event

        conv = None
        if story.owner_type == StoryOwnerTypeEnum.USER and story.user_id != user.id:
            conv = get_or_create_user_to_user_conversation(user, story.user)
            conversation_id = conv.id
        elif story.owner_type == StoryOwnerTypeEnum.GYM and story.gym_id:
            conv = get_or_create_user_to_gym_conversation(user, story.gym)
            conversation_id = conv.id

        if conv:
            msg_payload = {
                "type": "moment_reply",
                "story_id": str(story.id),
                "moment_id": str(story.id),
                "media_url": story.media_url,
                "thumbnail_url": story.thumbnail_url or story.media_url,
                "caption": story.caption or "",
                "message": cleaned_msg,
            }
            encoded_body = base64.b64encode(json.dumps(msg_payload).encode("utf-8")).decode("utf-8")

            sender_type_val = MessageSenderTypeEnum.GYM if owner_type == StoryOwnerTypeEnum.GYM else MessageSenderTypeEnum.USER
            msg = EncryptedMessage.objects.create(
                conversation=conv,
                sender_type=sender_type_val,
                sender_user=user,
                sender_gym=gym if owner_type == StoryOwnerTypeEnum.GYM else None,
                ciphertext=encoded_body,
                nonce="moment_reply",
                delivery_status=MessageDeliveryStatusEnum.SENT,
                sent_at=timezone.now(),
            )

            preview_text = f"Replied to moment: {cleaned_msg[:40]}"
            conv.last_message_at = msg.sent_at
            conv.last_message_preview = preview_text
            conv.save(update_fields=["last_message_at", "last_message_preview", "updated_at"])

            other_qs = ConversationParticipant.objects.filter(conversation=conv)
            if sender_type_val == MessageSenderTypeEnum.USER:
                other_qs = other_qs.exclude(user=user)
            elif sender_type_val == MessageSenderTypeEnum.GYM:
                other_qs = other_qs.exclude(gym=gym)

            other_targets = list(other_qs.values_list("user_id", "gym_id"))
            other_qs.update(unread_count=F("unread_count") + 1, updated_at=timezone.now())

            try:
                ws_payload = {
                    "id": str(msg.id),
                    "conversation_id": str(conv.id),
                    "sender_type": msg.sender_type,
                    "sender_user_id": str(user.id),
                    "sender_gym_id": str(gym.id) if gym else None,
                    "ciphertext": msg.ciphertext,
                    "nonce": msg.nonce,
                    "sent_at": msg.sent_at.isoformat(),
                    "story_id": str(story.id),
                    "message": cleaned_msg,
                }
                broadcast_realtime_event(f"chat_conversation_{conv.id}", "chat_message", ws_payload)
                for u_id, g_id in other_targets:
                    if u_id:
                        broadcast_realtime_event(f"chat_user_{u_id}", "chat_incoming", ws_payload)
                    elif g_id:
                        broadcast_realtime_event(f"chat_gym_{g_id}", "chat_incoming", ws_payload)
            except Exception:
                pass
    except Exception:
        pass

    clean_media = (media_url or "").strip()

    reply = StoryReply.objects.create(
        story=story,
        user=user,
        owner_type=owner_type,
        gym=gym if owner_type == StoryOwnerTypeEnum.GYM else None,
        message=cleaned_msg,
        media_url=clean_media,
        conversation_id=conversation_id,
    )

    Story.objects.filter(id=story.id).update(replies_count=F("replies_count") + 1)
    story.replies_count += 1

    # In-App & FCM Push Notification
    try:
        from apps.notifications.services.notification_services import send_notification
        from common.enums import NotificationTypeEnum

        recipient = story.user
        actor_name = f"{user.first_name} {user.last_name}".strip() or user.email
        send_notification(
            recipient=recipient,
            notification_type=NotificationTypeEnum.COMMENT,
            title=f"{actor_name} replied to your moment",
            body=cleaned_msg[:150],
            actor=user,
            actor_gym=gym if owner_type == StoryOwnerTypeEnum.GYM else None,
            gym=story.gym if story.owner_type == StoryOwnerTypeEnum.GYM else None,
            target_type="moment",
            target_id=str(story.id),
            action_url=f"/api/v1/moments/{story.id}/",
            data={
                "story_id": str(story.id),
                "moment_id": str(story.id),
                "reply_id": str(reply.id),
                "conversation_id": str(conversation_id) if conversation_id else None,
            },
            send_push=True,
        )
    except Exception:
        pass

    return reply


@transaction.atomic
def delete_story_reply(reply: StoryReply, actor_user: User) -> None:
    """
    Deletes a story reply.
    Allowed by the reply author, or the story owner / managing gym staff.
    Atomically decrements the story's replies_count.
    """
    if not actor_user or not getattr(actor_user, "is_authenticated", False):
        raise PermissionDeniedError("Authentication is required to delete a reply.")

    is_author = reply.user_id == actor_user.id
    is_story_owner = reply.story.user_id == actor_user.id
    is_gym_manager = False
    if reply.story.owner_type == StoryOwnerTypeEnum.GYM and reply.story.gym_id:
        is_gym_manager = has_gym_story_manage_permission(actor_user, reply.story.gym)

    if not (is_author or is_story_owner or is_gym_manager or actor_user.is_superuser):
        raise PermissionDeniedError("You do not have permission to delete this reply.")

    story_id = reply.story_id
    reply.delete()
    Story.objects.filter(id=story_id, replies_count__gt=0).update(replies_count=F("replies_count") - 1)


# Semantic Aliases
create_moment_reply = create_story_reply
delete_moment_reply = delete_story_reply

