import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, Tuple, Optional

from django.utils import timezone
from django.db.models import Sum, Count, Q

from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from apps.members.models import Member, MemberSubscription, MemberPayment
from apps.leads.models import Lead, LeadNextMove
from apps.routines.models import MemberRoutine
from common.enums import (
    StaffStatus,
    MembershipStatusEnum,
    PaymentMethodEnum,
    LeadStageEnum,
)
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
        try:
            end_date = datetime.strptime(str(end_str).strip(), "%Y-%m-%d").date()
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid date format for 'end_date'. Expected YYYY-MM-DD.")
    else:
        end_date = today

    if start_str:
        try:
            start_date = datetime.strptime(str(start_str).strip(), "%Y-%m-%d").date()
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid date format for 'start_date'. Expected YYYY-MM-DD.")
    else:
        start_date = end_date - timedelta(days=default_days)

    if start_date > end_date:
        raise DomainValidationError("'start_date' cannot be after 'end_date'.")

    return start_date, end_date


def get_dashboard_summary(gym: Gym) -> Dict[str, Any]:
    """
    Computes high-performance management overview dashboard metrics:
    - Total Active Members & Total Members
    - Expiring Memberships (next 7 and 30 days)
    - New Leads this week
    - Pending Next Moves due today & Overdue Next Moves
    - Today's Scheduled Visits / Trials
    - Today's Revenue & Current Month's Revenue
    """
    today = timezone.localdate()
    start_of_week = today - timedelta(days=today.weekday())

    # 1. Member metrics
    total_members = Member.objects.filter(gym=gym).count()
    active_subscriptions_qs = MemberSubscription.objects.filter(
        member__gym=gym,
        membership_status=MembershipStatusEnum.ACTIVE,
    )
    total_active_members = active_subscriptions_qs.values("member_id").distinct().count()

    expiring_next_7_days = active_subscriptions_qs.filter(
        end_date__gte=today,
        end_date__lte=today + timedelta(days=7),
    ).count()

    expiring_next_30_days = active_subscriptions_qs.filter(
        end_date__gte=today,
        end_date__lte=today + timedelta(days=30),
    ).count()

    # 2. Leads & CRM metrics
    new_leads_this_week = Lead.objects.filter(
        gym=gym,
        created_at__date__gte=start_of_week,
    ).count()

    pending_next_moves_today = LeadNextMove.objects.filter(
        lead__gym=gym,
        scheduled_date=today,
        is_completed=False,
    ).count()

    overdue_next_moves = LeadNextMove.objects.filter(
        lead__gym=gym,
        scheduled_date__lt=today,
        is_completed=False,
    ).count()

    todays_scheduled_trials = Lead.objects.filter(
        gym=gym,
        trial_booked_at__date=today,
    ).count()

    # 3. Revenue highlights
    gym_payments_qs = MemberPayment.objects.filter(member_subscription__member__gym=gym)
    todays_revenue = gym_payments_qs.filter(payment_date=today).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")

    current_month_revenue = gym_payments_qs.filter(
        payment_date__year=today.year,
        payment_date__month=today.month,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

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


def get_revenue_report(gym: Gym, start_date: date, end_date: date) -> Dict[str, Any]:
    """
    Aggregates financial performance, payment methods, plan revenue distribution,
    and daily revenue collections over a date range.
    """
    payments_qs = MemberPayment.objects.filter(
        member_subscription__member__gym=gym,
        payment_date__range=(start_date, end_date),
    )

    aggregates = payments_qs.aggregate(
        total_revenue=Sum("amount"),
        total_transactions=Count("id"),
    )
    total_rev = aggregates["total_revenue"] or Decimal("0.00")
    total_tx = aggregates["total_transactions"] or 0

    # 1. Payment method breakdown
    method_data = (
        payments_qs.values("payment_method")
        .annotate(
            total_amount=Sum("amount"),
            transaction_count=Count("id"),
        )
        .order_by("-total_amount")
    )
    payment_methods = [
        {
            "payment_method": row["payment_method"],
            "total_amount": float(row["total_amount"] or Decimal("0.00")),
            "transaction_count": row["transaction_count"],
            "percentage": round(float((row["total_amount"] or Decimal("0.00")) / total_rev * 100), 2)
            if total_rev > 0
            else 0.0,
        }
        for row in method_data
    ]

    # 2. Plan revenue distribution
    plan_data = (
        payments_qs.values(
            "member_subscription__plan__id",
            "member_subscription__plan__name",
        )
        .annotate(
            total_amount=Sum("amount"),
            subscription_count=Count("member_subscription_id", distinct=True),
            transaction_count=Count("id"),
        )
        .order_by("-total_amount")
    )
    plan_distribution = [
        {
            "plan_id": row["member_subscription__plan__id"],
            "plan_name": row["member_subscription__plan__name"] or "Custom / Unspecified Plan",
            "total_amount": float(row["total_amount"] or Decimal("0.00")),
            "subscription_count": row["subscription_count"],
            "transaction_count": row["transaction_count"],
        }
        for row in plan_data
    ]

    # 3. Daily time-series breakdown
    daily_data = (
        payments_qs.values("payment_date")
        .annotate(
            daily_amount=Sum("amount"),
            transaction_count=Count("id"),
        )
        .order_by("payment_date")
    )
    daily_breakdown = [
        {
            "date": str(row["payment_date"]),
            "amount": float(row["daily_amount"] or Decimal("0.00")),
            "transaction_count": row["transaction_count"],
        }
        for row in daily_data
    ]

    return {
        "gym_id": gym.id,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "total_revenue": float(total_rev),
        "total_transactions": total_tx,
        "average_transaction_value": round(float(total_rev / total_tx), 2) if total_tx > 0 else 0.0,
        "payment_method_breakdown": payment_methods,
        "plan_distribution": plan_distribution,
        "daily_breakdown": daily_breakdown,
    }


def get_membership_growth_report(gym: Gym, start_date: date, end_date: date) -> Dict[str, Any]:
    """
    Computes member acquisition, new subscriptions, cancellations, net growth,
    and churn rate over a date range.
    """
    total_members = Member.objects.filter(gym=gym).count()
    active_subscriptions = MemberSubscription.objects.filter(
        member__gym=gym,
        membership_status=MembershipStatusEnum.ACTIVE,
    ).count()

    new_members = Member.objects.filter(
        gym=gym,
        created_at__date__range=(start_date, end_date),
    ).count()

    new_subscriptions = MemberSubscription.objects.filter(
        member__gym=gym,
        start_date__range=(start_date, end_date),
    ).count()

    cancelled_subscriptions = MemberSubscription.objects.filter(
        member__gym=gym,
        membership_status__in=[MembershipStatusEnum.CANCELLED, MembershipStatusEnum.EXPIRED],
        updated_at__date__range=(start_date, end_date),
    ).count()

    net_growth = new_subscriptions - cancelled_subscriptions
    churn_rate = (
        round((cancelled_subscriptions / active_subscriptions * 100), 2)
        if active_subscriptions > 0
        else 0.0
    )

    # Subscriptions status breakdown
    status_data = (
        MemberSubscription.objects.filter(member__gym=gym)
        .values("membership_status")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    status_breakdown = [
        {"status": row["membership_status"], "count": row["count"]}
        for row in status_data
    ]

    # Active subscriptions plan breakdown
    plan_data = (
        MemberSubscription.objects.filter(
            member__gym=gym,
            membership_status=MembershipStatusEnum.ACTIVE,
        )
        .values("plan__id", "plan__name")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    plan_breakdown = [
        {
            "plan_id": row["plan__id"],
            "plan_name": row["plan__name"] or "Custom Plan",
            "active_subscriptions": row["count"],
        }
        for row in plan_data
    ]

    return {
        "gym_id": gym.id,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "total_members": total_members,
        "active_subscriptions": active_subscriptions,
        "new_members_in_period": new_members,
        "new_subscriptions_in_period": new_subscriptions,
        "cancelled_subscriptions_in_period": cancelled_subscriptions,
        "net_growth": net_growth,
        "churn_rate_percentage": churn_rate,
        "status_breakdown": status_breakdown,
        "plan_breakdown": plan_breakdown,
    }


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
    total_leads = leads_qs.count()

    # 1. Pipeline stage breakdown
    stage_data = (
        leads_qs.values("stage")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    stage_counts = {row["stage"]: row["count"] for row in stage_data}

    new_count = stage_counts.get(LeadStageEnum.NEW, 0)
    contacted_count = stage_counts.get(LeadStageEnum.CONTACTED, 0)
    trial_count = (
        stage_counts.get(LeadStageEnum.VISIT_TRIAL_BOOKED, 0)
        + leads_qs.filter(trial_booked_at__isnull=False).exclude(stage=LeadStageEnum.VISIT_TRIAL_BOOKED).count()
    )
    joined_count = stage_counts.get(LeadStageEnum.JOINED, 0)
    lost_count = stage_counts.get(LeadStageEnum.NOT_JOINING, 0)

    # Conversion rates with division-by-zero protection
    trial_booking_rate = round((trial_count / total_leads * 100), 2) if total_leads > 0 else 0.0
    trial_to_join_rate = round((joined_count / trial_count * 100), 2) if trial_count > 0 else 0.0
    overall_conversion_rate = round((joined_count / total_leads * 100), 2) if total_leads > 0 else 0.0
    drop_off_rate = round((lost_count / total_leads * 100), 2) if total_leads > 0 else 0.0

    # 2. Lost reason distribution
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


def get_trainer_workload_report(gym: Gym) -> Dict[str, Any]:
    """
    Computes trainer client allocation and prescribed workout workload:
    - Active assigned members per trainer
    - Active routines and total routines prescribed
    - Staff assignment status and role details
    """
    staff_assignments = (
        GymStaffAssignment.objects.filter(gym=gym, status=StaffStatus.ACTIVE)
        .select_related("user", "role")
        .order_by("user__first_name", "user__last_name")
    )

    trainer_workloads = []
    total_assigned_members_all = 0
    total_active_routines_all = 0

    for assignment in staff_assignments:
        u = assignment.user
        trainer_name = f"{u.first_name} {u.last_name}".strip() or u.email

        assigned_members_count = Member.objects.filter(
            gym=gym,
            assigned_trainer=assignment,
        ).count()

        active_routines_count = MemberRoutine.objects.filter(
            member__gym=gym,
            prescribed_by_staff=assignment,
            is_active=True,
        ).count()

        total_routines_count = MemberRoutine.objects.filter(
            member__gym=gym,
            prescribed_by_staff=assignment,
        ).count()

        total_assigned_members_all += assigned_members_count
        total_active_routines_all += active_routines_count

        trainer_workloads.append({
            "staff_assignment_id": assignment.id,
            "user_id": u.id,
            "name": trainer_name,
            "email": u.email,
            "role_name": assignment.role.name if assignment.role else "No Role",
            "role_slug": assignment.role.slug if assignment.role else None,
            "assigned_members_count": assigned_members_count,
            "active_routines_count": active_routines_count,
            "total_routines_prescribed": total_routines_count,
        })

    trainer_count = len(trainer_workloads)
    avg_members = round(total_assigned_members_all / trainer_count, 1) if trainer_count > 0 else 0.0

    return {
        "gym_id": gym.id,
        "gym_name": gym.name,
        "total_active_staff": trainer_count,
        "total_assigned_members": total_assigned_members_all,
        "total_active_routines": total_active_routines_all,
        "average_members_per_trainer": avg_members,
        "trainers": trainer_workloads,
    }
