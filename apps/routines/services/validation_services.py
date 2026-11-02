from typing import List, Dict, Any

from common.enums import (
    RoutineFormatEnum,
)
from common.exceptions import (
    DomainValidationError,
)


def validate_exercise_data(ex_data: Dict[str, Any], day_label: str) -> Dict[str, Any]:
    name = (ex_data.get("exercise_name") or "").strip()
    if not name:
        raise DomainValidationError(f"Exercise name cannot be blank on {day_label}.")

    reps_or_dur = (ex_data.get("reps_or_duration") or "").strip()
    if not reps_or_dur:
        raise DomainValidationError(f"Reps or duration cannot be blank for exercise '{name}' on {day_label}.")

    sets = ex_data.get("sets")
    if sets is not None:
        try:
            sets = int(sets)
            if sets < 1:
                raise DomainValidationError(f"Sets must be at least 1 for exercise '{name}' on {day_label}.")
        except (ValueError, TypeError):
            raise DomainValidationError(f"Invalid integer value for sets in exercise '{name}' on {day_label}.")

    rest_seconds = ex_data.get("rest_seconds")
    if rest_seconds is not None:
        try:
            rest_seconds = int(rest_seconds)
            if rest_seconds < 0:
                raise DomainValidationError(f"Rest seconds cannot be negative for exercise '{name}' on {day_label}.")
        except (ValueError, TypeError):
            raise DomainValidationError(f"Invalid integer value for rest seconds in exercise '{name}' on {day_label}.")

    return {
        "exercise_name": name,
        "sets": sets,
        "reps_or_duration": reps_or_dur,
        "rest_seconds": rest_seconds,
        "notes": (ex_data.get("notes") or "").strip() or None,
        "sort_order": int(ex_data.get("sort_order") or 0),
    }


def validate_days_payload(
    days: List[Dict[str, Any]],
    routine_format: str,
) -> List[Dict[str, Any]]:
    if not isinstance(days, list):
        raise DomainValidationError("Days payload must be a list of day objects.")

    validated_days = []
    seen_identifiers = set()

    for idx, day_data in enumerate(days):
        if not isinstance(day_data, dict):
            raise DomainValidationError(f"Invalid day structure at position {idx}.")

        is_rest_day = bool(day_data.get("is_rest_day", False))
        workout_title = (day_data.get("workout_title") or "").strip() or None
        workday_note = (day_data.get("workday_note") or "").strip() or None
        sort_order = int(day_data.get("sort_order", idx))

        day_of_week = None
        session_number = None

        if routine_format == RoutineFormatEnum.WEEKLY:
            raw_dow = day_data.get("day_of_week")
            if raw_dow is None:
                raise DomainValidationError(f"Day at position {idx} is missing required 'day_of_week' (1-7).")
            try:
                day_of_week = int(raw_dow)
                if not (1 <= day_of_week <= 7):
                    raise DomainValidationError(f"day_of_week must be an integer between 1 (Monday) and 7 (Sunday), got {day_of_week}.")
            except (ValueError, TypeError):
                raise DomainValidationError(f"day_of_week must be an integer between 1 and 7 at position {idx}.")

            if day_of_week in seen_identifiers:
                raise DomainValidationError(f"Duplicate day_of_week {day_of_week} found in routine schedule.")
            seen_identifiers.add(day_of_week)
            day_label = f"Day {day_of_week}"
        else:
            # Session-Based: Rest days are not permitted in session format
            if day_data.get("is_rest_day"):
                raise DomainValidationError(f"Session-based routine format cannot contain rest days.")
            is_rest_day = False
            raw_sess = day_data.get("session_number", idx + 1)
            try:
                session_number = int(raw_sess)
                if session_number < 1:
                    raise DomainValidationError(f"session_number must be at least 1, got {session_number}.")
            except (ValueError, TypeError):
                raise DomainValidationError(f"session_number must be a valid positive integer at position {idx}.")

            if session_number in seen_identifiers:
                raise DomainValidationError(f"Duplicate session_number {session_number} found in routine schedule.")
            seen_identifiers.add(session_number)
            day_label = f"Session {session_number}"

        raw_exercises = day_data.get("exercises", [])
        if not isinstance(raw_exercises, list):
            raise DomainValidationError(f"Exercises must be an array on {day_label}.")

        # If it is a rest day, exercises should not be defined
        if is_rest_day and raw_exercises:
            raise DomainValidationError(f"{day_label} is marked as a Rest Day and cannot contain exercises.")

        validated_exercises = []
        for ex_idx, ex_item in enumerate(raw_exercises):
            if not isinstance(ex_item, dict):
                raise DomainValidationError(f"Invalid exercise object at index {ex_idx} on {day_label}.")
            validated_ex = validate_exercise_data(ex_item, day_label)
            validated_exercises.append(validated_ex)

        validated_days.append({
            "day_of_week": day_of_week,
            "session_number": session_number,
            "is_rest_day": is_rest_day,
            "workout_title": workout_title,
            "workday_note": workday_note,
            "sort_order": sort_order,
            "exercises": validated_exercises,
        })

    return validated_days
