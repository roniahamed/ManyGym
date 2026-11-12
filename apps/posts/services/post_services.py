import logging
import uuid
from typing import Optional, List, Dict, Any
from django.db import transaction
from django.db.models import F, Q
from django.core.files.uploadedfile import UploadedFile

from apps.access_control.models import GymStaffAssignment
from apps.gyms.models import Gym, GymBlockedUser, GymFollow, GymSetting
from apps.members.models import Member
from apps.users.models import User, UserBlockedUser, UserFollow
from apps.posts.models import GymPost, GymPostMedia
from common.enums import (
    GYM_POST_PRIVACY_VALUES,
    MediaTypeEnum,
    PostOwnerTypeEnum,
    PostPrivacyEnum,
    ProcessingStatus,
    RepostTargetEnum,
    StaffStatus,
    StoryOwnerTypeEnum,
    USER_POST_PRIVACY_VALUES,
)
from common.exceptions import (
    DomainValidationError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from common.media import MediaOptimizerService
from apps.posts.services.media_services import validate_media_file

logger = logging.getLogger(__name__)


def normalize_post_privacy(privacy: Optional[str], owner_type: str) -> str:
    """
    Validates and normalizes post/repost privacy according to owner_type:
    - Public users ('user'): public, followers, private
    - Gyms ('gym'): public, followers, members_only (alias gym_members_only), private
    """
    if privacy is None or (isinstance(privacy, str) and not privacy.strip()):
        return PostPrivacyEnum.PUBLIC

    if not isinstance(privacy, str):
        raise DomainValidationError("Privacy must be a valid string.")

    cleaned = privacy.strip().lower().replace(" ", "_")

    if owner_type == PostOwnerTypeEnum.USER:
        if cleaned in (PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY):
            raise DomainValidationError(
                "Public user posts cannot use 'members_only' privacy. Allowed choices: public, followers, private."
            )
        if cleaned not in USER_POST_PRIVACY_VALUES:
            raise DomainValidationError(
                f"Invalid privacy setting '{privacy}' for public user post. Allowed choices: {list(USER_POST_PRIVACY_VALUES)}."
            )
        return cleaned

    if owner_type == PostOwnerTypeEnum.GYM:
        if cleaned not in GYM_POST_PRIVACY_VALUES:
            raise DomainValidationError(
                f"Invalid privacy setting '{privacy}' for gym post. Allowed choices: {list(GYM_POST_PRIVACY_VALUES)}."
            )
        return cleaned

    raise DomainValidationError(f"Unsupported post owner_type '{owner_type}'.")


def normalize_repost_target(target: Optional[str]) -> str:
    """
    Validates and normalizes repost destination target:
    - 'profile' (or 'profile_feed') -> 'profile'
    - 'story' -> 'story'
    """
    if target is None or (isinstance(target, str) and not target.strip()):
        return RepostTargetEnum.PROFILE

    if not isinstance(target, str):
        raise DomainValidationError("target must be a valid string ('profile' or 'story').")

    cleaned = target.strip().lower().replace(" ", "_")
    if cleaned in (RepostTargetEnum.PROFILE, "profile_feed", "feed"):
        return RepostTargetEnum.PROFILE
    if cleaned == RepostTargetEnum.STORY:
        return RepostTargetEnum.STORY

    raise DomainValidationError(
        f"Invalid repost target '{target}'. Allowed choices: ['profile', 'story']."
    )


def validate_source_post_access(source_post_id, actor_user: User) -> GymPost:
    """
    Validates that source_post_id exists and is accessible to the requesting actor_user.
    Supports both Personal User posts/reposts and Gym posts/reposts while preventing IDOR leaks.
    """
    try:
        post_uuid = uuid.UUID(str(source_post_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid source_post_id UUID.")

    post = (
        GymPost.objects.select_related(
            "gym",
            "gym__settings",
            "author_user",
            "author_user__profile",
            "author_user__settings",
            "source_post",
            "source_post__gym",
            "source_post__gym__settings",
            "source_post__author_user",
            "source_post__author_user__profile",
            "source_post__author_user__settings",
        )
        .prefetch_related("media_attachments", "source_post__media_attachments")
        .filter(id=post_uuid)
        .first()
    )
    if not post:
        raise ResourceNotFoundError("Source post not found.")

    if post.owner_type == PostOwnerTypeEnum.USER or post.gym is None:
        author = post.author_user
        is_owner = actor_user.is_superuser or actor_user.id == author.id
        author_setting = author.get_settings()
        if author_setting.is_deleted:
            raise ResourceNotFoundError("Source post not found.")
        if author_setting.is_deactivated and not is_owner:
            raise ResourceNotFoundError("Source post not found.")

        if not is_owner:
            is_blocked = UserBlockedUser.objects.filter(
                Q(blocker=author, blocked_user=actor_user)
                | Q(blocker=actor_user, blocked_user=author)
            ).exists()
            if is_blocked:
                raise PermissionDeniedError("You cannot share or repost this user's post.")

            if post.privacy == PostPrivacyEnum.PRIVATE:
                raise PermissionDeniedError("You do not have permission to share or repost this private post.")

            is_follower = UserFollow.objects.filter(follower=actor_user, followed_user=author).exists()
            if post.privacy == PostPrivacyEnum.FOLLOWERS and not is_follower:
                raise PermissionDeniedError("This source post is restricted to followers.")

            profile = getattr(author, "profile", None)
            if profile and profile.is_private and not is_follower:
                raise PermissionDeniedError("This user's account is private.")

        return post

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
            raise PermissionDeniedError("Cannot share or repost a post from a deactivated gym.")

    if not is_owner_or_staff and GymBlockedUser.objects.filter(gym=gym, user=actor_user).exists():
        raise PermissionDeniedError("You are blocked by this gym and cannot share its posts.")

    from apps.posts.selectors import check_posts_age_restriction
    if not check_posts_age_restriction(gym, actor_user):
        raise PermissionDeniedError("You do not meet the age requirement to share or repost this post.")

    if post.privacy == PostPrivacyEnum.PRIVATE and not is_owner_or_staff:
        raise PermissionDeniedError("You do not have permission to share or repost this private post.")

    if post.privacy == PostPrivacyEnum.FOLLOWERS and not is_owner_or_staff:
        is_follower = GymFollow.objects.filter(user=actor_user, gym=gym).exists()
        if not is_follower:
            raise PermissionDeniedError("This source post is restricted to gym followers.")

    if post.privacy in (PostPrivacyEnum.MEMBERS_ONLY, PostPrivacyEnum.GYM_MEMBERS_ONLY) and not is_owner_or_staff:
        is_member = Member.objects.filter(gym=gym).filter(
            Q(user=actor_user) | Q(email=actor_user.email)
        ).exists()
        if not is_member:
            raise PermissionDeniedError("This source post is restricted to gym members.")

    return post


@transaction.atomic
def create_post(
    gym: Optional[Gym] = None,
    author_user: User = None,
    content_text: Optional[str] = None,
    privacy: Optional[str] = PostPrivacyEnum.PUBLIC,
    media_files: Optional[List[UploadedFile]] = None,
    media_items: Optional[List[Dict[str, Any]]] = None,
    owner_type: Optional[str] = None,
    source_post_id=None,
) -> GymPost:
    """
    Atomically creates a new community post or profile repost for either a Public User or a Gym.
    Business Rules:
    - For standard posts: text is required unless media attachments are present.
    - For profile reposts (source_post_id provided): text and media attachments are optional.
    - Enforces owner-type-specific privacy options.
    - Media attachments are validated for format and size limits.
    - Dispatches asynchronous Celery task for image/video optimization.
    """
    if author_user is None:
        raise DomainValidationError("author_user is required.")

    if owner_type is None:
        owner_type = PostOwnerTypeEnum.GYM if gym is not None else PostOwnerTypeEnum.USER

    if owner_type == PostOwnerTypeEnum.GYM and gym is None:
        raise DomainValidationError("A gym is required when creating a gym post.")
    if owner_type == PostOwnerTypeEnum.USER and gym is not None:
        raise DomainValidationError("Personal user posts cannot be bound to a gym.")

    if content_text is not None and not isinstance(content_text, str):
        raise DomainValidationError("content_text must be a string.")
    if content_text and "\x00" in content_text:
        raise DomainValidationError("Invalid content_text value.")

    text_clean = (content_text or "").strip()
    media_files = media_files or []
    media_items = media_items or []

    source_post: Optional[GymPost] = None
    is_repost = False
    if source_post_id is not None and str(source_post_id).strip() != "":
        source_post = validate_source_post_access(source_post_id, actor_user=author_user)
        is_repost = True

    # Invariant: A standard post must contain text or media; a repost may have empty text/media
    if not is_repost and not text_clean and not media_files and not media_items:
        raise DomainValidationError("A post must contain either text or at least one media attachment.")

    resolved_privacy = normalize_post_privacy(privacy, owner_type=owner_type)

    post = GymPost.objects.create(
        owner_type=owner_type,
        gym=gym if owner_type == PostOwnerTypeEnum.GYM else None,
        author_user=author_user,
        source_post=source_post,
        is_repost=is_repost,
        content_text=text_clean or None,
        privacy=resolved_privacy,
    )

    if source_post is not None:
        GymPost.objects.filter(id=source_post.id).update(reposts_count=F("reposts_count") + 1)

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

    if owner_type == PostOwnerTypeEnum.GYM and gym is not None:
        try:
            from apps.gyms.services.admin_log_services import log_admin_action
            from common.enums import AdminLogCategory, AdminLogActionType
            action_text = "Reposted a post" if is_repost else "Published a post"
            snippet = f"“{text_clean[:60]}”" if text_clean else ("Shared a post" if is_repost else "Published a media post")
            log_admin_action(
                gym=gym,
                actor=author_user,
                action=action_text,
                action_type=AdminLogActionType.PUBLISH_POST,
                details=snippet,
                category=AdminLogCategory.POSTS,
                target_type="post",
                target_id=str(post.id),
            )
        except Exception:
            pass

    return post


@transaction.atomic
def repost_post(
    actor_user: User,
    source_post_id,
    target: str = RepostTargetEnum.PROFILE,
    owner_type: str = PostOwnerTypeEnum.USER,
    gym: Optional[Gym] = None,
    privacy: Optional[str] = None,
    content_text: Optional[str] = None,
    caption: Optional[str] = None,
    background_color: Optional[str] = None,
    lifetime_hours=None,
    media_file: Optional[UploadedFile] = None,
    media_url: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    file_size_bytes: int = 0,
    duration_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Reposts/shares an existing post (another user's/gym's post or actor's own previous post)
    to either:
    - 'profile': creates a repost on the actor's profile feed (Personal User or Gym).
    - 'story': shares the post onto the actor's Story (delegating to apps.stories.services.create_story).
    """
    resolved_target = normalize_repost_target(target)

    if resolved_target == RepostTargetEnum.PROFILE:
        created_post = create_post(
            gym=gym if owner_type == PostOwnerTypeEnum.GYM else None,
            author_user=actor_user,
            owner_type=owner_type,
            content_text=content_text,
            privacy=privacy,
            source_post_id=source_post_id,
        )
        return {
            "target": RepostTargetEnum.PROFILE,
            "post": created_post,
            "story": None,
        }

    # Share on Story
    from apps.stories.services import create_story

    story_owner_type = StoryOwnerTypeEnum.GYM if owner_type == PostOwnerTypeEnum.GYM else StoryOwnerTypeEnum.USER
    resolved_caption = caption if caption is not None else content_text

    created_story = create_story(
        user=actor_user,
        owner_type=story_owner_type,
        gym=gym if story_owner_type == StoryOwnerTypeEnum.GYM else None,
        source_post_id=source_post_id,
        media_file=media_file,
        media_url=media_url,
        thumbnail_url=thumbnail_url,
        file_size_bytes=file_size_bytes,
        duration_seconds=duration_seconds,
        lifetime_hours=lifetime_hours,
        privacy=privacy,
        caption=resolved_caption,
        background_color=background_color,
    )
    return {
        "target": RepostTargetEnum.STORY,
        "post": None,
        "story": created_story,
    }


@transaction.atomic
def update_post(
    post: GymPost,
    content_text: Optional[str] = None,
    privacy: Optional[str] = None,
    media_order: Optional[List[Dict[str, Any]]] = None,
) -> GymPost:
    """
    Updates post text, privacy (enforcing owner_type constraints), or re-arranges media attachment display order.
    """
    update_fields = ["updated_at"]

    if content_text is not None:
        if not isinstance(content_text, str):
            raise DomainValidationError("content_text must be a string.")
        if "\x00" in content_text:
            raise DomainValidationError("Invalid content_text value.")
        text_clean = content_text.strip()
        # Invariant: cannot remove text if there are no media attachments (unless it's a repost)
        if not text_clean and not post.is_repost and not post.media_attachments.exists():
            raise DomainValidationError("A post cannot be left empty without text or media attachments.")
        post.content_text = text_clean or None
        update_fields.append("content_text")

    if privacy is not None:
        post.privacy = normalize_post_privacy(privacy, owner_type=post.owner_type)
        update_fields.append("privacy")

    post.save(update_fields=update_fields)

    # Re-order media attachments if requested
    if media_order is not None:
        for order_entry in media_order:
            media_id = order_entry.get("media_id") or order_entry.get("id")
            new_idx = order_entry.get("order_index")
            if media_id and new_idx is not None:
                post.media_attachments.filter(id=media_id).update(order_index=int(new_idx))

    if post.owner_type == PostOwnerTypeEnum.GYM and post.gym is not None:
        try:
            from apps.gyms.services.admin_log_services import log_admin_action
            from common.enums import AdminLogCategory, AdminLogActionType
            snippet = f"“{(post.content_text or '')[:60]}”" if post.content_text else "Updated post details"
            log_admin_action(
                gym=post.gym,
                action="Updated a post",
                action_type=AdminLogActionType.UPDATE_POST,
                details=snippet,
                category=AdminLogCategory.POSTS,
                target_type="post",
                target_id=str(post.id),
            )
        except Exception:
            pass

    return post


@transaction.atomic
def delete_post(post: GymPost) -> None:
    """
    Deletes post entity, updates source_post.reposts_count if repost, and cleans up associated attachments.
    """
    if post.owner_type == PostOwnerTypeEnum.GYM and post.gym is not None:
        try:
            from apps.gyms.services.admin_log_services import log_admin_action
            from common.enums import AdminLogCategory, AdminLogActionType
            snippet = f"“{(post.content_text or '')[:60]}”" if post.content_text else f"Deleted post {post.id}"
            log_admin_action(
                gym=post.gym,
                action="Deleted a post",
                action_type=AdminLogActionType.DELETE_POST,
                details=snippet,
                category=AdminLogCategory.POSTS,
                target_type="post",
                target_id=str(post.id),
            )
        except Exception:
            pass

    if post.source_post_id:
        GymPost.objects.filter(id=post.source_post_id, reposts_count__gt=0).update(
            reposts_count=F("reposts_count") - 1
        )

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
