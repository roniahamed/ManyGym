import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest

from apps.gyms.models import Gym
from apps.posts.comment_selectors import get_comment_detail
from apps.posts.models import GymPost, PostComment
from apps.posts.selectors import get_post_detail_by_id
from apps.reactions.models import Reaction, ReactionItem
from apps.reactions.permissions import check_reaction_actor_permission
from apps.reactions.selectors import get_reaction_item_by_code, get_reaction_item_by_id
from apps.stories.models import Story
from apps.stories.selectors import get_story_detail
from apps.users.models import User
from common.enums import PostOwnerTypeEnum
from common.exceptions import DomainValidationError, PermissionDeniedError, ResourceNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_REACTION_ITEMS = [
    {"code": "smile", "emoji": "😊", "label": "Smile", "order": 1},
    {"code": "laugh", "emoji": "😆", "label": "Laugh", "order": 2},
    {"code": "like", "emoji": "👍", "label": "Like", "order": 3},
    {"code": "love", "emoji": "❤️", "label": "Love", "order": 4},
    {"code": "fire", "emoji": "🔥", "label": "Fire", "order": 5},
    {"code": "muscle", "emoji": "💪", "label": "Strong", "order": 6},
    {"code": "care", "emoji": "🥰", "label": "Care", "order": 7},
    {"code": "clap", "emoji": "👏", "label": "Clap", "order": 8},
    {"code": "wow", "emoji": "😮", "label": "Wow", "order": 9},
    {"code": "sad", "emoji": "😢", "label": "Sad", "order": 10},
    {"code": "thinking", "emoji": "🤔", "label": "Thinking", "order": 11},
    {"code": "hundred", "emoji": "💯", "label": "100", "order": 12},
    {"code": "party", "emoji": "🎉", "label": "Celebrate", "order": 13},
]


@transaction.atomic
def seed_default_reaction_items() -> List[ReactionItem]:
    """
    Seeds the default reaction item catalog (10+ emoji reactions including 😊 and 😆).
    Idempotent execution.
    """
    items = []
    for spec in DEFAULT_REACTION_ITEMS:
        item, _ = ReactionItem.objects.update_or_create(
            code=spec["code"],
            defaults={
                "emoji": spec["emoji"],
                "label": spec["label"],
                "order": spec["order"],
                "is_active": True,
            },
        )
        items.append(item)
    return items


