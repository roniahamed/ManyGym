from datetime import date
from typing import Dict, Any
from django.db.models import Count, Q

from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from apps.members.models import Member, MemberSubscription
from apps.routines.models import MemberRoutine
from common.enums import StaffStatus, MembershipStatusEnum


def get_membership_growth_report(gym: Gym, start_date: date, end_date: date) -> Dict[str, Any]:
    """
    Computes member acquisition, new subscriptions, cancellations, net growth,
    and churn rate over a date range.
    Consolidates count queries into 2 conditional SQL aggregations.
    """
    # 1. Consolidated Member aggregates (1 query instead of 2)
    member_aggregates = Member.objects.filter(gym=gym).aggregate(
        total_members=Count("id"),
        new_members=Count("id", filter=Q(created_at__date__range=(start_date, end_date))),
    )
    total_members = member_aggregates["total_members"] or 0
    new_members = member_aggregates["new_members"] or 0

    # 2. Consolidated Subscription aggregates (1 query instead of 3)
    sub_aggregates = MemberSubscription.objects.filter(member__gym=gym).aggregate(
        active_subscriptions=Count("id", filter=Q(membership_status=MembershipStatusEnum.ACTIVE)),
        new_subscriptions=Count("id", filter=Q(start_date__range=(start_date, end_date))),
        cancelled_subscriptions=Count(
            "id",
            filter=Q(
                membership_status__in=[MembershipStatusEnum.CANCELLED, MembershipStatusEnum.EXPIRED],
                updated_at__date__range=(start_date, end_date),
            ),
        ),
    )
    active_subscriptions = sub_aggregates["active_subscriptions"] or 0
    new_subscriptions = sub_aggregates["new_subscriptions"] or 0
    cancelled_subscriptions = sub_aggregates["cancelled_subscriptions"] or 0

    net_growth = new_subscriptions - cancelled_subscriptions
    churn_rate = (
        round((cancelled_subscriptions / active_subscriptions * 100), 2)
        if active_subscriptions > 0
        else 0.0
    )

    if total_members == 0:
        status_breakdown = []
        plan_breakdown = []
    else:
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

        # Active subscriptions plan breakdown (skip query if no active subscriptions)
        if active_subscriptions == 0:
            plan_breakdown = []
        else:
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


def get_trainer_workload_report(gym: Gym) -> Dict[str, Any]:
    """
    Computes trainer client allocation and prescribed workout workload:
    - Active assigned members per trainer
    - Active routines and total routines prescribed
    - Staff assignment status and role details

    Eliminates N+1 queries by batch-aggregating member assignments and
    routine metrics across all active trainers in exactly 3 database queries.
    """
    staff_assignments = list(
        GymStaffAssignment.objects.filter(gym=gym, status=StaffStatus.ACTIVE)
        .select_related("user", "role")
        .only(
            "id",
            "gym_id",
            "status",
            "user__id",
            "user__first_name",
            "user__last_name",
            "user__email",
            "role__id",
            "role__name",
            "role__slug",
        )
        .order_by("user__first_name", "user__last_name")
    )

    if not staff_assignments:
        return {
            "gym_id": gym.id,
            "gym_name": gym.name,
            "total_active_staff": 0,
            "total_assigned_members": 0,
            "total_active_routines": 0,
            "average_members_per_trainer": 0.0,
            "trainers": [],
        }

    staff_ids = [s.id for s in staff_assignments]

    # Batch 1: assigned members per trainer (1 query)
    assigned_counts = dict(
        Member.objects.filter(gym=gym, assigned_trainer_id__in=staff_ids)
        .values("assigned_trainer_id")
        .annotate(cnt=Count("id"))
        .values_list("assigned_trainer_id", "cnt")
    )

    # Batch 2: routine counts (active & total) per trainer (1 query via conditional aggregation)
    routine_aggregates = (
        MemberRoutine.objects.filter(member__gym=gym, prescribed_by_staff_id__in=staff_ids)
        .values("prescribed_by_staff_id")
        .annotate(
            active_cnt=Count("id", filter=Q(is_active=True)),
            total_cnt=Count("id"),
        )
        .values_list("prescribed_by_staff_id", "active_cnt", "total_cnt")
    )
    routine_counts = {row[0]: (row[1], row[2]) for row in routine_aggregates}

    trainer_workloads = []
    total_assigned_members_all = 0
    total_active_routines_all = 0

    for assignment in staff_assignments:
        u = assignment.user
        trainer_name = f"{u.first_name} {u.last_name}".strip() or u.email

        assigned_members_count = assigned_counts.get(assignment.id, 0)
        active_routines_count, total_routines_count = routine_counts.get(assignment.id, (0, 0))

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
