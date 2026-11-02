import logging
import uuid
from datetime import date
from typing import Optional
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from apps.access_control.models import GymStaffAssignment
from apps.leads.models import (
    Lead,
    LeadNextMove,
    LeadNotes,
)
from common.exceptions import DomainValidationError

logger = logging.getLogger(__name__)


@transaction.atomic
def schedule_next_move(
    lead: Lead,
    scheduled_date: date,
    short_description: str,
) -> LeadNextMove:
    """
    Schedules an action item or follow-up activity for the lead.
    """
    desc_clean = short_description.strip() if short_description else ""
    if not desc_clean:
        raise DomainValidationError("Short description of next move is required.")

    return LeadNextMove.objects.create(
        lead=lead,
        scheduled_date=scheduled_date,
        short_description=desc_clean,
        is_completed=False,
    )


@transaction.atomic
def complete_next_move(next_move: LeadNextMove) -> LeadNextMove:
    """
    Marks a scheduled next move as completed.
    """
    next_move.is_completed = True
    next_move.save(update_fields=["is_completed"])
    return next_move


@transaction.atomic
def add_lead_note(
    lead: Lead,
    note_text: str,
    author_staff_id: Optional[uuid.UUID] = None,
) -> LeadNotes:
    """
    Appends an internal text note to the lead's dossier.
    """
    text_clean = note_text.strip() if note_text else ""
    if not text_clean:
        raise DomainValidationError("Note text cannot be empty.")

    author_staff = None
    if author_staff_id:
        try:
            author_staff = GymStaffAssignment.objects.select_related("user").get(id=author_staff_id, gym=lead.gym)
        except GymStaffAssignment.DoesNotExist:
            raise DomainValidationError("Author staff not found in this gym.")

    return LeadNotes.objects.create(
        lead=lead,
        author_staff=author_staff,
        note_text=text_clean,
    )


def send_lead_followup_reminders() -> int:
    """
    Daily lifecycle worker:
    Queries uncompleted LeadNextMove items scheduled for today and alerts assigned staff or gym owners.
    Returns count of reminder notifications dispatched.
    """
    today = timezone.localdate()
    moves = (
        LeadNextMove.objects.filter(
            scheduled_date=today,
            is_completed=False,
        )
        .select_related(
            "lead",
            "lead__assigned_staff",
            "lead__assigned_staff__user",
            "lead__gym",
            "lead__gym__owner_user",
        )
        .only(
            "id",
            "scheduled_date",
            "short_description",
            "is_completed",
            "lead_id",
            "lead__id",
            "lead__first_name",
            "lead__last_name",
            "lead__phone",
            "lead__email",
            "lead__stage",
            "lead__assigned_staff_id",
            "lead__gym_id",
            "lead__assigned_staff__id",
            "lead__assigned_staff__user_id",
            "lead__assigned_staff__user__id",
            "lead__assigned_staff__user__first_name",
            "lead__assigned_staff__user__email",
            "lead__gym__id",
            "lead__gym__name",
            "lead__gym__owner_user_id",
            "lead__gym__owner_user__id",
            "lead__gym__owner_user__first_name",
            "lead__gym__owner_user__email",
        )
        .order_by()
        .iterator(chunk_size=1000)
    )

    dispatched = 0
    for move in moves:
        lead = move.lead
        gym = lead.gym
        recipient_email = None
        recipient_name = None

        if lead.assigned_staff and lead.assigned_staff.user and lead.assigned_staff.user.email:
            recipient_email = lead.assigned_staff.user.email
            recipient_name = f"{lead.assigned_staff.user.first_name}".strip() or "Staff Member"
        elif gym and gym.owner_user and gym.owner_user.email:
            recipient_email = gym.owner_user.email
            recipient_name = f"{gym.owner_user.first_name}".strip() or "Gym Owner"

        if not recipient_email:
            continue

        stage_disp = lead.get_stage_display()
        lead_phone = lead.phone or "N/A"
        lead_email = lead.email or "N/A"

        subject = f"Action Required: Lead follow-up due today for {lead.full_name} ({gym.name})"
        lines = [
            f"Hi {recipient_name},",
            "",
            f"You have an uncompleted lead follow-up action due today at {gym.name}:",
            "",
            f"Lead Name: {lead.full_name}",
            f"Phone: {lead_phone}",
            f"Email: {lead_email}",
            f"Current Stage: {stage_disp}",
            f"Scheduled Task: {move.short_description}",
            "",
            "Please follow up with the prospective member and update their stage in Many Gym.",
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
                recipient_list=[recipient_email],
                fail_silently=False,
            )
            dispatched += 1
        except Exception as exc:
            logger.error(f"Failed to dispatch lead follow-up reminder for move {move.id}: {exc}")

    logger.info(f"Dispatched {dispatched} lead follow-up reminders on {today}.")
    return dispatched
