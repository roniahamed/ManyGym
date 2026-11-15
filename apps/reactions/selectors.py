import uuid
from typing import Any, Dict, List, Optional
from django.db.models import Count, Q, QuerySet

from apps.gyms.models import Gym
from apps.reactions.models import Reaction, ReactionItem
from apps.users.models import User
from common.enums import PostOwnerTypeEnum
from common.exceptions import DomainValidationError, ResourceNotFoundError


def list_reaction_items(active_only: bool = True) -> QuerySet[ReactionItem]:
    """Retrieves all reaction items ordered by configured order and creation date."""
    qs = ReactionItem.objects.all()
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.order_by("order", "created_at")


def get_reaction_item_by_id(reaction_item_id: Any) -> ReactionItem:
    """Retrieves a single ReactionItem by UUID, or raises ResourceNotFoundError."""
    try:
        item_uuid = uuid.UUID(str(reaction_item_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid reaction item ID.")

    item = ReactionItem.objects.filter(id=item_uuid, is_active=True).first()
    if not item:
        raise ResourceNotFoundError("Reaction item not found or is inactive.")
    return item


def get_reaction_item_by_code(code: str) -> Optional[ReactionItem]:
    """Retrieves an active reaction item by its code (e.g. 'smile', 'laugh', 'fire')."""
    if not code or not isinstance(code, str):
        return None
    return ReactionItem.objects.filter(code=code.strip().lower(), is_active=True).first()


def get_reaction_by_id(reaction_id: Any) -> Reaction:
    """Retrieves a single Reaction by UUID with related entities loaded."""
    try:
        r_uuid = uuid.UUID(str(reaction_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid reaction ID.")

    reaction = (
        Reaction.objects.select_related("user", "user__profile", "gym", "reaction_item")
        .filter(id=r_uuid)
        .first()
    )
    if not reaction:
        raise ResourceNotFoundError("Reaction not found.")
    return reaction


def _build_target_filter(
    post_id: Optional[uuid.UUID] = None,
    story_id: Optional[uuid.UUID] = None,
    comment_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Validates and constructs query kwargs for exactly one target."""
    targets = [("post_id", post_id), ("story_id", story_id), ("comment_id", comment_id)]
    provided = [(name, val) for name, val in targets if val is not None]
    if len(provided) != 1:
        raise DomainValidationError("Exactly one target (post_id, story_id, or comment_id) must be specified.")
    name, val = provided[0]
    try:
        target_uuid = uuid.UUID(str(val))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError(f"Invalid {name}.")
    return {name: target_uuid}


def get_user_reaction_for_target(
    user: Optional[User] = None,
    gym: Optional[Gym] = None,
    owner_type: str = PostOwnerTypeEnum.USER,
    post_id: Optional[uuid.UUID] = None,
    story_id: Optional[uuid.UUID] = None,
    comment_id: Optional[uuid.UUID] = None,
) -> Optional[Reaction]:
    """Finds the current user or gym reaction for the given target."""
    if not user or not getattr(user, "is_authenticated", False):
        return None

    target_filter = _build_target_filter(post_id=post_id, story_id=story_id, comment_id=comment_id)
    qs = Reaction.objects.select_related("reaction_item").filter(**target_filter)

    if owner_type == PostOwnerTypeEnum.GYM and gym is not None:
        return qs.filter(owner_type=PostOwnerTypeEnum.GYM, gym=gym).first()
    return qs.filter(owner_type=PostOwnerTypeEnum.USER, user=user).first()


def get_target_reaction_summary(
    post_id: Optional[uuid.UUID] = None,
    story_id: Optional[uuid.UUID] = None,
    comment_id: Optional[uuid.UUID] = None,
    requesting_user: Optional[User] = None,
    owner_type: str = PostOwnerTypeEnum.USER,
    gym: Optional[Gym] = None,
) -> Dict[str, Any]:
    """
    Computes aggregated reaction metrics for a target with O(1) database queries:
    - total_reactions: Count of all reactions
    - reaction_counts: Breakdown grouped by reaction item
    - top_reactions: Top 3 emojis by reaction frequency
    - viewer_reaction: Viewer's active reaction on this target (if authenticated)
    """
    target_filter = _build_target_filter(post_id=post_id, story_id=story_id, comment_id=comment_id)
    base_qs = Reaction.objects.filter(**target_filter)

    total_reactions = base_qs.count()

    # Aggregate reaction counts grouped by item
    counts_raw = (
        base_qs.values(
            "reaction_item__id",
            "reaction_item__code",
            "reaction_item__emoji",
            "reaction_item__label",
            "reaction_item__order",
        )
        .annotate(count=Count("id"))
        .order_by("-count", "reaction_item__order")
    )

    reaction_counts: List[Dict[str, Any]] = []
    top_reactions: List[Dict[str, Any]] = []

    for idx, row in enumerate(counts_raw):
        item_data = {
            "reaction_item_id": str(row["reaction_item__id"]),
            "code": row["reaction_item__code"],
            "emoji": row["reaction_item__emoji"],
            "label": row["reaction_item__label"],
            "count": row["count"],
        }
        reaction_counts.append(item_data)
        if idx < 3:
            top_reactions.append({
                "code": row["reaction_item__code"],
                "emoji": row["reaction_item__emoji"],
                "count": row["count"],
            })

    # Determine viewer's reaction
    viewer_reaction_data: Optional[Dict[str, Any]] = None
    if requesting_user and getattr(requesting_user, "is_authenticated", False):
        user_reaction = get_user_reaction_for_target(
            user=requesting_user,
            gym=gym,
            owner_type=owner_type,
            post_id=post_id,
            story_id=story_id,
            comment_id=comment_id,
        )
        if user_reaction:
            viewer_reaction_data = {
                "id": str(user_reaction.id),
                "reaction_item_id": str(user_reaction.reaction_item_id),
                "code": user_reaction.reaction_item.code,
                "emoji": user_reaction.reaction_item.emoji,
                "label": user_reaction.reaction_item.label,
                "owner_type": user_reaction.owner_type,
                "gym_id": str(user_reaction.gym_id) if user_reaction.gym_id else None,
                "created_at": user_reaction.created_at.isoformat(),
            }

    return {
        "total_reactions": total_reactions,
        "reaction_counts": reaction_counts,
        "top_reactions": top_reactions,
        "viewer_reaction": viewer_reaction_data,
    }


def list_reactions_for_target(
    post_id: Optional[uuid.UUID] = None,
    story_id: Optional[uuid.UUID] = None,
    comment_id: Optional[uuid.UUID] = None,
    reaction_item_id: Optional[uuid.UUID] = None,
    reaction_code: Optional[str] = None,
    requesting_user: Optional[User] = None,
) -> QuerySet[Reaction]:
    """
    Returns an optimized QuerySet of reactors for a given target,
    supporting optional filtering by reaction_item_id or reaction code.
    """
    target_filter = _build_target_filter(post_id=post_id, story_id=story_id, comment_id=comment_id)
    qs = (
        Reaction.objects.select_related("user", "user__profile", "gym", "reaction_item")
        .filter(**target_filter)
    )

    if reaction_item_id is not None:
        try:
            item_uuid = uuid.UUID(str(reaction_item_id))
            qs = qs.filter(reaction_item_id=item_uuid)
        except (ValueError, TypeError):
            raise DomainValidationError("Invalid reaction_item_id.")

    if reaction_code:
        qs = qs.filter(reaction_item__code=reaction_code.strip().lower())

    return qs.order_by("-created_at")

