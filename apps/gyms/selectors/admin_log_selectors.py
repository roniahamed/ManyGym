import uuid
from typing import Optional, Dict, Any, Tuple, List, Union
from datetime import datetime
from django.db.models import Q, Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from apps.gyms.models import Gym, GymAdminLog
from common.exceptions import ResourceNotFoundError, DomainValidationError


def list_admin_logs(
    gym: Gym,
    category: Optional[str] = None,
    action_type: Optional[str] = None,
    actor_id: Optional[Union[uuid.UUID, str]] = None,
    start_date: Optional[Union[datetime, str]] = None,
    end_date: Optional[Union[datetime, str]] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[GymAdminLog], int, int]:
    """
    Retrieves an optimized, paginated list of administration audit logs for a gym workspace.

    Args:
        gym: Target gym instance.
        category: Optional category filter string.
        action_type: Optional action type code filter.
        actor_id: Optional UUID (or string) of the user who performed the action.
        start_date: Optional start datetime (or ISO string) for range filtering.
        end_date: Optional end datetime (or ISO string) for range filtering.
        search: Optional search term matching action, details, actor name, or actor email.
        page: Page number (1-based index, automatically clamped).
        page_size: Items per page (clamped between 1 and 100).

    Returns:
        (logs_list, total_count, total_pages)
    """
    qs = (
        GymAdminLog.objects.filter(gym=gym)
        .select_related("actor", "actor__profile")
        .order_by("-created_at")
    )

    if category:
        clean_category = str(category).replace("\x00", "").strip()
        if clean_category:
            qs = qs.filter(category=clean_category)

    if action_type:
        clean_action_type = str(action_type).replace("\x00", "").strip()
        if clean_action_type:
            qs = qs.filter(action_type=clean_action_type)

    if actor_id:
        clean_actor_id = str(actor_id).replace("\x00", "").strip()
        try:
            uuid.UUID(clean_actor_id)
            qs = qs.filter(actor_id=clean_actor_id)
        except (ValueError, TypeError):
            raise DomainValidationError("Invalid actor_id UUID.")

    if start_date:
        if isinstance(start_date, datetime):
            parsed_start = start_date
        else:
            clean_start = str(start_date).replace("\x00", "").strip()
            try:
                parsed_start = parse_datetime(clean_start) or parse_date(clean_start)
            except (ValueError, TypeError, OverflowError):
                raise DomainValidationError("Invalid start_date format. Expected ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).")
            if not parsed_start:
                raise DomainValidationError("Invalid start_date format. Expected ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).")
            if not hasattr(parsed_start, "hour"):
                parsed_start = timezone.datetime.combine(
                    parsed_start,
                    timezone.datetime.min.time(),
                    tzinfo=timezone.get_current_timezone(),
                )
        qs = qs.filter(created_at__gte=parsed_start)

    if end_date:
        if isinstance(end_date, datetime):
            parsed_end = end_date
        else:
            clean_end = str(end_date).replace("\x00", "").strip()
            try:
                parsed_end = parse_datetime(clean_end) or parse_date(clean_end)
            except (ValueError, TypeError, OverflowError):
                raise DomainValidationError("Invalid end_date format. Expected ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).")
            if not parsed_end:
                raise DomainValidationError("Invalid end_date format. Expected ISO format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS).")
            if not hasattr(parsed_end, "hour"):
                parsed_end = timezone.datetime.combine(
                    parsed_end,
                    timezone.datetime.max.time(),
                    tzinfo=timezone.get_current_timezone(),
                )
        qs = qs.filter(created_at__lte=parsed_end)

    if search:
        search_term = str(search).replace("\x00", "").strip()
        if search_term:
            qs = qs.filter(
                Q(action__icontains=search_term)
                | Q(details__icontains=search_term)
                | Q(actor_name__icontains=search_term)
                | Q(actor_email__icontains=search_term)
            )

    total_count = qs.count()

    try:
        raw_page = int(page)
    except (ValueError, TypeError, OverflowError):
        raw_page = 1

    try:
        raw_page_size = int(page_size)
    except (ValueError, TypeError, OverflowError):
        raw_page_size = 20

    safe_page_size = max(1, min(raw_page_size, 100))
    safe_page = max(1, min(raw_page, 100_000))
    offset = (safe_page - 1) * safe_page_size
    total_pages = (total_count + safe_page_size - 1) // safe_page_size if total_count > 0 else 1

    logs = list(qs[offset : offset + safe_page_size])
    return logs, total_count, total_pages


def get_admin_log_by_id(gym: Gym, log_id: Union[uuid.UUID, str]) -> GymAdminLog:
    """
    Retrieves a single administration log record for the specified gym.

    Args:
        gym: Gym entity scope.
        log_id: UUID of the admin log record.

    Returns:
        The matched GymAdminLog instance.

    Raises:
        DomainValidationError: If log_id is not a valid UUID string.
        ResourceNotFoundError: If the log does not exist or does not belong to the gym.
    """
    clean_id = str(log_id).replace("\x00", "").strip()
    try:
        uuid.UUID(clean_id)
    except (ValueError, TypeError):
        raise DomainValidationError("Invalid log_id UUID.")

    try:
        return (
            GymAdminLog.objects.select_related("actor", "actor__profile")
            .get(gym=gym, id=clean_id)
        )
    except GymAdminLog.DoesNotExist:
        raise ResourceNotFoundError("Admin log entry not found.")


def get_admin_logs_metrics(gym: Gym) -> Dict[str, Any]:
    """
    Calculates summary metrics for gym administration activity.

    Returns:
        A dictionary containing:
        - `total_logs`: Total number of administrative logs.
        - `logs_today`: Number of logs created today.
        - `by_category`: Count distribution map per category.
        - `recent_logs`: The 5 most recent GymAdminLog instances.
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
