import uuid
from typing import Optional, Dict, Any, Generator
from django.db.models import QuerySet, Q, Prefetch, Count, Sum
from apps.gyms.models import Gym
from apps.members.models import (
    Member,
    MemberSubscription,
    MemberPayment,
    MemberExtraAmenities,
)
from common.enums import (
    MemberJoiningStatus,
    MembershipStatusEnum,
    PaymentStatusEnum,
)
from common.exceptions import ResourceNotFoundError


def list_gym_members(
    gym: Gym,
    joining_status: Optional[str] = None,
    membership_status: Optional[str] = None,
    payment_status: Optional[str] = None,
    assigned_trainer_id: Optional[uuid.UUID] = None,
    search: Optional[str] = None,
) -> QuerySet[Member]:
    """
    Retrieves the gym member directory with preloaded active subscriptions,
    assigned trainers, and projection-optimized columns.
    Eliminates N+1 queries.
    """
    sub_prefetch = Prefetch(
        "subscriptions",
        queryset=MemberSubscription.objects.select_related("plan").order_by("-created_at"),
    )

    qs = (
        Member.objects.filter(gym=gym)
        .only(
            "id",
            "gym_id",
            "user_id",
            "assigned_trainer_id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "profile_photo_url",
            "joining_status",
            "created_at",
            "updated_at",
        )
        .select_related("assigned_trainer__user")
        .prefetch_related(sub_prefetch)
        .order_by("-created_at")
    )

    if joining_status is not None:
        status_clean = str(joining_status).lower().strip()
        if status_clean:
            qs = qs.filter(joining_status=status_clean)

    if membership_status is not None:
        ms_clean = str(membership_status).lower().strip()
        if ms_clean:
            qs = qs.filter(subscriptions__membership_status=ms_clean)

    if payment_status is not None:
        ps_clean = str(payment_status).lower().strip()
        if ps_clean:
            qs = qs.filter(subscriptions__payment_status=ps_clean)

    if assigned_trainer_id is not None:
        qs = qs.filter(assigned_trainer_id=assigned_trainer_id)

    if search is not None:
        search_term = str(search).strip()
        if search_term:
            qs = qs.filter(
                Q(first_name__icontains=search_term)
                | Q(last_name__icontains=search_term)
                | Q(email__icontains=search_term)
                | Q(phone__icontains=search_term)
            )

    return qs.distinct()


def get_member_detail(
    member_id: uuid.UUID,
    gym: Gym,
) -> Member:
    """
    Retrieves a complete member dossier including subscription history,
    bundled extra amenities, payment transaction ledger, and notes.
    """
    extra_amenity_prefetch = Prefetch(
        "extra_amenities",
        queryset=MemberExtraAmenities.objects.select_related("gym_amenity__amenity"),
    )
    payment_prefetch = Prefetch(
        "payments",
        queryset=MemberPayment.objects.order_by("-payment_date", "-created_at"),
    )
    sub_prefetch = Prefetch(
        "subscriptions",
        queryset=MemberSubscription.objects.select_related("plan")
        .prefetch_related(extra_amenity_prefetch, payment_prefetch)
        .order_by("-created_at"),
    )

    try:
        return (
            Member.objects.filter(id=member_id, gym=gym)
            .select_related("gym", "user", "assigned_trainer__user")
            .prefetch_related(sub_prefetch)
            .get()
        )
    except Member.DoesNotExist:
        raise ResourceNotFoundError(f"Member '{member_id}' not found.")


def get_gym_member_metrics(gym: Gym) -> Dict[str, Any]:
    """
    Calculates member and subscription metrics at the database level in a single query.
    """
    member_aggregates = Member.objects.filter(gym=gym).aggregate(
        total_members=Count("id", distinct=True),
        joined_members=Count("id", filter=Q(joining_status=MemberJoiningStatus.JOINED), distinct=True),
        invited_members=Count("id", filter=Q(joining_status=MemberJoiningStatus.SENT_INVITATION), distinct=True),
    )

    sub_aggregates = MemberSubscription.objects.filter(member__gym=gym).aggregate(
        active_subscriptions=Count("id", filter=Q(membership_status=MembershipStatusEnum.ACTIVE), distinct=True),
        unpaid_subscriptions=Count("id", filter=Q(payment_status=PaymentStatusEnum.UNPAID), distinct=True),
        fully_paid_subscriptions=Count("id", filter=Q(payment_status=PaymentStatusEnum.FULLY_PAID), distinct=True),
    )

    revenue_aggregates = MemberPayment.objects.filter(member_subscription__member__gym=gym).aggregate(
        total_revenue=Sum("amount"),
    )

    return {
        **member_aggregates,
        **sub_aggregates,
        "total_revenue": revenue_aggregates["total_revenue"] or 0.0,
    }


def stream_gym_members(gym: Gym, chunk_size: int = 500) -> Generator[Member, None, None]:
    """
    Yields members using QuerySet.iterator() to stream large directories
    without materializing entire querysets in memory.
    """
    qs = (
        Member.objects.filter(gym=gym)
        .only("id", "first_name", "last_name", "email", "phone", "joining_status", "created_at")
        .order_by("-created_at")
    )
    for member in qs.iterator(chunk_size=chunk_size):
        yield member
