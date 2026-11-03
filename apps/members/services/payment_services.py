from datetime import date
from decimal import Decimal
from typing import Optional
from django.db import transaction

from apps.members.models import (
    MemberSubscription,
    MemberPayment,
)
from apps.members.services.subscription_services import recalculate_subscription_payment_status
from common.enums import PaymentMethodEnum
from common.exceptions import DomainValidationError


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

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        member = subscription.member
        member_name = f"{member.first_name} {member.last_name}".strip() or member.email
        log_admin_action(
            gym=member.gym,
            action="Recorded payment",
            action_type=AdminLogActionType.RECORD_PAYMENT,
            details=f"Recorded payment of ${amount} via {payment_method} for {member_name}",
            category=AdminLogCategory.SUBSCRIPTIONS,
            target_type="payment",
            target_id=str(payment.id),
            metadata={"amount": str(amount), "payment_method": payment_method},
        )
    except Exception:
        pass

    return payment
