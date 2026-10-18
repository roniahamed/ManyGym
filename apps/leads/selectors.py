import uuid
from typing import Optional, Dict, Any, List
from django.db.models import Q, QuerySet, Count, Case, When, IntegerField
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
    """
    return LeadCustomReasons.objects.filter(gym=gym).only("id", "gym_id", "reason_name", "created_at").order_by("reason_name")


def get_lead_by_id(gym: Gym, lead_id: uuid.UUID) -> Lead:
    """
    Retrieves a single lead record scoped to a gym.
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
                "fitness_goals",
                "next_moves",
                "notes__author_staff__user",
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
            "fitness_goals",
            "next_moves",
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


def get_lead_metrics(gym: Gym) -> Dict[str, Any]:
    """
    Computes sales pipeline funnel KPIs in an optimized single aggregation query.
    """
    metrics = Lead.objects.filter(gym=gym).aggregate(
        total_leads=Count("id"),
        new_count=Count(Case(When(stage=LeadStageEnum.NEW, then=1), output_field=IntegerField())),
        contacted_count=Count(Case(When(stage=LeadStageEnum.CONTACTED, then=1), output_field=IntegerField())),
        trial_booked_count=Count(Case(When(stage=LeadStageEnum.VISIT_TRIAL_BOOKED, then=1), output_field=IntegerField())),
        joined_count=Count(Case(When(stage=LeadStageEnum.JOINED, then=1), output_field=IntegerField())),
        not_joining_count=Count(Case(When(stage=LeadStageEnum.NOT_JOINING, then=1), output_field=IntegerField())),
    )

    total = metrics.get("total_leads") or 0
    joined = metrics.get("joined_count") or 0
    conversion_rate = round((joined / total * 100), 2) if total > 0 else 0.0

    pending_next_moves = LeadNextMove.objects.filter(
        lead__gym=gym,
        is_completed=False,
    ).count()

    return {
        "total_leads": total,
        "new": metrics.get("new_count") or 0,
        "contacted": metrics.get("contacted_count") or 0,
        "visit_trial_booked": metrics.get("trial_booked_count") or 0,
        "joined": joined,
        "not_joining": metrics.get("not_joining_count") or 0,
        "conversion_rate_percentage": conversion_rate,
        "pending_next_moves_count": pending_next_moves,
    }
