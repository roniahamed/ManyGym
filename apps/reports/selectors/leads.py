from datetime import date
from typing import Dict, Any
from django.db.models import Count

from apps.gyms.models import Gym
from apps.leads.models import Lead
from common.enums import LeadStageEnum


def get_lead_funnel_report(gym: Gym, start_date: date, end_date: date) -> Dict[str, Any]:
    """
    Computes lead conversion pipeline analytics:
    - Funnel stages (New -> Contacted -> Trial Booked -> Joined -> Lost)
    - Conversion and drop-off percentages
    - Lost reason distribution (standard and custom)
    - Acquisition sources
    """
    leads_qs = Lead.objects.filter(
        gym=gym,
        created_at__date__range=(start_date, end_date),
    )

    # 1. Pipeline stage breakdown
    stage_data = list(
        leads_qs.values("stage")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    stage_counts = {row["stage"]: row["count"] for row in stage_data}
    total_leads = sum(stage_counts.values())

    if total_leads == 0:
        return {
            "gym_id": gym.id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "total_leads": 0,
            "funnel_stages": {
                "new": 0,
                "contacted": 0,
                "trial_booked": 0,
                "joined": 0,
                "lost": 0,
            },
            "conversion_rates": {
                "trial_booking_rate_percentage": 0.0,
                "trial_to_join_rate_percentage": 0.0,
                "overall_conversion_rate_percentage": 0.0,
                "drop_off_rate_percentage": 0.0,
            },
            "stage_breakdown": [],
            "lost_reason_distribution": [],
            "source_breakdown": [],
        }

    new_count = stage_counts.get(LeadStageEnum.NEW, 0)
    contacted_count = stage_counts.get(LeadStageEnum.CONTACTED, 0)

    # Any booked trials outside VISIT_TRIAL_BOOKED stage
    extra_trials = (
        leads_qs.filter(trial_booked_at__isnull=False)
        .exclude(stage=LeadStageEnum.VISIT_TRIAL_BOOKED)
        .count()
    )
    trial_count = stage_counts.get(LeadStageEnum.VISIT_TRIAL_BOOKED, 0) + extra_trials

    joined_count = stage_counts.get(LeadStageEnum.JOINED, 0)
    lost_count = stage_counts.get(LeadStageEnum.NOT_JOINING, 0)

    # Conversion rates with division-by-zero protection
    trial_booking_rate = round((trial_count / total_leads * 100), 2) if total_leads > 0 else 0.0
    trial_to_join_rate = round((joined_count / trial_count * 100), 2) if trial_count > 0 else 0.0
    overall_conversion_rate = round((joined_count / total_leads * 100), 2) if total_leads > 0 else 0.0
    drop_off_rate = round((lost_count / total_leads * 100), 2) if total_leads > 0 else 0.0

    # 2. Lost reason distribution (only query if lost_count > 0)
    lost_reasons = []
    if lost_count > 0:
        lost_standard = (
            leads_qs.filter(stage=LeadStageEnum.NOT_JOINING, not_joining_reason_standard__isnull=False)
            .values("not_joining_reason_standard")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        lost_custom = (
            leads_qs.filter(stage=LeadStageEnum.NOT_JOINING, not_joining_custom_reason__isnull=False)
            .values("not_joining_custom_reason__reason_name")
            .annotate(count=Count("id"))
            .order_by("-count")
        )
        lost_reasons = [
            {"reason": row["not_joining_reason_standard"], "type": "standard", "count": row["count"]}
            for row in lost_standard
        ] + [
            {"reason": row["not_joining_custom_reason__reason_name"], "type": "custom", "count": row["count"]}
            for row in lost_custom
        ]

    # 3. Source distribution
    source_data = (
        leads_qs.values("source")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    source_breakdown = [
        {
            "source": row["source"],
            "count": row["count"],
            "percentage": round((row["count"] / total_leads * 100), 2) if total_leads > 0 else 0.0,
        }
        for row in source_data
    ]

    return {
        "gym_id": gym.id,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "total_leads": total_leads,
        "funnel_stages": {
            "new": new_count,
            "contacted": contacted_count,
            "trial_booked": trial_count,
            "joined": joined_count,
            "lost": lost_count,
        },
        "conversion_rates": {
            "trial_booking_rate_percentage": trial_booking_rate,
            "trial_to_join_rate_percentage": trial_to_join_rate,
            "overall_conversion_rate_percentage": overall_conversion_rate,
            "drop_off_rate_percentage": drop_off_rate,
        },
        "stage_breakdown": [{"stage": s, "count": c} for s, c in stage_counts.items()],
        "lost_reason_distribution": lost_reasons,
        "source_breakdown": source_breakdown,
    }
