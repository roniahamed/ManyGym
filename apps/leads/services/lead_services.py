import uuid
from datetime import date, datetime
from typing import List, Optional
from django.db import transaction

from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from apps.memberships.models import MembershipPlan
from apps.leads.models import (
    Lead,
    LeadCustomReasons,
    LeadFitnessGoals,
)
from apps.leads.services.action_services import add_lead_note
from common.enums import (
    LeadStageEnum,
    LeadSourceEnum,
    NotJoiningReasonStandard,
    FitnessGoalEnum,
)
from common.exceptions import (
    DomainValidationError,
    ResourceConflictError,
)


def create_custom_reason(gym: Gym, reason_name: str) -> LeadCustomReasons:
    """
    Creates a new gym-specific custom reason for lost leads.
    """
    clean_name = reason_name.strip() if reason_name else ""
    if not clean_name:
        raise DomainValidationError("Custom reason name is required.")

    if LeadCustomReasons.objects.filter(gym=gym, reason_name__iexact=clean_name).exists():
        raise ResourceConflictError(f"A custom reason '{clean_name}' already exists for this gym.")

    return LeadCustomReasons.objects.create(
        gym=gym,
        reason_name=clean_name,
    )


@transaction.atomic
def create_lead(
    gym: Gym,
    first_name: str,
    last_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    interested_plan_id: Optional[uuid.UUID] = None,
    assigned_staff_id: Optional[uuid.UUID] = None,
    source: str = LeadSourceEnum.WALK_IN,
    stage: str = LeadStageEnum.NEW,
    expected_start_date: Optional[date] = None,
    trial_booked_at: Optional[datetime] = None,
    not_joining_reason_standard: Optional[str] = None,
    not_joining_custom_reason_id: Optional[uuid.UUID] = None,
    fitness_goals: Optional[List[str]] = None,
    initial_note: Optional[str] = None,
    author_staff_id: Optional[uuid.UUID] = None,
) -> Lead:
    """
    Creates a prospective lead, validates contact details, attaches fitness goals and initial note.
    """
    fn_clean = first_name.strip() if first_name else ""
    ln_clean = last_name.strip() if last_name else ""
    phone_clean = phone.strip() if phone else ""
    email_clean = email.strip().lower() if email else ""

    if not fn_clean:
        raise DomainValidationError("Lead first name is required.")
    if not phone_clean and not email_clean:
        raise DomainValidationError("At least one contact method (phone or email) is required.")

    if email_clean and "@" not in email_clean:
        raise DomainValidationError("Please provide a valid email address.")

    if stage not in LeadStageEnum.values:
        raise DomainValidationError(f"Invalid stage '{stage}'. Allowed values: {LeadStageEnum.values}")
    if source not in LeadSourceEnum.values:
        raise DomainValidationError(f"Invalid source '{source}'. Allowed values: {LeadSourceEnum.values}")

    interested_plan = None
    if interested_plan_id:
        try:
            interested_plan = MembershipPlan.objects.get(id=interested_plan_id, gym=gym)
        except MembershipPlan.DoesNotExist:
            raise DomainValidationError("Interested plan not found or does not belong to this gym.")

    assigned_staff = None
    if assigned_staff_id:
        try:
            assigned_staff = GymStaffAssignment.objects.select_related("user").get(id=assigned_staff_id, gym=gym)
        except GymStaffAssignment.DoesNotExist:
            raise DomainValidationError("Assigned staff not found or does not belong to this gym.")

    custom_reason = None
    if not_joining_custom_reason_id:
        try:
            custom_reason = LeadCustomReasons.objects.get(id=not_joining_custom_reason_id, gym=gym)
        except LeadCustomReasons.DoesNotExist:
            raise DomainValidationError("Custom reason not found or does not belong to this gym.")

    if stage == LeadStageEnum.NOT_JOINING:
        if not not_joining_reason_standard and not custom_reason:
            raise DomainValidationError(
                "A standard reason or custom gym reason must be provided when lead is marked as 'not_joining'."
            )
        if not_joining_reason_standard and not_joining_reason_standard not in NotJoiningReasonStandard.values:
            raise DomainValidationError(
                f"Invalid not joining standard reason. Allowed: {NotJoiningReasonStandard.values}"
            )

    lead = Lead(
        gym=gym,
        first_name=fn_clean,
        last_name=ln_clean if ln_clean else None,
        phone=phone_clean if phone_clean else None,
        email=email_clean if email_clean else None,
        interested_plan=interested_plan,
        assigned_staff=assigned_staff,
        source=source,
        stage=stage,
        expected_start_date=expected_start_date,
        trial_booked_at=trial_booked_at,
        not_joining_reason_standard=not_joining_reason_standard if stage == LeadStageEnum.NOT_JOINING else None,
        not_joining_custom_reason=custom_reason if stage == LeadStageEnum.NOT_JOINING else None,
    )
    lead.save()

    # Attach fitness goals if provided
    if fitness_goals:
        goal_objs = []
        valid_goals = set(FitnessGoalEnum.values)
        seen_goals = set()
        for g in fitness_goals:
            g_clean = g.strip().lower() if isinstance(g, str) else str(g)
            if g_clean not in valid_goals:
                raise DomainValidationError(f"Invalid fitness goal '{g}'. Allowed values: {list(valid_goals)}")
            if g_clean not in seen_goals:
                seen_goals.add(g_clean)
                goal_objs.append(LeadFitnessGoals(lead=lead, goal=g_clean))
        if goal_objs:
            LeadFitnessGoals.objects.bulk_create(goal_objs)

    # Attach initial note if provided
    if initial_note and initial_note.strip():
        add_lead_note(
            lead=lead,
            note_text=initial_note.strip(),
            author_staff_id=author_staff_id,
        )

    return lead


