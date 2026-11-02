from datetime import date, datetime, timedelta
from typing import Dict, Any, Tuple
from django.utils import timezone
from common.exceptions import DomainValidationError


def parse_and_validate_date_range(
    query_params: Dict[str, Any],
    default_days: int = 30,
) -> Tuple[date, date]:
    """
    Parses and validates 'start_date' and 'end_date' query parameters.
    Format must be YYYY-MM-DD.
    Enforces that start_date <= end_date.
    Defaults to the past `default_days` ending today.
    """
    today = timezone.localdate()
    start_str = query_params.get("start_date")
    end_str = query_params.get("end_date")

    if end_str:
        s_end = str(end_str).strip()
        if len(s_end) != 10 or s_end[4] != '-' or s_end[7] != '-':
            raise DomainValidationError("Invalid date format for 'end_date'. Expected YYYY-MM-DD.")
        try:
            end_date = datetime.strptime(s_end, "%Y-%m-%d").date()
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid date format for 'end_date'. Expected YYYY-MM-DD.")
    else:
        end_date = today

    if start_str:
        s_start = str(start_str).strip()
        if len(s_start) != 10 or s_start[4] != '-' or s_start[7] != '-':
            raise DomainValidationError("Invalid date format for 'start_date'. Expected YYYY-MM-DD.")
        try:
            start_date = datetime.strptime(s_start, "%Y-%m-%d").date()
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid date format for 'start_date'. Expected YYYY-MM-DD.")
    else:
        try:
            start_date = end_date - timedelta(days=default_days)
        except (OverflowError, ValueError):
            raise DomainValidationError("Calculated date range is out of valid bounds.")

    if start_date > end_date:
        raise DomainValidationError("'start_date' cannot be after 'end_date'.")

    return start_date, end_date
