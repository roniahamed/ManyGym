from datetime import timedelta
from decimal import Decimal
from typing import Dict, Any
from django.utils import timezone
from django.db.models import Sum, Count, Q

from apps.gyms.models import Gym
from apps.members.models import Member, MemberSubscription, MemberPayment
from apps.leads.models import Lead, LeadNextMove
from common.enums import MembershipStatusEnum


def get_dashboard_summary(gym: Gym) -> Dict[str, Any]:
    """
    Computes high-performance management overview dashboard metrics:
    - Total Active Members & Total Members
    - Expiring Memberships (next 7 and 30 days)
    - New Leads this week
    - Pending Next Moves due today & Overdue Next Moves
    - Today's Scheduled Visits / Trials
    - Today's Revenue & Current Month's Revenue

    Optimized using consolidated conditional SQL aggregations (5 queries total).
    """
    today = timezone.localdate()
    start_of_week = today - timedelta(days=today.weekday())

    # 1. Member & Subscription metrics (2 queries total instead of 4)
    total_members = Member.objects.filter(gym=gym).count()

    sub_aggregates = MemberSubscription.objects.filter(
        member__gym=gym,
        membership_status=MembershipStatusEnum.ACTIVE,
    ).aggregate(
        total_active_members=Count("member_id", distinct=True),
        expiring_next_7_days=Count(
            "id",
            filter=Q(end_date__gte=today, end_date__lte=today + timedelta(days=7)),
        ),
        expiring_next_30_days=Count(
            "id",
            filter=Q(end_date__gte=today, end_date__lte=today + timedelta(days=30)),
        ),
    )
    total_active_members = sub_aggregates["total_active_members"] or 0
    expiring_next_7_days = sub_aggregates["expiring_next_7_days"] or 0
    expiring_next_30_days = sub_aggregates["expiring_next_30_days"] or 0

    # 2. Leads & CRM metrics (1 query for leads, 1 query for next moves instead of 4)
    lead_aggregates = Lead.objects.filter(gym=gym).aggregate(
        new_leads_this_week=Count("id", filter=Q(created_at__date__gte=start_of_week)),
        todays_scheduled_trials=Count("id", filter=Q(trial_booked_at__date=today)),
    )
    new_leads_this_week = lead_aggregates["new_leads_this_week"] or 0
    todays_scheduled_trials = lead_aggregates["todays_scheduled_trials"] or 0

    next_moves_aggregates = LeadNextMove.objects.filter(
        lead__gym=gym,
        is_completed=False,
    ).aggregate(
        pending_today=Count("id", filter=Q(scheduled_date=today)),
        overdue=Count("id", filter=Q(scheduled_date__lt=today)),
    )
    pending_next_moves_today = next_moves_aggregates["pending_today"] or 0
    overdue_next_moves = next_moves_aggregates["overdue"] or 0

    # 3. Revenue highlights (1 single query instead of 2)
    revenue_aggregates = MemberPayment.objects.filter(
        member_subscription__member__gym=gym,
        payment_date__year=today.year,
        payment_date__month=today.month,
    ).aggregate(
        todays_revenue=Sum("amount", filter=Q(payment_date=today)),
        current_month_revenue=Sum("amount"),
    )
    todays_revenue = revenue_aggregates["todays_revenue"] or Decimal("0.00")
    current_month_revenue = revenue_aggregates["current_month_revenue"] or Decimal("0.00")

    return {
        "gym_id": gym.id,
        "gym_name": gym.name,
        "generated_at": timezone.now(),
        "headline_metrics": {
            "total_members": total_members,
            "total_active_members": total_active_members,
            "expiring_memberships_next_7_days": expiring_next_7_days,
            "expiring_memberships_next_30_days": expiring_next_30_days,
            "new_leads_this_week": new_leads_this_week,
            "pending_next_moves_today": pending_next_moves_today,
            "overdue_next_moves": overdue_next_moves,
            "todays_scheduled_trials": todays_scheduled_trials,
            "todays_revenue": float(todays_revenue),
            "current_month_revenue": float(current_month_revenue),
        },
    }
