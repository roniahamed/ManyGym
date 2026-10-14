import uuid
import secrets
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Any
from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.core.exceptions import ValidationError

from apps.gyms.models import Gym
from apps.users.models import User
from apps.access_control.models import GymStaffAssignment
from apps.amenities.models import GymAmenity
from apps.memberships.models import MembershipPlan
from apps.members.models import (
    Member,
    MemberSubscription,
    MemberExtraAmenities,
    MemberPayment,
)
from apps.members.tasks import send_member_invitation_email
from common.enums import (
    MemberJoiningStatus,
    MembershipStatusEnum,
    PaymentStatusEnum,
    PaymentMethodEnum,
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
)
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    ResourceConflictError,
)


@transaction.atomic
def create_member(
    gym: Gym,
    first_name: str,
    last_name: str,
    email: str,
    phone: Optional[str] = None,
    profile_photo_url: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    date_of_birth: Optional[date] = None,
    sex: Optional[str] = None,
    nationality: Optional[str] = None,
    emergency_contact_name: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
    emergency_contact_relationship: Optional[str] = None,
    assigned_trainer_id: Optional[uuid.UUID] = None,
    internal_notes: Optional[str] = None,
    plan_id: Optional[uuid.UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    extra_amenity_ids: Optional[List[uuid.UUID]] = None,
    initial_payment_amount: Optional[Decimal] = None,
    initial_payment_method: Optional[str] = None,
    initial_payment_date: Optional[date] = None,
    initial_payment_notes: Optional[str] = None,
) -> Member:
    """
    Creates a new gym member record with onboarding invitation and optional initial subscription.
    """
    # 1. Clean and validate inputs
    fn_clean = first_name.strip() if first_name else ""
    ln_clean = last_name.strip() if last_name else ""
    email_clean = email.strip().lower() if email else ""

    if not fn_clean:
        raise DomainValidationError("Member first name is required.")
    if not ln_clean:
        raise DomainValidationError("Member last name is required.")
    if not email_clean or "@" not in email_clean:
        raise DomainValidationError("A valid member email address is required.")

    if Member.objects.filter(gym=gym, email=email_clean).exists():
        raise ResourceConflictError(f"A member with email '{email_clean}' already exists in this gym.")

    # 2. Validate trainer assignment if provided
    trainer_assignment = None
    if assigned_trainer_id:
        try:
            trainer_assignment = GymStaffAssignment.objects.select_related("user").get(
                id=assigned_trainer_id,
                gym=gym,
            )
        except GymStaffAssignment.DoesNotExist:
            raise DomainValidationError("Assigned trainer does not exist or is not a staff member of this gym.")

    # 3. Generate onboarding invitation token
    invitation_token = secrets.token_urlsafe(32)

    member = Member(
        gym=gym,
        first_name=fn_clean,
        last_name=ln_clean,
        email=email_clean,
        phone=phone.strip() if phone else None,
        profile_photo_url=profile_photo_url.strip() if profile_photo_url else None,
        address=address.strip() if address else None,
        city=city.strip() if city else None,
        country=country.strip() if country else None,
        date_of_birth=date_of_birth,
        sex=sex.strip() if sex else None,
        nationality=nationality.strip() if nationality else None,
        emergency_contact_name=emergency_contact_name.strip() if emergency_contact_name else None,
        emergency_contact_phone=emergency_contact_phone.strip() if emergency_contact_phone else None,
        emergency_contact_relationship=emergency_contact_relationship.strip() if emergency_contact_relationship else None,
        assigned_trainer=trainer_assignment,
        internal_notes=internal_notes.strip() if internal_notes else None,
        joining_status=MemberJoiningStatus.SENT_INVITATION,
        invitation_token=invitation_token,
        invitation_sent_at=timezone.now(),
    )
    try:
        member.full_clean()
        member.save()
    except ValidationError as exc:
        raise DomainValidationError(str(exc))

    # 4. Initialize initial subscription if plan_id is provided
    if plan_id:
        try:
            plan = MembershipPlan.objects.get(id=plan_id, gym=gym)
        except MembershipPlan.DoesNotExist:
            raise DomainValidationError("The selected membership plan does not exist in this gym.")

        sub_start_date = start_date or timezone.now().date()
        create_member_subscription(
            member=member,
            plan=plan,
            start_date=sub_start_date,
            end_date=end_date,
            extra_amenity_ids=extra_amenity_ids,
            initial_payment_amount=initial_payment_amount,
            initial_payment_method=initial_payment_method,
            initial_payment_date=initial_payment_date or sub_start_date,
            initial_payment_notes=initial_payment_notes,
        )

    # 5. Dispatch async invitation email
    send_member_invitation_email.delay(
        member_id=str(member.id),
        email=member.email,
        first_name=member.first_name,
        gym_name=gym.name,
        token=invitation_token,
    )

    return member


@transaction.atomic
def resend_member_invitation(member_id: uuid.UUID, gym: Gym) -> Member:
    """
    Regenerates invitation token and re-dispatches onboarding confirmation email.
    """
    try:
        member = Member.objects.get(id=member_id, gym=gym)
    except Member.DoesNotExist:
        raise ResourceNotFoundError(f"Member '{member_id}' not found.")

    if member.joining_status == MemberJoiningStatus.JOINED:
        raise DomainValidationError("Member has already completed onboarding and activated their account.")

    new_token = secrets.token_urlsafe(32)
    member.invitation_token = new_token
    member.invitation_sent_at = timezone.now()
    member.save(update_fields=["invitation_token", "invitation_sent_at", "updated_at"])

    send_member_invitation_email.delay(
        member_id=str(member.id),
        email=member.email,
        first_name=member.first_name,
        gym_name=gym.name,
        token=new_token,
    )
    return member


@transaction.atomic
def accept_member_invitation(token: str, user: User) -> Member:
    """
    Validates invitation token, links user account, and transitions status to 'joined'.
    """
    token_clean = token.strip() if token else ""
    if not token_clean:
        raise DomainValidationError("An invitation token is required.")

    try:
        member = Member.objects.select_related("gym").get(invitation_token=token_clean)
    except Member.DoesNotExist:
        raise DomainValidationError("Invalid or expired invitation token.")

    if member.joining_status == MemberJoiningStatus.JOINED:
        raise DomainValidationError("This invitation has already been accepted.")

    member.user = user
    member.joining_status = MemberJoiningStatus.JOINED
    member.invitation_token = None
    member.save(update_fields=["user", "joining_status", "invitation_token", "updated_at"])
    return member


@transaction.atomic
def update_member_profile(
    member_id: uuid.UUID,
    gym: Gym,
    **update_fields: Any,
) -> Member:
    """
    Updates member profile, demographics, emergency contact, or trainer assignment.
    """
    try:
        member = Member.objects.get(id=member_id, gym=gym)
    except Member.DoesNotExist:
        raise ResourceNotFoundError(f"Member '{member_id}' not found.")

    if "assigned_trainer_id" in update_fields:
        trainer_id = update_fields.pop("assigned_trainer_id")
        if trainer_id is None:
            member.assigned_trainer = None
        else:
            try:
                assignment = GymStaffAssignment.objects.get(id=trainer_id, gym=gym)
                member.assigned_trainer = assignment
            except GymStaffAssignment.DoesNotExist:
                raise DomainValidationError("Assigned trainer does not belong to this gym.")

    for field, val in update_fields.items():
        if hasattr(member, field):
            setattr(member, field, val)

    try:
        member.full_clean()
        member.save()
    except ValidationError as exc:
        raise DomainValidationError(str(exc))

    return member


@transaction.atomic
def delete_member(member_id: uuid.UUID, gym: Gym) -> None:
    """
    Deletes a member. If subscriptions with payments exist, archives/cancels them instead.
    """
    try:
        member = Member.objects.get(id=member_id, gym=gym)
    except Member.DoesNotExist:
        raise ResourceNotFoundError(f"Member '{member_id}' not found.")

    has_payments = MemberPayment.objects.filter(member_subscription__member=member).exists()
    if has_payments:
        raise ResourceConflictError("Cannot permanently delete a member with payment ledger history. Cancel their active subscription instead.")

    member.delete()


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
def record_member_payment(
    subscription: MemberSubscription,
    amount: Decimal,
    payment_method: str,
    payment_date: date,
    is_initial_payment: bool = False,
    notes: Optional[str] = None,
) -> MemberPayment:
    """
    Logs a payment transaction and automatically recalculates subscription payment_status.
    """
    if amount is None or amount <= Decimal("0.00"):
        raise DomainValidationError("Payment amount must be greater than 0.00.")

    if payment_method not in PaymentMethodEnum.values:
        raise DomainValidationError(f"Invalid payment method '{payment_method}'.")

    payment = MemberPayment.objects.create(
        member_subscription=subscription,
        amount=amount,
        payment_method=payment_method,
        payment_date=payment_date,
        is_initial_payment=is_initial_payment,
        notes=notes.strip() if notes else None,
    )

    # Recalculate payment status
    recalculate_subscription_payment_status(subscription)
    return payment


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
    and updates subscription payment_status.
    """
    plan = subscription.plan
    base_cost = plan.price + plan.joining_fee
    extra_cost = (
        MemberExtraAmenities.objects.filter(member_subscription=subscription, is_active=True)
        .aggregate(total=Sum("extra_fee"))["total"]
        or Decimal("0.00")
    )
    total_cost = base_cost + extra_cost

    total_paid = (
        MemberPayment.objects.filter(member_subscription=subscription)
        .aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )

    if total_paid >= total_cost:
        subscription.payment_status = PaymentStatusEnum.FULLY_PAID
    elif total_paid > Decimal("0.00"):
        subscription.payment_status = PaymentStatusEnum.PARTIALLY_PAID
    else:
        subscription.payment_status = PaymentStatusEnum.UNPAID

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
