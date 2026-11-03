import uuid
from typing import Optional, Dict, Any, Tuple, List, Union, Iterator
from datetime import datetime
from django.db.models import Q, Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from apps.gyms.models import Gym, GymAdminLog
from common.exceptions import ResourceNotFoundError, DomainValidationError

ADMIN_LOG_LIST_ONLY_FIELDS = (
    "id",
    "gym_id",
    "actor_id",
    "actor_name",
    "actor_email",
    "action",
    "action_type",
    "category",
    "details",
    "target_type",
    "target_id",
    "metadata",
    "created_at",
    "actor__id",
    "actor__email",
    "actor__first_name",
    "actor__last_name",
    "actor__profile__id",
    "actor__profile__avatar_url",
)

ADMIN_LOG_EXPORT_CSV_ONLY_FIELDS = (
    "actor_name",
    "actor_email",
    "actor__email",
    "action",
    "details",
    "created_at",
    "category",
    "action_type",
    "target_type",
    "target_id",
)


def _build_admin_logs_filtered_queryset(
    gym: Gym,
    category: Optional[str] = None,
    action_type: Optional[str] = None,
    actor_id: Optional[Union[uuid.UUID, str]] = None,
    start_date: Optional[Union[datetime, str]] = None,
    end_date: Optional[Union[datetime, str]] = None,
    search: Optional[str] = None,
):
    """Internal helper to construct filtered querysets with index awareness."""
    qs = GymAdminLog.objects.filter(gym=gym)

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

    return qs


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
    Employs field projections (only) and relationship loading (select_related) to minimize
    memory footprint and completely eliminate N+1 queries.

    Returns:
        (logs_list, total_count, total_pages)
    """
    base_qs = _build_admin_logs_filtered_queryset(
        gym=gym,
        category=category,
        action_type=action_type,
        actor_id=actor_id,
        start_date=start_date,
        end_date=end_date,
        search=search,
    )

    total_count = base_qs.count()

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

    # Project only fields required by serializer and order by compound index (gym, -created_at)
    page_qs = (
        base_qs.select_related("actor", "actor__profile")
        .only(*ADMIN_LOG_LIST_ONLY_FIELDS)
        .order_by("-created_at")
    )

    logs = list(page_qs[offset : offset + safe_page_size])
    return logs, total_count, total_pages


def get_admin_log_by_id(gym: Gym, log_id: Union[uuid.UUID, str]) -> GymAdminLog:
    """
    Retrieves a single administration log record with optimized field projections.
    """
    clean_id = str(log_id).replace("\x00", "").strip()
    try:
        uuid.UUID(clean_id)
    except (ValueError, TypeError):
        raise DomainValidationError("Invalid log_id UUID.")

    try:
        return (
            GymAdminLog.objects.filter(gym=gym, id=clean_id)
            .select_related("actor", "actor__profile")
            .only(*ADMIN_LOG_LIST_ONLY_FIELDS)
            .get()
        )
    except GymAdminLog.DoesNotExist:
        raise ResourceNotFoundError("Admin log entry not found.")


def get_admin_logs_metrics(gym: Gym) -> Dict[str, Any]:
    """
    Calculates summary metrics for gym administration activity.
    Combines total_logs and logs_today into a SINGLE database aggregation query using Q filters,
    reducing query count by 25%.
    """
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)

    # Consolidated conditional aggregation (1 query for both totals)
    aggregates = GymAdminLog.objects.filter(gym=gym).aggregate(
        total_logs=Count("id"),
        logs_today=Count("id", filter=Q(created_at__gte=today_start)),
    )
    total_logs = aggregates["total_logs"] or 0
    logs_today = aggregates["logs_today"] or 0

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
        .only(*ADMIN_LOG_LIST_ONLY_FIELDS)
        .order_by("-created_at")[:5]
    )

    return {
        "total_logs": total_logs,
        "logs_today": logs_today,
        "by_category": by_category,
        "recent_logs": recent_logs,
    }


def get_admin_logs_export_iterator(
    gym: Gym,
    category: Optional[str] = None,
    action_type: Optional[str] = None,
    actor_id: Optional[Union[uuid.UUID, str]] = None,
    start_date: Optional[Union[datetime, str]] = None,
    end_date: Optional[Union[datetime, str]] = None,
    search: Optional[str] = None,
    limit: int = 5000,
    is_csv: bool = True,
) -> Iterator[GymAdminLog]:
    """
    Memory-efficient iterator for administrative logs export.
    Uses chunked fetching (.iterator(chunk_size=500)) and field projections
    to ensure O(1) memory consumption even during large dataset exports.
    """
    base_qs = _build_admin_logs_filtered_queryset(
        gym=gym,
        category=category,
        action_type=action_type,
        actor_id=actor_id,
        start_date=start_date,
        end_date=end_date,
        search=search,
    ).order_by("-created_at")

    if is_csv:
        qs = (
            base_qs.select_related("actor")
            .only(*ADMIN_LOG_EXPORT_CSV_ONLY_FIELDS)[:limit]
            .iterator(chunk_size=500)
        )
    else:
        qs = (
            base_qs.select_related("actor", "actor__profile")
            .only(*ADMIN_LOG_LIST_ONLY_FIELDS)[:limit]
            .iterator(chunk_size=500)
        )

    return qs
