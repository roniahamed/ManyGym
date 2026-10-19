import uuid
from typing import Optional, List, Dict, Any
from django.db import transaction
from django.utils import timezone

from apps.gyms.models import Gym
from apps.members.models import Member
from apps.access_control.models import GymStaffAssignment
from apps.routines.models import (
    RoutineTemplate,
    RoutineTemplateGoal,
    RoutineTemplateDay,
    RoutineTemplateExercise,
    MemberRoutine,
    MemberRoutineDay,
    MemberRoutineExercise,
)
from common.enums import (
    RoutineFormatEnum,
    RoutineLevelEnum,
    FitnessGoalEnum,
    StaffStatus,
)
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    ResourceConflictError,
)


def _validate_exercise_data(ex_data: Dict[str, Any], day_label: str) -> Dict[str, Any]:
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


def _validate_days_payload(
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
            # Session-Based: Rest days are disabled in session format
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
            validated_ex = _validate_exercise_data(ex_item, day_label)
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


@transaction.atomic
def create_routine_template(
    gym: Gym,
    template_name: str,
    routine_format: str = RoutineFormatEnum.WEEKLY,
    level: str = RoutineLevelEnum.BEGINNER,
    notes: Optional[str] = None,
    goals: Optional[List[str]] = None,
    days: Optional[List[Dict[str, Any]]] = None,
    created_by_staff_id: Optional[uuid.UUID] = None,
) -> RoutineTemplate:
    """
    Creates a new routine template header, target fitness goals, and nested days/exercises.
    """
    name_clean = (template_name or "").strip()
    if not name_clean:
        raise DomainValidationError("Template name cannot be empty.")

    if routine_format not in RoutineFormatEnum.values:
        raise DomainValidationError(f"Invalid routine_format '{routine_format}'. Choices: {RoutineFormatEnum.values}.")

    if level not in RoutineLevelEnum.values:
        raise DomainValidationError(f"Invalid level '{level}'. Choices: {RoutineLevelEnum.values}.")

    created_by_staff = None
    if created_by_staff_id:
        try:
            created_by_staff = GymStaffAssignment.objects.get(
                id=created_by_staff_id,
                gym=gym,
                status=StaffStatus.ACTIVE,
            )
        except GymStaffAssignment.DoesNotExist:
            raise DomainValidationError("The assigned author staff member does not exist or is inactive in this gym.")

    template = RoutineTemplate.objects.create(
        gym=gym,
        template_name=name_clean,
        routine_format=routine_format,
        level=level,
        notes=(notes or "").strip() or None,
        created_by_staff=created_by_staff,
    )

    # Associate Fitness Goals
    if goals:
        clean_goals = []
        for g in goals:
            g_str = str(g).strip().lower()
            if g_str not in FitnessGoalEnum.values:
                raise DomainValidationError(f"Invalid fitness goal '{g_str}'. Choices: {FitnessGoalEnum.values}.")
            clean_goals.append(g_str)

        # De-duplicate
        unique_goals = list(dict.fromkeys(clean_goals))
        goal_objs = [
            RoutineTemplateGoal(template=template, goal=g)
            for g in unique_goals
        ]
        RoutineTemplateGoal.objects.bulk_create(goal_objs)

    # Associate Days & Exercises
    if days:
        validated_days = _validate_days_payload(days, routine_format)
        for d_data in validated_days:
            day_obj = RoutineTemplateDay.objects.create(
                template=template,
                day_of_week=d_data["day_of_week"],
                session_number=d_data["session_number"],
                is_rest_day=d_data["is_rest_day"],
                workout_title=d_data["workout_title"],
                workday_note=d_data["workday_note"],
                sort_order=d_data["sort_order"],
            )
            ex_objs = [
                RoutineTemplateExercise(
                    template_day=day_obj,
                    exercise_name=ex["exercise_name"],
                    sets=ex["sets"],
                    reps_or_duration=ex["reps_or_duration"],
                    rest_seconds=ex["rest_seconds"],
                    notes=ex["notes"],
                    sort_order=ex["sort_order"],
                )
                for ex in d_data["exercises"]
            ]
            if ex_objs:
                RoutineTemplateExercise.objects.bulk_create(ex_objs)

    return template


@transaction.atomic
def update_routine_template(
    template: RoutineTemplate,
    template_name: Optional[str] = None,
    routine_format: Optional[str] = None,
    level: Optional[str] = None,
    notes: Optional[str] = None,
    goals: Optional[List[str]] = None,
    days: Optional[List[Dict[str, Any]]] = None,
) -> RoutineTemplate:
    """
    Updates routine template details and optionally replaces days and exercise structure.
    """
    update_fields = ["updated_at"]

    if template_name is not None:
        name_clean = template_name.strip()
        if not name_clean:
            raise DomainValidationError("Template name cannot be empty.")
        template.template_name = name_clean
        update_fields.append("template_name")

    new_format = template.routine_format
    if routine_format is not None:
        if routine_format not in RoutineFormatEnum.values:
            raise DomainValidationError(f"Invalid routine_format '{routine_format}'.")
        template.routine_format = routine_format
        new_format = routine_format
        update_fields.append("routine_format")

    if level is not None:
        if level not in RoutineLevelEnum.values:
            raise DomainValidationError(f"Invalid level '{level}'.")
        template.level = level
        update_fields.append("level")

    if notes is not None:
        template.notes = notes.strip() or None
        update_fields.append("notes")

    template.save(update_fields=update_fields)

    # Update goals if explicitly passed
    if goals is not None:
        template.goals.all().delete()
        clean_goals = []
        for g in goals:
            g_str = str(g).strip().lower()
            if g_str not in FitnessGoalEnum.values:
                raise DomainValidationError(f"Invalid fitness goal '{g_str}'.")
            clean_goals.append(g_str)
        unique_goals = list(dict.fromkeys(clean_goals))
        goal_objs = [
            RoutineTemplateGoal(template=template, goal=g)
            for g in unique_goals
        ]
        RoutineTemplateGoal.objects.bulk_create(goal_objs)

    # Replace days and exercises if explicitly passed
    if days is not None:
        template.days.all().delete()
        validated_days = _validate_days_payload(days, new_format)
        for d_data in validated_days:
            day_obj = RoutineTemplateDay.objects.create(
                template=template,
                day_of_week=d_data["day_of_week"],
                session_number=d_data["session_number"],
                is_rest_day=d_data["is_rest_day"],
                workout_title=d_data["workout_title"],
                workday_note=d_data["workday_note"],
                sort_order=d_data["sort_order"],
            )
            ex_objs = [
                RoutineTemplateExercise(
                    template_day=day_obj,
                    exercise_name=ex["exercise_name"],
                    sets=ex["sets"],
                    reps_or_duration=ex["reps_or_duration"],
                    rest_seconds=ex["rest_seconds"],
                    notes=ex["notes"],
                    sort_order=ex["sort_order"],
                )
                for ex in d_data["exercises"]
            ]
            if ex_objs:
                RoutineTemplateExercise.objects.bulk_create(ex_objs)

    return template


@transaction.atomic
def delete_routine_template(template: RoutineTemplate) -> None:
    """
    Deletes routine template if not actively prescribed to gym members.
    """
    active_prescriptions = MemberRoutine.objects.filter(
        source_template=template,
        is_active=True,
    ).exists()
    if active_prescriptions:
        raise ResourceConflictError(
            "Cannot delete routine template that is currently actively prescribed to gym members."
        )

    template.delete()


@transaction.atomic
def assign_routine_to_member(
    gym: Gym,
    member: Member,
    source_template_id: Optional[uuid.UUID] = None,
    routine_name: Optional[str] = None,
    routine_format: Optional[str] = None,
    level: Optional[str] = None,
    notes: Optional[str] = None,
    days: Optional[List[Dict[str, Any]]] = None,
    prescribed_by_staff_id: Optional[uuid.UUID] = None,
) -> MemberRoutine:
    """
    Prescribes a workout routine to a gym member, either cloned from a template or customized directly.
    Automatically archives/deactivates any currently active routine for that member.
    """
    if member.gym_id != gym.id:
        raise DomainValidationError("Member does not belong to this gym context.")

    prescribed_by_staff = None
    if prescribed_by_staff_id:
        try:
            prescribed_by_staff = GymStaffAssignment.objects.get(
                id=prescribed_by_staff_id,
                gym=gym,
                status=StaffStatus.ACTIVE,
            )
        except GymStaffAssignment.DoesNotExist:
            raise DomainValidationError("The prescribed staff member does not exist or is not active in this gym.")

    source_template = None
    if source_template_id:
        try:
            source_template = RoutineTemplate.objects.prefetch_related(
                "days__exercises"
            ).get(id=source_template_id, gym=gym)
        except RoutineTemplate.DoesNotExist:
            raise DomainValidationError("Source routine template not found in this gym.")

    final_name = (routine_name or (source_template.template_name if source_template else "")).strip()
    if not final_name:
        raise DomainValidationError("Routine name cannot be blank.")

    final_format = routine_format or (source_template.routine_format if source_template else RoutineFormatEnum.WEEKLY)
    if final_format not in RoutineFormatEnum.values:
        raise DomainValidationError(f"Invalid routine format '{final_format}'.")

    final_level = level or (source_template.level if source_template else RoutineLevelEnum.BEGINNER)
    if final_level not in RoutineLevelEnum.values:
        raise DomainValidationError(f"Invalid routine level '{final_level}'.")

    raw_notes = notes if notes is not None else (source_template.notes if source_template else None)
    final_notes = raw_notes.strip() if raw_notes else None

    # Deactivate existing active routine for this member
    MemberRoutine.objects.filter(member=member, is_active=True).update(is_active=False)

    # Create new active member routine
    member_routine = MemberRoutine.objects.create(
        member=member,
        source_template=source_template,
        prescribed_by_staff=prescribed_by_staff,
        routine_name=final_name,
        routine_format=final_format,
        level=final_level,
        is_active=True,
        notes=final_notes,
        assigned_at=timezone.now(),
    )

    if days is not None:
        # Use custom provided days layout
        validated_days = _validate_days_payload(days, final_format)
        for d_data in validated_days:
            mr_day = MemberRoutineDay.objects.create(
                member_routine=member_routine,
                day_of_week=d_data["day_of_week"],
                session_number=d_data["session_number"],
                is_rest_day=d_data["is_rest_day"],
                workout_title=d_data["workout_title"],
                workday_note=d_data["workday_note"],
                sort_order=d_data["sort_order"],
            )
            ex_objs = [
                MemberRoutineExercise(
                    member_routine_day=mr_day,
                    exercise_name=ex["exercise_name"],
                    sets=ex["sets"],
                    reps_or_duration=ex["reps_or_duration"],
                    rest_seconds=ex["rest_seconds"],
                    notes=ex["notes"],
                    sort_order=ex["sort_order"],
                )
                for ex in d_data["exercises"]
            ]
            if ex_objs:
                MemberRoutineExercise.objects.bulk_create(ex_objs)

    elif source_template:
        # Deep clone days and exercises from source template
        for t_day in source_template.days.all():
            mr_day = MemberRoutineDay.objects.create(
                member_routine=member_routine,
                day_of_week=t_day.day_of_week,
                session_number=t_day.session_number,
                is_rest_day=t_day.is_rest_day,
                workout_title=t_day.workout_title,
                workday_note=t_day.workday_note,
                sort_order=t_day.sort_order,
            )
            ex_objs = [
                MemberRoutineExercise(
                    member_routine_day=mr_day,
                    exercise_name=t_ex.exercise_name,
                    sets=t_ex.sets,
                    reps_or_duration=t_ex.reps_or_duration,
                    rest_seconds=t_ex.rest_seconds,
                    notes=t_ex.notes,
                    sort_order=t_ex.sort_order,
                )
                for t_ex in t_day.exercises.all()
            ]
            if ex_objs:
                MemberRoutineExercise.objects.bulk_create(ex_objs)

    return member_routine


@transaction.atomic
def customize_member_routine(
    member_routine: MemberRoutine,
    routine_name: Optional[str] = None,
    level: Optional[str] = None,
    notes: Optional[str] = None,
    is_active: Optional[bool] = None,
    days: Optional[List[Dict[str, Any]]] = None,
) -> MemberRoutine:
    """
    Updates or customizes an assigned member routine's layout, exercises, or active status.
    """
    update_fields = ["updated_at"]

    if routine_name is not None:
        name_clean = routine_name.strip()
        if not name_clean:
            raise DomainValidationError("Routine name cannot be blank.")
        member_routine.routine_name = name_clean
        update_fields.append("routine_name")

    if level is not None:
        if level not in RoutineLevelEnum.values:
            raise DomainValidationError(f"Invalid level '{level}'.")
        member_routine.level = level
        update_fields.append("level")

    if notes is not None:
        member_routine.notes = notes.strip() or None
        update_fields.append("notes")

    if is_active is not None:
        member_routine.is_active = bool(is_active)
        update_fields.append("is_active")
        if member_routine.is_active:
            # If activating, deactivate other active routines for this member
            MemberRoutine.objects.filter(
                member_id=member_routine.member_id,
                is_active=True,
            ).exclude(id=member_routine.id).update(is_active=False)

    member_routine.save(update_fields=update_fields)

    if days is not None:
        member_routine.days.all().delete()
        validated_days = _validate_days_payload(days, member_routine.routine_format)
        for d_data in validated_days:
            mr_day = MemberRoutineDay.objects.create(
                member_routine=member_routine,
                day_of_week=d_data["day_of_week"],
                session_number=d_data["session_number"],
                is_rest_day=d_data["is_rest_day"],
                workout_title=d_data["workout_title"],
                workday_note=d_data["workday_note"],
                sort_order=d_data["sort_order"],
            )
            ex_objs = [
                MemberRoutineExercise(
                    member_routine_day=mr_day,
                    exercise_name=ex["exercise_name"],
                    sets=ex["sets"],
                    reps_or_duration=ex["reps_or_duration"],
                    rest_seconds=ex["rest_seconds"],
                    notes=ex["notes"],
                    sort_order=ex["sort_order"],
                )
                for ex in d_data["exercises"]
            ]
            if ex_objs:
                MemberRoutineExercise.objects.bulk_create(ex_objs)

    return member_routine
