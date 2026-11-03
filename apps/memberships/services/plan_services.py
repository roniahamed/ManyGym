import uuid
from decimal import Decimal
from typing import List, Optional, Dict, Any
from django.db import transaction
from django.core.exceptions import ValidationError

from apps.gyms.models import Gym
from apps.memberships.models import MembershipPlan
from apps.memberships.services.amenities_services import sync_plan_amenities
from common.enums import (
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    PaymentScheduleEnum,
)
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    ResourceConflictError,
)


@transaction.atomic
def create_membership_plan(
    gym: Gym,
    name: str,
    plan_type: str,
    price: Decimal,
    duration_value: int,
    duration_unit: str,
    description: Optional[str] = None,
    plan_status: str = PlanStatusEnum.DRAFT,
    joining_fee: Decimal = Decimal("0.00"),
    payment_schedule: str = PaymentScheduleEnum.FULL_PAYMENT,
    installment_schedule_config: Optional[Dict[str, Any]] = None,
    cancellation_policy: Optional[str] = None,
    refund_policy: Optional[str] = None,
    included_amenity_ids: Optional[List[uuid.UUID]] = None,
) -> MembershipPlan:
    """
    Creates a new 5-step membership plan definition with validated pricing, duration, and bundled amenities.
    """
    # 1. Clean and normalize inputs
    name_clean = name.strip() if name else ""
    if not name_clean:
        raise DomainValidationError("Plan name is required.")

    desc_clean = description.strip() if description else None
    if desc_clean and len(desc_clean) < 50:
        raise DomainValidationError("Description must be at least 50 characters long when provided.")

    # 2. Plan type and duration unit validations
    if plan_type == PlanTypeEnum.TIME_BASED:
        valid_units = [DurationUnitEnum.DAY, DurationUnitEnum.WEEK, DurationUnitEnum.MONTH]
        if duration_unit not in valid_units:
            raise DomainValidationError(
                f"For time-based plans, duration unit must be one of: {', '.join(valid_units)}."
            )
    elif plan_type == PlanTypeEnum.SESSION_BASED:
        if duration_unit != DurationUnitEnum.SESSION:
            raise DomainValidationError("For session-based plans, duration unit must be 'session'.")
    else:
        raise DomainValidationError(f"Invalid plan type '{plan_type}'.")

    if price is None or price < Decimal("0.00"):
        raise DomainValidationError("Price cannot be negative.")

    if joining_fee is None or joining_fee < Decimal("0.00"):
        raise DomainValidationError("Joining fee cannot be negative.")

    if duration_value is None or duration_value < 1:
        raise DomainValidationError("Duration value must be at least 1.")

    if payment_schedule == PaymentScheduleEnum.INSTALMENTS:
        if not installment_schedule_config:
            raise DomainValidationError(
                "Installment schedule configuration is required when payment schedule is set to 'instalments'."
            )
    elif payment_schedule != PaymentScheduleEnum.FULL_PAYMENT:
        raise DomainValidationError(f"Invalid payment schedule '{payment_schedule}'.")

    # 3. Create plan entity
    plan = MembershipPlan(
        gym=gym,
        name=name_clean,
        description=desc_clean,
        plan_status=plan_status,
        plan_type=plan_type,
        price=price,
        duration_value=duration_value,
        duration_unit=duration_unit,
        joining_fee=joining_fee,
        payment_schedule=payment_schedule,
        installment_schedule_config=installment_schedule_config if payment_schedule == PaymentScheduleEnum.INSTALMENTS else None,
        cancellation_policy=cancellation_policy.strip() if cancellation_policy else None,
        refund_policy=refund_policy.strip() if refund_policy else None,
    )

    try:
        plan.full_clean()
        plan.save()
    except ValidationError as exc:
        raise DomainValidationError(str(exc))

    # 4. Link included amenities
    if included_amenity_ids:
        sync_plan_amenities(plan=plan, gym=gym, amenity_ids=included_amenity_ids)

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        log_admin_action(
            gym=gym,
            action="Create a custom membership plan",
            action_type=AdminLogActionType.CREATE_MEMBERSHIP_PLAN,
            details=f"Created custom plan '{plan.name}' ({plan.price})",
            category=AdminLogCategory.MEMBERSHIP_PLANS,
            target_type="plan",
            target_id=str(plan.id),
        )
    except Exception:
        pass

    return plan


