import uuid
from typing import Optional, List, Dict, Any
from django.db import transaction
from django.utils import timezone

from apps.gyms.models import Gym
from apps.members.models import Member
from apps.access_control.models import GymStaffAssignment
from apps.routines.models import (
    RoutineTemplate,
    MemberRoutine,
    MemberRoutineDay,
    MemberRoutineExercise,
)
from apps.routines.services.validation_services import validate_days_payload
from common.enums import (
    RoutineFormatEnum,
    RoutineLevelEnum,
    StaffStatus,
)
from common.exceptions import (
    DomainValidationError,
)


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
        validated_days = validate_days_payload(days, final_format)
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

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        member_name = f"{member.first_name} {member.last_name}".strip() or member.email
        log_admin_action(
            gym=gym,
            action="Assigned routine to member",
            action_type=AdminLogActionType.ASSIGN_ROUTINE,
            details=f"Assigned workout routine '{member_routine.routine_name}' to {member_name}",
            category=AdminLogCategory.ROUTINES,
            target_type="member_routine",
            target_id=str(member_routine.id),
        )
    except Exception:
        pass

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
        validated_days = validate_days_payload(days, member_routine.routine_format)
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

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        member_name = f"{member.first_name} {member.last_name}".strip() or member.email
        log_admin_action(
            gym=gym,
            action="Assigned routine to member",
            action_type=AdminLogActionType.ASSIGN_ROUTINE,
            details=f"Assigned workout routine '{member_routine.routine_name}' to {member_name}",
            category=AdminLogCategory.ROUTINES,
            target_type="member_routine",
            target_id=str(member_routine.id),
        )
    except Exception:
        pass

    return member_routine
