import uuid
from typing import Optional, Dict, Any, List, Generator
from django.db import connection
from django.db.models import Q, QuerySet, Count, Case, When, IntegerField, Prefetch
from django.core.exceptions import ValidationError

from apps.gyms.models import Gym
from apps.leads.models import (
    Lead,
    LeadCustomReasons,
    LeadFitnessGoals,
    LeadNextMove,
    LeadNotes,
)
from common.enums import LeadStageEnum
from common.exceptions import ResourceNotFoundError


def list_custom_reasons(gym: Gym) -> QuerySet[LeadCustomReasons]:
    """
    Returns all configured custom lost reasons for a specific gym.
    Uses column projection to avoid retrieving unused metadata.
    """
    return (
        LeadCustomReasons.objects.filter(gym=gym)
        .only("id", "gym_id", "reason_name", "created_at")
        .order_by("reason_name")
    )


def get_lead_by_id(gym: Gym, lead_id: uuid.UUID) -> Lead:
    """
    Retrieves a single lead record scoped to a gym with eager loading.
    """
    try:
        return (
            Lead.objects.select_related(
                "assigned_staff__user",
                "interested_plan",
                "converted_member",
                "not_joining_custom_reason",
            )
            .get(id=lead_id, gym=gym)
        )
    except (Lead.DoesNotExist, ValidationError, ValueError):
        raise ResourceNotFoundError(f"Lead with ID '{lead_id}' does not exist in this gym.")


def get_lead_details(gym: Gym, lead_id: uuid.UUID) -> Lead:
    """
    Retrieves complete lead dossier including next moves, notes, and fitness goals.
    Uses coordinated prefetching with column projections to eliminate N+1 queries.
    """
    try:
        return (
            Lead.objects.select_related(
                "gym",
                "assigned_staff__user",
                "interested_plan",
                "converted_member",
                "not_joining_custom_reason",
            )
            .prefetch_related(
                Prefetch(
                    "fitness_goals",
                    queryset=LeadFitnessGoals.objects.only("id", "lead_id", "goal"),
                ),
                Prefetch(
                    "next_moves",
                    queryset=LeadNextMove.objects.only(
                        "id",
                        "lead_id",
                        "scheduled_date",
                        "short_description",
                        "is_completed",
                        "created_at",
                    ),
                ),
                Prefetch(
                    "notes",
                    queryset=LeadNotes.objects.select_related("author_staff__user").only(
                        "id",
                        "lead_id",
                        "author_staff__id",
                        "author_staff__user__id",
                        "author_staff__user__first_name",
                        "author_staff__user__last_name",
                        "author_staff__user__email",
                        "note_text",
                        "created_at",
                    ),
                ),
            )
            .get(id=lead_id, gym=gym)
        )
    except (Lead.DoesNotExist, ValidationError, ValueError):
        raise ResourceNotFoundError(f"Lead with ID '{lead_id}' does not exist in this gym.")


def list_leads(
    gym: Gym,
    stage: Optional[str] = None,
    source: Optional[str] = None,
    assigned_staff_id: Optional[uuid.UUID] = None,
    interested_plan_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
) -> QuerySet[Lead]:
    """
    Retrieves leads directory for a gym with query filters, search, and prefetching.
    Annotates pending_next_moves_count directly in the database to eliminate relation traversals.
    """
    qs = (
        Lead.objects.filter(gym=gym)
        .select_related(
            "assigned_staff__user",
            "interested_plan",
            "converted_member",
            "not_joining_custom_reason",
        )
        .prefetch_related(
            Prefetch(
                "fitness_goals",
                queryset=LeadFitnessGoals.objects.only("id", "lead_id", "goal"),
            ),
        )
        .annotate(
            annotated_pending_moves=Count(
                "next_moves",
                filter=Q(next_moves__is_completed=False),
                distinct=True,
            )
        )
        .only(
            "id",
            "gym_id",
            "first_name",
            "last_name",
            "phone",
            "email",
            "stage",
            "source",
            "expected_start_date",
            "trial_booked_at",
            "not_joining_reason_standard",
            "not_joining_custom_reason__id",
            "not_joining_custom_reason__reason_name",
            "interested_plan__id",
            "interested_plan__name",
            "assigned_staff__id",
            "assigned_staff__user__id",
            "assigned_staff__user__first_name",
            "assigned_staff__user__last_name",
            "converted_member__id",
            "converted_member__first_name",
            "converted_member__last_name",
            "created_at",
            "updated_at",
        )
    )

    if stage:
        qs = qs.filter(stage=stage)

    if source:
        qs = qs.filter(source=source)

    if assigned_staff_id:
        qs = qs.filter(assigned_staff_id=assigned_staff_id)

    if interested_plan_id:
        qs = qs.filter(interested_plan_id=interested_plan_id)

    if search:
        search_term = search.strip()
        qs = qs.filter(
            Q(first_name__icontains=search_term)
            | Q(last_name__icontains=search_term)
            | Q(email__icontains=search_term)
            | Q(phone__icontains=search_term)
        )

    return qs.order_by("-created_at")


def stream_leads(
    gym: Gym,
    chunk_size: int = 500,
    **filters,
) -> Generator[Lead, None, None]:
    """
    Memory-efficient generator that streams large leads datasets using QuerySet.iterator()
    without materializing the entire directory in Python memory.
    """
    qs = list_leads(gym=gym, **filters)
    for lead in qs.iterator(chunk_size=chunk_size):
        yield lead


def get_lead_metrics(gym: Gym) -> Dict[str, Any]:
    """
    Computes sales pipeline funnel KPIs in a single unified PostgreSQL aggregation query.
    Reduces database query count from 2 to 1 (50% query reduction).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT 
                COUNT(l.id) AS total_leads,
                COUNT(CASE WHEN l.stage = 'new' THEN 1 END) AS new_count,
                COUNT(CASE WHEN l.stage = 'contacted' THEN 1 END) AS contacted_count,
                COUNT(CASE WHEN l.stage = 'visit_trial_booked' THEN 1 END) AS trial_booked_count,
                COUNT(CASE WHEN l.stage = 'joined' THEN 1 END) AS joined_count,
                COUNT(CASE WHEN l.stage = 'not_joining' THEN 1 END) AS not_joining_count,
                COALESCE((
                    SELECT COUNT(*) 
                    FROM lead_next_moves nm 
                    JOIN leads l2 ON nm.lead_id = l2.id 
                    WHERE l2.gym_id = %s AND nm.is_completed = FALSE
                ), 0) AS pending_next_moves_count
            FROM leads l
            WHERE l.gym_id = %s
            """,
            [gym.id, gym.id],
        )
        row = cursor.fetchone()

    total = row[0] or 0
    joined = row[4] or 0
    conversion_rate = round((joined / total * 100), 2) if total > 0 else 0.0

    return {
        "total_leads": total,
        "new": row[1] or 0,
        "contacted": row[2] or 0,
        "visit_trial_booked": row[3] or 0,
        "joined": joined,
        "not_joining": row[5] or 0,
        "conversion_rate_percentage": conversion_rate,
        "pending_next_moves_count": row[6] or 0,
    }