@transaction.atomic
def update_membership_plan(
    plan_id: uuid.UUID,
    gym: Gym,
    **update_fields: Any,
) -> MembershipPlan:
    """
    Updates an existing membership plan. Enforces invariant: if active subscriptions exist,
    pricing and duration fields cannot be modified.
    """
    try:
        plan = MembershipPlan.objects.select_related("gym").get(id=plan_id, gym=gym)
    except MembershipPlan.DoesNotExist:
        raise ResourceNotFoundError(f"Membership plan '{plan_id}' not found for this gym.")

    # Check for active member subscriptions if the subscriptions relation exists
    has_active_subscriptions = False
    if hasattr(plan, "subscriptions"):
        has_active_subscriptions = plan.subscriptions.filter(membership_status="active").exists()

    protected_fields = {"price", "plan_type", "duration_value", "duration_unit", "joining_fee", "payment_schedule"}
    if has_active_subscriptions:
        for field in protected_fields:
            if field in update_fields and getattr(plan, field) != update_fields[field]:
                raise DomainValidationError(
                    f"Cannot modify '{field}' on a membership plan with active member subscriptions."
                )

    # Process description validation
    if "description" in update_fields:
        desc = update_fields["description"]
        if desc is not None:
            desc_clean = str(desc).strip()
            if desc_clean and len(desc_clean) < 50:
                raise DomainValidationError("Description must be at least 50 characters long when provided.")
            update_fields["description"] = desc_clean if desc_clean else None

    # Process plan_type and duration_unit compatibility
    new_type = update_fields.get("plan_type", plan.plan_type)
    new_unit = update_fields.get("duration_unit", plan.duration_unit)

    if new_type == PlanTypeEnum.TIME_BASED:
        valid_units = [DurationUnitEnum.DAY, DurationUnitEnum.WEEK, DurationUnitEnum.MONTH]
        if new_unit not in valid_units:
            raise DomainValidationError(
                f"For time-based plans, duration unit must be one of: {', '.join(valid_units)}."
            )
    elif new_type == PlanTypeEnum.SESSION_BASED:
        if new_unit != DurationUnitEnum.SESSION:
            raise DomainValidationError("For session-based plans, duration unit must be 'session'.")

    # Payment schedule & installments
    new_schedule = update_fields.get("payment_schedule", plan.payment_schedule)
    if new_schedule == PaymentScheduleEnum.INSTALMENTS:
        config = update_fields.get("installment_schedule_config", plan.installment_schedule_config)
        if not config:
            raise DomainValidationError(
                "Installment schedule configuration is required when payment schedule is set to 'instalments'."
            )
    elif "installment_schedule_config" in update_fields and new_schedule == PaymentScheduleEnum.FULL_PAYMENT:
        update_fields["installment_schedule_config"] = None

    # Handle amenities update if provided
    included_amenity_ids = update_fields.pop("included_amenity_ids", None)

    for key, value in update_fields.items():
        if hasattr(plan, key):
            setattr(plan, key, value)

    try:
        plan.full_clean()
        plan.save()
    except ValidationError as exc:
        raise DomainValidationError(str(exc))

    if included_amenity_ids is not None:
        sync_plan_amenities(plan=plan, gym=gym, amenity_ids=included_amenity_ids)

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        log_admin_action(
            gym=gym,
            action="Update a custom membership plan",
            action_type=AdminLogActionType.UPDATE_MEMBERSHIP_PLAN,
            details=f"Updated custom plan '{plan.name}'",
            category=AdminLogCategory.MEMBERSHIP_PLANS,
            target_type="plan",
            target_id=str(plan.id),
        )
    except Exception:
        pass

    return plan


@transaction.atomic
def set_plan_status(
    plan_id: uuid.UUID,
    gym: Gym,
    new_status: str,
) -> MembershipPlan:
    """
    Manages state machine transitions: (draft -> active <-> archived).
    Archived plans cannot be reverted to draft.
    """
    try:
        plan = MembershipPlan.objects.get(id=plan_id, gym=gym)
    except MembershipPlan.DoesNotExist:
        raise ResourceNotFoundError(f"Membership plan '{plan_id}' not found for this gym.")

    current_status = plan.plan_status

    if current_status == new_status:
        return plan

    # Invariants for transitions
    if current_status == PlanStatusEnum.ARCHIVED and new_status == PlanStatusEnum.DRAFT:
        raise DomainValidationError("Archived plans cannot be reverted back to draft status.")

    if new_status == PlanStatusEnum.ACTIVE:
        # Validate that the plan has all mandatory fields before activation
        if not plan.name or plan.price is None or not plan.duration_value or not plan.duration_unit:
            raise DomainValidationError("Cannot activate a plan that is missing name, price, or duration details.")

    plan.plan_status = new_status
    plan.save(update_fields=["plan_status", "updated_at"])

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        log_admin_action(
            gym=gym,
            action="Changed plan status",
            action_type=AdminLogActionType.CHANGE_PLAN_STATUS,
            details=f"Changed status of '{plan.name}' from {current_status} to {new_status}",
            category=AdminLogCategory.MEMBERSHIP_PLANS,
            target_type="plan",
            target_id=str(plan.id),
        )
    except Exception:
        pass

    return plan


@transaction.atomic
def delete_membership_plan(
    plan_id: uuid.UUID,
    gym: Gym,
) -> None:
    """
    Deletes a membership plan. If plan has subscribers or active history, archives it instead.
    Only draft plans without subscribers can be permanently removed.
    """
    try:
        plan = MembershipPlan.objects.get(id=plan_id, gym=gym)
    except MembershipPlan.DoesNotExist:
        raise ResourceNotFoundError(f"Membership plan '{plan_id}' not found for this gym.")

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        log_admin_action(
            gym=gym,
            action="Delete a custom membership plan",
            action_type=AdminLogActionType.DELETE_MEMBERSHIP_PLAN,
            details=f"Deleted custom plan '{plan.name}'",
            category=AdminLogCategory.MEMBERSHIP_PLANS,
            target_type="plan",
            target_id=str(plan.id),
        )
    except Exception:
        pass

    has_subscriptions = False
    if hasattr(plan, "subscriptions"):
        has_subscriptions = plan.subscriptions.exists()

    if has_subscriptions:
        raise ResourceConflictError(
            "Cannot delete a membership plan that has member subscription history. Archive the plan instead."
        )

    if plan.plan_status != PlanStatusEnum.DRAFT:
        # Auto-archive if active
        plan.plan_status = PlanStatusEnum.ARCHIVED
        plan.save(update_fields=["plan_status", "updated_at"])
    else:
        plan.delete()
