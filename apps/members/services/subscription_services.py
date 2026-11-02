import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.mail import send_mail
from django.db import connection, transaction
from django.utils import timezone

from apps.gyms.models import Gym
from apps.amenities.models import GymAmenity
from apps.memberships.models import MembershipPlan
from apps.members.models import (
    Member,
    MemberSubscription,
    MemberExtraAmenities,
)
from common.enums import (
    MembershipStatusEnum,
    PaymentStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
)
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
)

logger = logging.getLogger(__name__)


@transaction.atomic
def create_member_subscription(
    member: Member,
    plan: MembershipPlan,
    start_date: date,
    end_date: Optional[date] = None,
    extra_amenity_ids: Optional[List[uuid.UUID]] = None,
    initial_payment_amount: Optional[Decimal] = None,
    initial_payment_method: Optional[str] = None,
    initial_payment_date: Optional[date] = None,
    initial_payment_notes: Optional[str] = None,
) -> MemberSubscription:
    """
    Creates a membership subscription, computes end date for time-based plans,
    attaches extra amenities, and logs initial payment.
    """
    if plan.gym_id != member.gym_id:
        raise DomainValidationError("Selected plan does not belong to the member's gym.")

    calculated_end_date = end_date
    total_sessions = None
    remaining_sessions = None

    if plan.plan_type == PlanTypeEnum.TIME_BASED:
        val = plan.duration_value
        unit = plan.duration_unit
        if unit == DurationUnitEnum.DAY:
            calculated_end_date = start_date + timedelta(days=val)
        elif unit == DurationUnitEnum.WEEK:
            calculated_end_date = start_date + timedelta(weeks=val)
        elif unit == DurationUnitEnum.MONTH:
            calculated_end_date = start_date + relativedelta(months=val)
        else:
            calculated_end_date = start_date + timedelta(days=val)
    elif plan.plan_type == PlanTypeEnum.SESSION_BASED:
        if not calculated_end_date:
            raise DomainValidationError("An expiry end date is required for session-based plans.")
        total_sessions = plan.duration_value
        remaining_sessions = plan.duration_value

    if calculated_end_date and calculated_end_date < start_date:
        raise DomainValidationError("Subscription end date cannot be prior to start date.")

    # Determine status based on start_date
    today = timezone.now().date()
    sub_status = MembershipStatusEnum.ACTIVE if start_date <= today else MembershipStatusEnum.SCHEDULED

    subscription = MemberSubscription.objects.create(
        member=member,
        plan=plan,
        membership_status=sub_status,
        payment_status=PaymentStatusEnum.UNPAID,
        start_date=start_date,
        end_date=calculated_end_date,
        total_sessions=total_sessions,
        remaining_sessions=remaining_sessions,
    )

    # Attach extra paid amenities if provided
    if extra_amenity_ids:
        attach_extra_amenities(subscription=subscription, amenity_ids=extra_amenity_ids)

    # Record initial payment if provided
    if initial_payment_amount is not None and initial_payment_amount > Decimal("0.00"):
        if not initial_payment_method:
            raise DomainValidationError("Payment method is required when initial payment amount is provided.")
        from apps.members.services.payment_services import record_member_payment
        record_member_payment(
            subscription=subscription,
            amount=initial_payment_amount,
            payment_method=initial_payment_method,
            payment_date=initial_payment_date or start_date,
            is_initial_payment=True,
            notes=initial_payment_notes,
        )

    return subscription


@transaction.atomic
def attach_extra_amenities(
    subscription: MemberSubscription,
    amenity_ids: List[uuid.UUID],
) -> List[MemberExtraAmenities]:
    """
    Attaches extra paid amenities to an active member subscription.
    """
    if not amenity_ids:
        return []

    gym = subscription.member.gym
    valid_amenities = GymAmenity.objects.filter(
        id__in=amenity_ids,
        gym=gym,
    ).select_related("amenity")

    valid_map = {a.id: a for a in valid_amenities}
    invalid_ids = [aid for aid in amenity_ids if aid not in valid_map]
    if invalid_ids:
        raise DomainValidationError(f"The following amenities do not belong to this gym: {invalid_ids}")

    # Check that each amenity is a paid amenity
    for a in valid_amenities:
        if not a.is_paid:
            raise DomainValidationError(f"Amenity '{a.amenity.name}' is free and cannot be added as an extra paid amenity.")

    created = []
    seen = set()
    for aid in amenity_ids:
        if aid not in seen:
            seen.add(aid)
            amenity = valid_map[aid]
            obj, _ = MemberExtraAmenities.objects.get_or_create(
                member_subscription=subscription,
                gym_amenity=amenity,
                defaults={"extra_fee": amenity.default_price, "is_active": True},
            )
            created.append(obj)

    recalculate_subscription_payment_status(subscription)
    return created


