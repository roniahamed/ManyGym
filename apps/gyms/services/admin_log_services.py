import logging
from typing import Optional, Dict, Any
from django.db import transaction
from apps.gyms.models import Gym, GymAdminLog
from apps.users.models import User
from common.enums import AdminLogCategory, AdminLogActionType

logger = logging.getLogger(__name__)


@transaction.atomic
def log_admin_action(
    gym: Gym,
    actor: Optional[User] = None,
    action: str = "Custom Action",
    action_type: str = AdminLogActionType.CUSTOM_ACTION,
    details: str = "",
    category: str = AdminLogCategory.GENERAL,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    raise_on_error: bool = False,
) -> Optional[GymAdminLog]:
    """
    Records an administrative action audit entry within a gym workspace.

    Args:
        gym: The gym workspace where the action was executed.
        actor: The administrator or staff user who performed the action.
        action: Human-readable action label (e.g. "Updated page information", "Published a post").
        action_type: Normalized machine code from AdminLogActionType.
        details: Specific details or diff of what changed (e.g. "Changed the page description").
        category: High-level module category from AdminLogCategory.
        target_type: Entity type affected (e.g. "post", "member", "plan", "gym").
        target_id: Stringified identifier of the affected entity.
        metadata: Structured dictionary with extra context or before/after diff.
        ip_address: Optional client IP address.
        user_agent: Optional client user agent string.
        raise_on_error: If True, raises exceptions; if False, logs warnings gracefully.

    Returns:
        The created GymAdminLog instance, or None if an error occurred and raise_on_error is False.
    """
    try:
        actor_name = ""
        actor_email = ""
        if actor is not None:
            first = getattr(actor, "first_name", "") or ""
            last = getattr(actor, "last_name", "") or ""
            full_name = f"{first} {last}".strip()
            actor_name = full_name or getattr(actor, "email", "")
            actor_email = getattr(actor, "email", "")

        cleaned_target_id = str(target_id) if target_id is not None else None
        cleaned_action = str(action or "Admin Action").strip()[:255]
        cleaned_action_type = str(action_type or AdminLogActionType.CUSTOM_ACTION).strip()[:100]
        cleaned_category = str(category or AdminLogCategory.GENERAL).strip()[:50]
        cleaned_details = str(details or "").strip()

        # Enforce valid choice values with graceful fallbacks
        if cleaned_category not in AdminLogCategory.values:
            cleaned_category = AdminLogCategory.GENERAL

        log_entry = GymAdminLog.objects.create(
            gym=gym,
            actor=actor,
            actor_name=actor_name,
            actor_email=actor_email,
            action=cleaned_action,
            action_type=cleaned_action_type,
            category=cleaned_category,
            details=cleaned_details,
            target_type=target_type[:100] if target_type else None,
            target_id=cleaned_target_id[:100] if cleaned_target_id else None,
            metadata=metadata if isinstance(metadata, dict) else {},
            ip_address=ip_address,
            user_agent=user_agent[:500] if user_agent else None,
        )
        logger.info(
            "Logged admin action for gym '%s' [%s]: %s - %s",
            gym.name,
            gym.id,
            log_entry.action,
            log_entry.details,
        )
        return log_entry
    except Exception as exc:
        logger.warning(
            "Failed to record admin log for gym '%s': %s",
            getattr(gym, "id", None),
            str(exc),
            exc_info=True,
        )
        if raise_on_error:
            raise exc
        return None

