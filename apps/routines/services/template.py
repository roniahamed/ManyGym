import uuid
from typing import Optional, List, Dict, Any
from django.db import transaction

from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from apps.routines.models import (
    RoutineTemplate,
    RoutineTemplateGoal,
    RoutineTemplateDay,
    RoutineTemplateExercise,
    MemberRoutine,
)
from apps.routines.services.validation import validate_days_payload
from common.enums import (
    RoutineFormatEnum,
    RoutineLevelEnum,
    FitnessGoalEnum,
    StaffStatus,
)
from common.exceptions import (
    DomainValidationError,
    ResourceConflictError,
)


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
        validated_days = validate_days_payload(days, routine_format)
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
        validated_days = validate_days_payload(days, new_format)
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