@transaction.atomic
def update_lead(
    lead: Lead,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    interested_plan_id: Optional[uuid.UUID] = ...,  # Ellipsis allows distinguishing None from omitted
    assigned_staff_id: Optional[uuid.UUID] = ...,
    source: Optional[str] = None,
    stage: Optional[str] = None,
    not_joining_reason_standard: Optional[str] = ...,
    not_joining_custom_reason_id: Optional[uuid.UUID] = ...,
    expected_start_date: Optional[date] = ...,
    trial_booked_at: Optional[datetime] = ...,
    fitness_goals: Optional[List[str]] = None,
) -> Lead:
    """
    Updates prospective lead attributes, contact info, staff assignment, or goals.
    """
    if first_name is not None:
        fn_clean = first_name.strip()
        if not fn_clean:
            raise DomainValidationError("Lead first name cannot be empty.")
        lead.first_name = fn_clean

    if last_name is not None:
        lead.last_name = last_name.strip() or None

    new_phone = phone.strip() if phone is not None else lead.phone
    new_email = email.strip().lower() if email is not None else lead.email

    if phone is not None:
        lead.phone = new_phone or None
    if email is not None:
        lead.email = new_email or None

    if not (lead.phone and lead.phone.strip()) and not (lead.email and lead.email.strip()):
        raise DomainValidationError("At least one contact method (phone or email) must be maintained.")

    if lead.email and "@" not in lead.email:
        raise DomainValidationError("Please provide a valid email address.")

    if source is not None:
        if source not in LeadSourceEnum.values:
            raise DomainValidationError(f"Invalid source '{source}'. Allowed: {LeadSourceEnum.values}")
        lead.source = source

    if interested_plan_id is not ...:
        if interested_plan_id is None:
            lead.interested_plan = None
        else:
            try:
                lead.interested_plan = MembershipPlan.objects.get(id=interested_plan_id, gym=lead.gym)
            except MembershipPlan.DoesNotExist:
                raise DomainValidationError("Interested plan not found in this gym.")

    if assigned_staff_id is not ...:
        if assigned_staff_id is None:
            lead.assigned_staff = None
        else:
            try:
                lead.assigned_staff = GymStaffAssignment.objects.select_related("user").get(
                    id=assigned_staff_id,
                    gym=lead.gym,
                )
            except GymStaffAssignment.DoesNotExist:
                raise DomainValidationError("Assigned staff not found in this gym.")

    if expected_start_date is not ...:
        lead.expected_start_date = expected_start_date

    if trial_booked_at is not ...:
        lead.trial_booked_at = trial_booked_at

    # Handle stage change if requested in update
    if stage is not None:
        std_reason = not_joining_reason_standard if not_joining_reason_standard is not ... else lead.not_joining_reason_standard
        cust_reason_id = not_joining_custom_reason_id if not_joining_custom_reason_id is not ... else (
            lead.not_joining_custom_reason_id
        )
        update_lead_stage(
            lead=lead,
            new_stage=stage,
            not_joining_reason_standard=std_reason,
            not_joining_custom_reason_id=cust_reason_id,
            trial_booked_at=lead.trial_booked_at,
        )
    else:
        if not_joining_reason_standard is not ...:
            lead.not_joining_reason_standard = not_joining_reason_standard
        if not_joining_custom_reason_id is not ...:
            if not_joining_custom_reason_id is None:
                lead.not_joining_custom_reason = None
            else:
                try:
                    lead.not_joining_custom_reason = LeadCustomReasons.objects.get(
                        id=not_joining_custom_reason_id,
                        gym=lead.gym,
                    )
                except LeadCustomReasons.DoesNotExist:
                    raise DomainValidationError("Custom reason not found in this gym.")
        lead.save()

    # Update fitness goals if explicitly provided
    if fitness_goals is not None:
        LeadFitnessGoals.objects.filter(lead=lead).delete()
        valid_goals = set(FitnessGoalEnum.values)
        goal_objs = []
        seen = set()
        for g in fitness_goals:
            g_clean = g.strip().lower() if isinstance(g, str) else str(g)
            if g_clean not in valid_goals:
                raise DomainValidationError(f"Invalid fitness goal '{g}'. Allowed: {list(valid_goals)}")
            if g_clean not in seen:
                seen.add(g_clean)
                goal_objs.append(LeadFitnessGoals(lead=lead, goal=g_clean))
        if goal_objs:
            LeadFitnessGoals.objects.bulk_create(goal_objs)

    return lead


