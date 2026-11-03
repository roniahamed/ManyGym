import uuid
from typing import Optional, Dict, Any, Tuple, List
from django.db.models import Q, Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from apps.gyms.models import Gym, GymAdminLog
from common.exceptions import ResourceNotFoundError, DomainValidationError


def list_admin_logs(
    gym: Gym,
    category: Optional[str] = None,
    action_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[GymAdminLog], int, int]:
    """
    Retrieves an optimized, paginated list of administration audit logs for a gym.

    Returns:
        (logs_list, total_count, total_pages)
    """
    qs = (
        GymAdminLog.objects.filter(gym=gym)
        .select_related("actor", "actor__profile")
        .order_by("-created_at")
    )

    if category:
        qs = qs.filter(category=category.strip())

    if action_type:
        qs = qs.filter(action_type=action_type.strip())

    if actor_id:
        try:
            uuid.UUID(str(actor_id))
            qs = qs.filter(actor_id=actor_id)
        except (ValueError, TypeError):
            raise DomainValidationError("Invalid actor_id UUID.")

    if start_date:
        parsed_start = parse_datetime(start_date) or parse_date(start_date)
        if parsed_start:
            if not hasattr(parsed_start, "hour"):
                parsed_start = timezone.datetime.combine(
                    parsed_start,
                    timezone.datetime.min.time(),
                    tzinfo=timezone.get_current_timezone(),
                )
            qs = qs.filter(created_at__gte=parsed_start)

    if end_date:
        parsed_end = parse_datetime(end_date) or parse_date(end_date)
        if parsed_end:
            if not hasattr(parsed_end, "hour"):
                parsed_end = timezone.datetime.combine(
                    parsed_end,
                    timezone.datetime.max.time(),
                    tzinfo=timezone.get_current_timezone(),
                )
            qs = qs.filter(created_at__lte=parsed_end)

    if search:
        search_term = search.strip()
        qs = qs.filter(
            Q(action__icontains=search_term)
            | Q(details__icontains=search_term)
            | Q(actor_name__icontains=search_term)
            | Q(actor_email__icontains=search_term)
        )

    total_count = qs.count()

    safe_page_size = max(1, min(page_size, 100))
    safe_page = max(1, page)
    offset = (safe_page - 1) * safe_page_size
    total_pages = (total_count + safe_page_size - 1) // safe_page_size if total_count > 0 else 1

    logs = list(qs[offset : offset + safe_page_size])
    return logs, total_count, total_pages


def get_admin_log_by_id(gym: Gym, log_id: str) -> GymAdminLog:
    """
    Retrieves a single administration log record for the specified gym.
    """
    try:
        uuid.UUID(str(log_id))
    except (ValueError, TypeError):
        raise DomainValidationError("Invalid log_id UUID.")

    try:
        return (
            GymAdminLog.objects.select_related("actor", "actor__profile")
            .get(gym=gym, id=log_id)
        )
    except GymAdminLog.DoesNotExist:
        raise ResourceNotFoundError("Admin log entry not found.")


def get_admin_logs_metrics(gym: Gym) -> Dict[str, Any]:
    """
    Calculates summary metrics for gym administration activity.
    """
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    total_logs = GymAdminLog.objects.filter(gym=gym).count()
    logs_today = GymAdminLog.objects.filter(gym=gym, created_at__gte=today_start).count()

    category_counts = (
        GymAdminLog.objects.filter(gym=gym)
        .values("category")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    by_category = {item["category"]: item["count"] for item in category_counts}

    recent_logs = list(
        GymAdminLog.objects.filter(gym=gym)
        .select_related("actor", "actor__profile")
        .order_by("-created_at")[:5]
    )

    return {
        "total_logs": total_logs,
        "logs_today": logs_today,
        "by_category": by_category,
        "recent_logs": recent_logs,
    }

