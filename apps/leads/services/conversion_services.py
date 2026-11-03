import uuid
from datetime import date
from decimal import Decimal
from typing import List, Optional
from django.db import transaction
from django.utils import timezone

from apps.members.models import Member
from apps.members.services import create_member
from apps.leads.models import Lead
from apps.leads.services.action_services import add_lead_note
from common.enums import LeadStageEnum
from common.exceptions import (
    DomainValidationError,
    ResourceConflictError,
)


@transaction.atomic
def convert_lead_to_member(
    lead: Lead,
    plan_id: Optional[uuid.UUID] = None,
    member_email: Optional[str] = None,
    last_name: Optional[str] = None,
    assigned_trainer_id: Optional[uuid.UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    extra_amenity_ids: Optional[List[uuid.UUID]] = None,
    initial_payment_amount: Optional[Decimal] = None,
    initial_payment_method: Optional[str] = None,
    initial_payment_date: Optional[date] = None,
    initial_payment_notes: Optional[str] = None,
    date_of_birth: Optional[date] = None,
    sex: Optional[str] = None,
    nationality: Optional[str] = None,
    emergency_contact_name: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
    emergency_contact_relationship: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    author_staff_id: Optional[uuid.UUID] = None,
) -> Member:
    """
    Atomically converts a prospective lead into an active gym member:
    1. Creates a Member dossier populated from lead info.
    2. Attaches the specified or interested membership plan.
    3. Starts onboarding invitation email dispatch workflow.
    4. Marks lead stage as 'joined' and stores converted_member_id.
    """
    if lead.stage == LeadStageEnum.JOINED or lead.converted_member_id is not None:
        raise ResourceConflictError("This lead has already been converted to an active member.")

    # Determine email
    email_to_use = (member_email.strip().lower() if member_email else "") or (lead.email.strip().lower() if lead.email else "")
    if not email_to_use or "@" not in email_to_use:
        raise DomainValidationError("A valid email address is required to convert a lead to a member.")

    target_last_name = (
        (last_name.strip() if last_name else "")
        or (lead.last_name.strip() if lead.last_name else "")
        or "-"
    )

    target_plan_id = plan_id or (lead.interested_plan_id if lead.interested_plan else None)
    target_start_date = start_date or lead.expected_start_date or timezone.localdate()

    # Create Member dossier using member service
    member = create_member(
        gym=lead.gym,
        first_name=lead.first_name,
        last_name=target_last_name,
        email=email_to_use,
        phone=lead.phone,
        address=address,
        city=city,
        country=country,
        date_of_birth=date_of_birth,
        sex=sex,
        nationality=nationality,
        emergency_contact_name=emergency_contact_name,
        emergency_contact_phone=emergency_contact_phone,
        emergency_contact_relationship=emergency_contact_relationship,
        assigned_trainer_id=assigned_trainer_id,
        internal_notes=f"Converted from Lead ID: {lead.id}",
        plan_id=target_plan_id,
        start_date=target_start_date,
        end_date=end_date,
        extra_amenity_ids=extra_amenity_ids,
        initial_payment_amount=initial_payment_amount,
        initial_payment_method=initial_payment_method,
        initial_payment_date=initial_payment_date,
        initial_payment_notes=initial_payment_notes,
    )

    # Link converted member to lead and update stage
    lead.converted_member = member
    lead.stage = LeadStageEnum.JOINED
    lead.save(update_fields=["converted_member", "stage", "updated_at"])

    # Record conversion audit note
    add_lead_note(
        lead=lead,
        note_text=f"Lead converted successfully to member: {member.full_name} ({member.email}).",
        author_staff_id=author_staff_id,
    )

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        lead_name = f"{lead.first_name} {lead.last_name}".strip()
        log_admin_action(
            gym=lead.gym,
            action="Converted lead to member",
            action_type=AdminLogActionType.CONVERT_LEAD,
            details=f"Converted lead {lead_name} into active member {member.first_name} {member.last_name}",
            category=AdminLogCategory.LEADS,
            target_type="lead",
            target_id=str(lead.id),
        )
    except Exception:
        pass

    return member