@transaction.atomic
def update_lead_stage(
    lead: Lead,
    new_stage: str,
    not_joining_reason_standard: Optional[str] = None,
    not_joining_custom_reason_id: Optional[uuid.UUID] = None,
    custom_reason_name: Optional[str] = None,
    trial_booked_at: Optional[datetime] = None,
) -> Lead:
    """
    Transitions lead across sales pipeline stages and enforces business invariants.
    """
    if new_stage not in LeadStageEnum.values:
        raise DomainValidationError(f"Invalid stage '{new_stage}'. Allowed: {LeadStageEnum.values}")

    if lead.stage == LeadStageEnum.JOINED and new_stage != LeadStageEnum.JOINED:
        raise ResourceConflictError("Cannot revert stage of a lead that has already joined as a member.")

    if new_stage == LeadStageEnum.NOT_JOINING:
        custom_reason = None
        if custom_reason_name and custom_reason_name.strip():
            # Dynamically get or create custom reason
            custom_reason, _ = LeadCustomReasons.objects.get_or_create(
                gym=lead.gym,
                reason_name=custom_reason_name.strip(),
            )
        elif not_joining_custom_reason_id:
            try:
                custom_reason = LeadCustomReasons.objects.get(id=not_joining_custom_reason_id, gym=lead.gym)
            except LeadCustomReasons.DoesNotExist:
                raise DomainValidationError("Custom reason not found in this gym.")

        if not not_joining_reason_standard and not custom_reason:
            raise DomainValidationError(
                "A standard reason or custom gym reason must be provided when stage is marked as 'not_joining'."
            )

        if not_joining_reason_standard and not_joining_reason_standard not in NotJoiningReasonStandard.values:
            raise DomainValidationError(
                f"Invalid not joining standard reason. Allowed: {NotJoiningReasonStandard.values}"
            )

        lead.not_joining_reason_standard = not_joining_reason_standard
        lead.not_joining_custom_reason = custom_reason
    else:
        # Clear not joining reasons if moving to a non-lost stage
        lead.not_joining_reason_standard = None
        lead.not_joining_custom_reason = None

    if new_stage == LeadStageEnum.VISIT_TRIAL_BOOKED and trial_booked_at is not None:
        lead.trial_booked_at = trial_booked_at

    lead.stage = new_stage
    lead.save()
    return lead


@transaction.atomic
def delete_lead(lead: Lead) -> None:
    """
    Deletes a prospective lead unless already converted to an active gym member.
    """
    if lead.stage == LeadStageEnum.JOINED or lead.converted_member_id is not None:
        raise ResourceConflictError("Cannot delete a lead that has already been converted to a member.")
    lead.delete()
