import uuid
from decimal import Decimal
from typing import Optional, Dict, Any, Generator
from django.db import connection
from django.db.models import QuerySet, Q, Prefetch
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
        queryset=(
            MemberSubscription.objects.select_related("plan")
            .only(
                "id",
                "member_id",
                "membership_status",
                "payment_status",
                "end_date",
                "created_at",
                "plan__id",
                "plan__name",
            )
            .order_by("-created_at")
        ),
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
            "assigned_trainer__id",
            "assigned_trainer__gym_id",
            "assigned_trainer__user_id",
            "assigned_trainer__user__id",
            "assigned_trainer__user__first_name",
            "assigned_trainer__user__last_name",
            "assigned_trainer__user__email",
        )
        .select_related("assigned_trainer__user")
        .prefetch_related(sub_prefetch)
        .order_by("-created_at")
    )

    if joining_status is not None:
        status_clean = str(joining_status).lower().strip()
        if status_clean:
            qs = qs.filter(joining_status=status_clean)

    has_reverse_filter = False
    if membership_status is not None:
        ms_clean = str(membership_status).lower().strip()
        if ms_clean:
            qs = qs.filter(subscriptions__membership_status=ms_clean)
            has_reverse_filter = True

    if payment_status is not None:
        ps_clean = str(payment_status).lower().strip()
        if ps_clean:
            qs = qs.filter(subscriptions__payment_status=ps_clean)
            has_reverse_filter = True

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

    if has_reverse_filter:
        return qs.distinct()
    return qs


def get_member_detail(
    member_id: uuid.UUID,
    gym: Gym,
) -> Member:
    """
    Retrieves a complete member dossier including subscription history,
    bundled extra amenities, payment transaction ledger, and notes.
    Optimized with precise column projection to eliminate over-fetching.
    """
    extra_amenity_prefetch = Prefetch(
        "extra_amenities",
        queryset=(
            MemberExtraAmenities.objects.select_related("gym_amenity__amenity")
            .only(
                "id",
                "member_subscription_id",
                "gym_amenity_id",
                "extra_fee",
                "is_active",
                "created_at",
                "gym_amenity__id",
                "gym_amenity__amenity_id",
                "gym_amenity__amenity__name",
                "gym_amenity__amenity__group_name",
            )
        ),
    )
    payment_prefetch = Prefetch(
        "payments",
        queryset=(
            MemberPayment.objects.only(
                "id",
                "member_subscription_id",
                "amount",
                "payment_method",
                "payment_date",
                "is_initial_payment",
                "notes",
                "created_at",
            )
            .order_by("-payment_date", "-created_at")
        ),
    )
    sub_prefetch = Prefetch(
        "subscriptions",
        queryset=(
            MemberSubscription.objects.select_related("plan")
            .only(
                "id",
                "member_id",
                "plan_id",
                "membership_status",
                "payment_status",
                "start_date",
                "end_date",
                "total_sessions",
                "remaining_sessions",
                "created_at",
                "updated_at",
                "plan__id",
                "plan__name",
                "plan__plan_type",
                "plan__price",
                "plan__joining_fee",
            )
            .prefetch_related(extra_amenity_prefetch, payment_prefetch)
            .order_by("-created_at")
        ),
    )

    try:
        return (
            Member.objects.filter(id=member_id, gym=gym)
            .select_related("gym", "user", "assigned_trainer__user")
            .only(
                "id", "gym_id", "user_id", "assigned_trainer_id",
                "first_name", "last_name", "email", "phone",
                "profile_photo_url", "address", "city", "country",
                "date_of_birth", "sex", "nationality",
                "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relationship",
                "joining_status", "invitation_sent_at", "internal_notes",
                "created_at", "updated_at",
                "gym__id", "gym__name",
                "user__id", "user__email", "user__first_name", "user__last_name",
                "assigned_trainer__id", "assigned_trainer__user_id",
                "assigned_trainer__user__id", "assigned_trainer__user__first_name",
                "assigned_trainer__user__last_name", "assigned_trainer__user__email",
            )
            .prefetch_related(sub_prefetch)
            .get()
        )
    except Member.DoesNotExist:
        raise ResourceNotFoundError(f"Member '{member_id}' not found.")


def get_gym_member_metrics(gym: Gym) -> Dict[str, Any]:
    """
    Calculates member and subscription metrics at the database level in a single unified query.
    Reduces database round-trips from 3 to 1 (66.7% query reduction).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM members WHERE gym_id = %s) AS total_members,
                (SELECT COUNT(*) FROM members WHERE gym_id = %s AND joining_status = %s) AS joined_members,
                (SELECT COUNT(*) FROM members WHERE gym_id = %s AND joining_status = %s) AS invited_members,
                (SELECT COUNT(*) FROM member_subscriptions ms INNER JOIN members m ON ms.member_id = m.id WHERE m.gym_id = %s AND ms.membership_status = %s) AS active_subscriptions,
                (SELECT COUNT(*) FROM member_subscriptions ms INNER JOIN members m ON ms.member_id = m.id WHERE m.gym_id = %s AND ms.payment_status = %s) AS unpaid_subscriptions,
                (SELECT COUNT(*) FROM member_subscriptions ms INNER JOIN members m ON ms.member_id = m.id WHERE m.gym_id = %s AND ms.payment_status = %s) AS fully_paid_subscriptions,
                (SELECT COALESCE(SUM(mp.amount), 0.00) FROM member_payments mp INNER JOIN member_subscriptions ms ON mp.member_subscription_id = ms.id INNER JOIN members m ON ms.member_id = m.id WHERE m.gym_id = %s) AS total_revenue
            """,
            [
                gym.id,
                gym.id, MemberJoiningStatus.JOINED,
                gym.id, MemberJoiningStatus.SENT_INVITATION,
                gym.id, MembershipStatusEnum.ACTIVE,
                gym.id, PaymentStatusEnum.UNPAID,
                gym.id, PaymentStatusEnum.FULLY_PAID,
                gym.id,
            ],
        )
        row = cursor.fetchone()

    return {
        "total_members": row[0] or 0,
        "joined_members": row[1] or 0,
        "invited_members": row[2] or 0,
        "active_subscriptions": row[3] or 0,
        "unpaid_subscriptions": row[4] or 0,
        "fully_paid_subscriptions": row[5] or 0,
        "total_revenue": float(row[6]) if row[6] is not None else 0.0,
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