def recalculate_subscription_payment_status(subscription: MemberSubscription) -> None:
    """
    Calculates total cost (plan price + joining fee + extra amenities) vs total paid,
    and updates subscription payment_status using a single aggregated SQL lookup and selective update_fields.
    """
    plan = subscription.plan
    base_cost = plan.price + plan.joining_fee

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COALESCE(SUM(extra_fee), 0.00) FROM member_extra_amenities WHERE member_subscription_id = %s AND is_active = true),
                (SELECT COALESCE(SUM(amount), 0.00) FROM member_payments WHERE member_subscription_id = %s)
            """,
            [subscription.id, subscription.id],
        )
        row = cursor.fetchone()
        extra_cost = Decimal(str(row[0] or 0.00))
        total_paid = Decimal(str(row[1] or 0.00))

    total_cost = base_cost + extra_cost

    if total_paid >= total_cost:
        new_status = PaymentStatusEnum.FULLY_PAID
    elif total_paid > Decimal("0.00"):
        new_status = PaymentStatusEnum.PARTIALLY_PAID
    else:
        new_status = PaymentStatusEnum.UNPAID

    if subscription.payment_status != new_status:
        subscription.payment_status = new_status
        subscription.save(update_fields=["payment_status", "updated_at"])


@transaction.atomic
def transition_membership_status(
    subscription_id: uuid.UUID,
    gym: Gym,
    new_status: str,
) -> MemberSubscription:
    """
    Transitions subscription state: active <-> paused, active/paused -> cancelled.
    """
    try:
        sub = MemberSubscription.objects.select_related("member").get(
            id=subscription_id,
            member__gym=gym,
        )
    except MemberSubscription.DoesNotExist:
        raise ResourceNotFoundError(f"Member subscription '{subscription_id}' not found.")

    if new_status not in MembershipStatusEnum.values:
        raise DomainValidationError(f"Invalid membership status '{new_status}'.")

    current = sub.membership_status
    if current == new_status:
        return sub

    # Validate allowed transitions
    allowed_transitions = {
        MembershipStatusEnum.SCHEDULED: [MembershipStatusEnum.ACTIVE, MembershipStatusEnum.CANCELLED],
        MembershipStatusEnum.ACTIVE: [MembershipStatusEnum.PAUSED, MembershipStatusEnum.CANCELLED, MembershipStatusEnum.EXPIRED],
        MembershipStatusEnum.PAUSED: [MembershipStatusEnum.ACTIVE, MembershipStatusEnum.CANCELLED],
        MembershipStatusEnum.EXPIRED: [MembershipStatusEnum.CANCELLED],
        MembershipStatusEnum.CANCELLED: [],  # terminal
    }

    if new_status not in allowed_transitions.get(current, []):
        raise DomainValidationError(f"Cannot transition membership status from '{current}' to '{new_status}'.")

    sub.membership_status = new_status
    sub.save(update_fields=["membership_status", "updated_at"])
    return sub


@transaction.atomic
def reconcile_expired_subscriptions() -> int:
    """
    Atomically updates active subscriptions where end_date < today to EXPIRED.
    Also activates SCHEDULED subscriptions where start_date <= today and end_date >= today.
    Returns total number of subscriptions transitioned to EXPIRED.
    """
    today = timezone.localdate()
    expired_count = (
        MemberSubscription.objects.filter(
            membership_status=MembershipStatusEnum.ACTIVE,
            end_date__lt=today,
        )
        .order_by()
        .update(membership_status=MembershipStatusEnum.EXPIRED)
    )

    MemberSubscription.objects.filter(
        membership_status=MembershipStatusEnum.SCHEDULED,
        start_date__lte=today,
        end_date__gte=today,
    ).order_by().update(membership_status=MembershipStatusEnum.ACTIVE)

    logger.info(f"Reconciled {expired_count} expired member subscriptions as of {today}.")
    return expired_count


def send_subscription_expiry_reminders() -> int:
    """
    Queries active subscriptions expiring in 7 days and 1 day,
    and dispatches reminder notifications.
    Optimized with precise column projection (.only), un-ordered queryset,
    and memory-efficient chunk streaming (.iterator).
    Returns count of notifications dispatched.
    """
    today = timezone.localdate()
    target_dates = [today + timedelta(days=7), today + timedelta(days=1)]
    expiring_subs = (
        MemberSubscription.objects.filter(
            membership_status=MembershipStatusEnum.ACTIVE,
            end_date__in=target_dates,
        )
        .select_related("member", "plan", "member__gym")
        .only(
            "id",
            "end_date",
            "membership_status",
            "member_id",
            "plan_id",
            "member__id",
            "member__first_name",
            "member__email",
            "member__gym_id",
            "plan__id",
            "plan__name",
            "member__gym__id",
            "member__gym__name",
        )
        .order_by()
        .iterator(chunk_size=1000)
    )

    dispatched = 0
    for sub in expiring_subs:
        days_left = (sub.end_date - today).days
        member = sub.member
        gym = member.gym
        if not member.email:
            continue

        day_str = "days" if days_left > 1 else "day"
        subject = f"Reminder: Your {sub.plan.name} membership at {gym.name} expires in {days_left} {day_str}"
        lines = [
            f"Hi {member.first_name},",
            "",
            f"This is a friendly reminder that your {sub.plan.name} membership at {gym.name} is set to expire on {sub.end_date} ({days_left} {day_str} remaining).",
            "",
            "Please visit the gym reception or renew your subscription to maintain uninterrupted access.",
            "",
            "Best regards,",
            f"The {gym.name} Team",
        ]
        message = chr(10).join(lines)
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[member.email],
                fail_silently=False,
            )
            dispatched += 1
        except Exception as exc:
            logger.error(f"Failed to dispatch subscription expiry reminder to {member.email}: {exc}")

    logger.info(f"Dispatched {dispatched} subscription expiry reminder emails on {today}.")
    return dispatched
