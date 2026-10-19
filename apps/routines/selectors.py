import uuid
from typing import Optional, Generator
from django.db.models import QuerySet, Q, Count

from apps.gyms.models import Gym
from apps.members.models import Member
from apps.routines.models import RoutineTemplate, MemberRoutine
from common.exceptions import ResourceNotFoundError


def list_routine_templates(
    gym: Gym,
    routine_format: Optional[str] = None,
    level: Optional[str] = None,
    goal: Optional[str] = None,
    search: Optional[str] = None,
) -> QuerySet[RoutineTemplate]:
    """
    Returns an optimized queryset of routine templates for a gym with eager loading of goals,
    and database-level aggregation for days_count and total_exercises_count to eliminate N+1 queries.
    """
    qs = (
        RoutineTemplate.objects.filter(gym=gym)
        .select_related("gym", "created_by_staff__user")
        .prefetch_related("goals")
        .annotate(
            annotated_days_count=Count("days", distinct=True),
            annotated_exercises_count=Count("days__exercises", distinct=True),
        )
        .order_by("-created_at")
    )

    if routine_format:
        qs = qs.filter(routine_format=routine_format)

    if level:
        qs = qs.filter(level=level)

    if goal:
        qs = qs.filter(goals__goal=goal.strip().lower()).distinct()

    if search:
        search_term = search.strip()
        qs = qs.filter(
            Q(template_name__icontains=search_term)
            | Q(notes__icontains=search_term)
        ).distinct()

    return qs


def get_routine_template_detail(gym: Gym, template_id: uuid.UUID) -> RoutineTemplate:
    """
    Retrieves a single routine template dossier with all nested days and exercise structures.
    """
    try:
        return (
            RoutineTemplate.objects.filter(gym=gym, id=template_id)
            .select_related("gym", "created_by_staff__user")
            .prefetch_related("goals", "days__exercises")
            .get()
        )
    except RoutineTemplate.DoesNotExist:
        raise ResourceNotFoundError("Routine template not found.")


def stream_routine_templates(gym: Gym, chunk_size: int = 1000) -> Generator[RoutineTemplate, None, None]:
    """
    Memory-efficient generator for routine templates streaming and data exports.
    """
    qs = (
        RoutineTemplate.objects.filter(gym=gym)
        .select_related("gym", "created_by_staff__user")
        .prefetch_related("goals", "days__exercises")
        .order_by("-created_at")
    )
    yield from qs.iterator(chunk_size=chunk_size)


def get_member_active_routine(gym: Gym, member_id: uuid.UUID) -> Optional[MemberRoutine]:
    """
    Retrieves the current active workout routine prescribed to a member.
    """
    try:
        Member.objects.get(id=member_id, gym=gym)
    except Member.DoesNotExist:
        raise ResourceNotFoundError("Member not found.")

    return (
        MemberRoutine.objects.filter(member_id=member_id, member__gym=gym, is_active=True)
        .select_related("prescribed_by_staff__user", "source_template")
        .prefetch_related("days__exercises")
        .annotate(annotated_days_count=Count("days", distinct=True))
        .first()
    )


def list_member_routine_history(gym: Gym, member_id: uuid.UUID) -> QuerySet[MemberRoutine]:
    """
    Retrieves all current and previous routine assignments for a member.
    """
    try:
        Member.objects.get(id=member_id, gym=gym)
    except Member.DoesNotExist:
        raise ResourceNotFoundError("Member not found.")

    return (
        MemberRoutine.objects.filter(member_id=member_id, member__gym=gym)
        .select_related("prescribed_by_staff__user", "source_template")
        .prefetch_related("days__exercises")
        .annotate(annotated_days_count=Count("days", distinct=True))
        .order_by("-is_active", "-assigned_at")
    )


def get_member_routine_by_id(gym: Gym, member_id: uuid.UUID, routine_id: uuid.UUID) -> MemberRoutine:
    """
    Retrieves a specific member routine record by ID.
    """
    try:
        return (
            MemberRoutine.objects.filter(id=routine_id, member_id=member_id, member__gym=gym)
            .select_related("prescribed_by_staff__user", "source_template")
            .prefetch_related("days__exercises")
            .get()
        )
    except MemberRoutine.DoesNotExist:
        raise ResourceNotFoundError("Member routine not found.")
