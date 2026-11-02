from datetime import date
from decimal import Decimal
from typing import Dict, Any
from django.db.models import Sum, Count

from apps.gyms.models import Gym
from apps.members.models import MemberPayment


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

    # Early exit for zero-transaction windows (saves 3 queries)
    if total_tx == 0:
        return {
            "gym_id": gym.id,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "total_revenue": 0.0,
            "total_transactions": 0,
            "average_transaction_value": 0.0,
            "payment_method_breakdown": [],
            "plan_distribution": [],
            "daily_breakdown": [],
        }

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