def validate_reaction_target(
    actor_user: User,
    post_id: Optional[uuid.UUID] = None,
    story_id: Optional[uuid.UUID] = None,
    comment_id: Optional[uuid.UUID] = None,
) -> Tuple[str, Any]:
    """
    Validates that exactly one target is provided and that the actor has permission
    to view/access that target according to domain privacy and blocklist rules.
    Returns (target_type, target_instance).
    """
    targets = [("post", post_id), ("story", story_id), ("comment", comment_id)]
    provided = [(name, val) for name, val in targets if val is not None]
    if len(provided) != 1:
        raise DomainValidationError("Exactly one target (post_id, story_id, or comment_id) must be specified.")

    target_type, raw_id = provided[0]
    try:
        target_uuid = uuid.UUID(str(raw_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError(f"Invalid {target_type}_id.")

    if target_type == "post":
        post = get_post_detail_by_id(post_id=target_uuid, requesting_user=actor_user)
        return "post", post

    if target_type == "story":
        story = get_story_detail(story_id=target_uuid, requesting_user=actor_user)
        return "story", story

    if target_type == "comment":
        comment = get_comment_detail(comment_id=target_uuid, requesting_user=actor_user)
        return "comment", comment

    raise DomainValidationError("Unsupported reaction target.")


def _update_target_reactions_count(target_obj: Any, delta: int) -> None:
    """Updates denormalized reactions_count on the target model atomically."""
    model_cls = target_obj.__class__
    if delta > 0:
        model_cls.objects.filter(id=target_obj.id).update(
            reactions_count=F("reactions_count") + delta
        )
    elif delta < 0:
        model_cls.objects.filter(id=target_obj.id).update(
            reactions_count=Greatest(F("reactions_count") + delta, 0)
        )
    # Refresh local instance counter
    target_obj.refresh_from_db(fields=["reactions_count"])


@transaction.atomic
def toggle_or_set_reaction(
    actor_user: User,
    reaction_item_id: Optional[uuid.UUID] = None,
    reaction_code: Optional[str] = None,
    post_id: Optional[uuid.UUID] = None,
    story_id: Optional[uuid.UUID] = None,
    comment_id: Optional[uuid.UUID] = None,
    owner_type: str = PostOwnerTypeEnum.USER,
    gym: Optional[Gym] = None,
) -> Tuple[Optional[Reaction], str, Any]:
    """
    Atomically creates, updates, or toggles off a reaction on a target.
    - If no reaction exists: creates reaction, increments reactions_count, returns (reaction, 'created', target).
    - If reaction exists with the same emoji: removes reaction, decrements reactions_count, returns (None, 'removed', target).
    - If reaction exists with a different emoji: updates reaction item, reactions_count unchanged, returns (reaction, 'updated', target).
    """
    # 1. Authorize actor
    check_reaction_actor_permission(actor_user=actor_user, gym=gym)

    if owner_type == PostOwnerTypeEnum.GYM and gym is None:
        raise DomainValidationError("A gym must be provided when reacting as a gym.")
    if owner_type == PostOwnerTypeEnum.USER and gym is not None:
        raise DomainValidationError("Personal user reactions cannot be bound to a gym.")

    # 2. Resolve ReactionItem
    reaction_item: Optional[ReactionItem] = None
    if reaction_item_id is not None:
        reaction_item = get_reaction_item_by_id(reaction_item_id)
    elif reaction_code:
        reaction_item = get_reaction_item_by_code(reaction_code)
        if not reaction_item:
            raise ResourceNotFoundError(f"Reaction item with code '{reaction_code}' not found.")
    else:
        raise DomainValidationError("Either 'reaction_item_id' or 'reaction_code' is required.")

    # 3. Validate Target & Access Permissions
    target_type, target_obj = validate_reaction_target(
        actor_user=actor_user,
        post_id=post_id,
        story_id=story_id,
        comment_id=comment_id,
    )

    # 4. Check for existing reaction with row lock
    target_kwarg = {f"{target_type}_id": target_obj.id}
    existing_qs = Reaction.objects.select_for_update().filter(**target_kwarg)

    if owner_type == PostOwnerTypeEnum.GYM:
        existing = existing_qs.filter(owner_type=PostOwnerTypeEnum.GYM, gym=gym).first()
    else:
        existing = existing_qs.filter(owner_type=PostOwnerTypeEnum.USER, user=actor_user).first()

    if existing:
        if existing.reaction_item_id == reaction_item.id:
            # Same emoji clicked -> Toggle off (remove)
            existing.delete()
            _update_target_reactions_count(target_obj, delta=-1)
            return None, "removed", target_obj

        # Different emoji clicked -> Switch reaction
        existing.reaction_item = reaction_item
        existing.save(update_fields=["reaction_item", "updated_at"])
        return existing, "updated", target_obj

    # New reaction
    new_reaction = Reaction(
        user=actor_user,
        owner_type=owner_type,
        gym=gym,
        reaction_item=reaction_item,
        **{target_type: target_obj},
    )
    new_reaction.save()
    _update_target_reactions_count(target_obj, delta=+1)
    return new_reaction, "created", target_obj


@transaction.atomic
def remove_reaction(
    actor_user: User,
    post_id: Optional[uuid.UUID] = None,
    story_id: Optional[uuid.UUID] = None,
    comment_id: Optional[uuid.UUID] = None,
    reaction_id: Optional[uuid.UUID] = None,
    owner_type: str = PostOwnerTypeEnum.USER,
    gym: Optional[Gym] = None,
) -> Tuple[bool, Any]:
    """
    Explicitly removes a reaction from a target or by reaction ID.
    Atomically decrements the target's reactions_count.
    Returns (success: bool, target_obj: Any).
    """
    check_reaction_actor_permission(actor_user=actor_user, gym=gym)

    if reaction_id is not None:
        try:
            r_uuid = uuid.UUID(str(reaction_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid reaction ID.")
        reaction = Reaction.objects.select_for_update().filter(id=r_uuid).first()
        if not reaction:
            raise ResourceNotFoundError("Reaction not found.")

        # Verify ownership
        if not actor_user.is_superuser:
            if reaction.owner_type == PostOwnerTypeEnum.GYM:
                check_reaction_actor_permission(actor_user=actor_user, gym=reaction.gym)
            elif reaction.user_id != actor_user.id:
                raise PermissionDeniedError("You do not have permission to delete this reaction.")

        target_obj = reaction.post or reaction.story or reaction.comment
        reaction.delete()
        if target_obj:
            _update_target_reactions_count(target_obj, delta=-1)
        return True, target_obj

    # Remove by target coordinates
    target_type, target_obj = validate_reaction_target(
        actor_user=actor_user,
        post_id=post_id,
        story_id=story_id,
        comment_id=comment_id,
    )

    target_kwarg = {f"{target_type}_id": target_obj.id}
    existing_qs = Reaction.objects.select_for_update().filter(**target_kwarg)

    if owner_type == PostOwnerTypeEnum.GYM:
        reaction = existing_qs.filter(owner_type=PostOwnerTypeEnum.GYM, gym=gym).first()
    else:
        reaction = existing_qs.filter(owner_type=PostOwnerTypeEnum.USER, user=actor_user).first()

    if not reaction:
        return False, target_obj

    reaction.delete()
    _update_target_reactions_count(target_obj, delta=-1)
    return True, target_obj

