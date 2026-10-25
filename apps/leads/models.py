import uuid
from django.db import models
from django.core.exceptions import ValidationError

from common.enums import (
    LeadStageEnum,
    NotJoiningReasonStandard,
    LeadSourceEnum,
    FitnessGoalEnum,
)


class LeadCustomReasons(models.Model):
    """
    Gym-level custom taxonomy for lost/not joining reasons when leads decline membership.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="lead_custom_reasons",
    )
    reason_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "lead_custom_reasons"
        verbose_name = "Lead Custom Reason"
        verbose_name_plural = "Lead Custom Reasons"
        ordering = ["reason_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["gym", "reason_name"],
                name="unique_gym_lead_custom_reason",
            )
        ]
        indexes = [
            models.Index(fields=["gym", "reason_name"], name="idx_lead_custom_reason_gym"),
        ]

    def __str__(self):
        return f"{self.reason_name} ({self.gym.name})"


# Alias for singular imports
LeadCustomReason = LeadCustomReasons


class Lead(models.Model):
    """
    Prospective gym lead entity representing inquiry, sales pipeline stage, and follow-ups.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="leads",
    )
    interested_plan = models.ForeignKey(
        "memberships.MembershipPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interested_leads",
        help_text="Membership plan the lead is interested in.",
    )
    assigned_staff = models.ForeignKey(
        "access_control.GymStaffAssignment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_leads",
        help_text="Gym staff or sales representative responsible for following up.",
    )
    converted_member = models.ForeignKey(
        "members.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="originated_lead",
        help_text="Active gym member record created upon successful conversion.",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    phone = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True)

    stage = models.CharField(
        max_length=50,
        choices=LeadStageEnum.choices,
        default=LeadStageEnum.NEW,
        db_index=True,
    )
    not_joining_reason_standard = models.CharField(
        max_length=50,
        choices=NotJoiningReasonStandard.choices,
        null=True,
        blank=True,
    )
    not_joining_custom_reason = models.ForeignKey(
        LeadCustomReasons,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )
    expected_start_date = models.DateField(null=True, blank=True)
    source = models.CharField(
        max_length=50,
        choices=LeadSourceEnum.choices,
        default=LeadSourceEnum.WALK_IN,
        db_index=True,
    )
    trial_booked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "leads"
        verbose_name = "Lead"
        verbose_name_plural = "Leads"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["gym", "-created_at"], name="idx_lead_gym_created"),
            models.Index(fields=["gym", "stage"], name="idx_lead_gym_stage"),
            models.Index(fields=["gym", "source"], name="idx_lead_gym_source"),
            models.Index(fields=["gym", "assigned_staff"], name="idx_lead_gym_staff"),
            models.Index(fields=["gym", "email"], name="idx_lead_gym_email"),
            models.Index(fields=["gym", "phone"], name="idx_lead_gym_phone"),
        ]

    @property
    def full_name(self) -> str:
        if self.last_name:
            return f"{self.first_name} {self.last_name}".strip()
        return self.first_name.strip()

    def clean(self):
        super().clean()
        phone_clean = (self.phone or "").strip()
        email_clean = (self.email or "").strip()
        if not phone_clean and not email_clean:
            raise ValidationError("At least one contact method (phone or email) is required.")

        if self.stage == LeadStageEnum.NOT_JOINING:
            if not self.not_joining_reason_standard and not self.not_joining_custom_reason:
                raise ValidationError(
                    "A standard reason or custom gym reason must be provided when stage is marked as 'not_joining'."
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} ({self.stage}) - {self.gym.name}"


class LeadFitnessGoals(models.Model):
    """
    Multi-select fitness goals for prospective leads.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="fitness_goals",
    )
    goal = models.CharField(
        max_length=50,
        choices=FitnessGoalEnum.choices,
    )

    class Meta:
        db_table = "lead_fitness_goals"
        verbose_name = "Lead Fitness Goal"
        verbose_name_plural = "Lead Fitness Goals"
        constraints = [
            models.UniqueConstraint(
                fields=["lead", "goal"],
                name="unique_lead_fitness_goal",
            )
        ]
        indexes = [
            models.Index(fields=["lead", "goal"], name="idx_lead_fitness_goal"),
        ]

    def __str__(self):
        return f"{self.lead.full_name} - {self.goal}"


# Alias for singular imports
LeadFitnessGoal = LeadFitnessGoals


class LeadNextMove(models.Model):
    """
    Scheduled action item or follow-up activity for a lead.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="next_moves",
    )
    scheduled_date = models.DateField()
    short_description = models.CharField(max_length=255)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "lead_next_moves"
        verbose_name = "Lead Next Move"
        verbose_name_plural = "Lead Next Moves"
        ordering = ["is_completed", "scheduled_date", "-created_at"]
        indexes = [
            models.Index(fields=["lead", "is_completed", "scheduled_date"], name="idx_lead_next_move_sched"),
            models.Index(fields=["is_completed", "scheduled_date"], name="idx_lead_move_comp_sched"),
        ]

    def __str__(self):
        status = "Done" if self.is_completed else "Pending"
        return f"{self.lead.full_name} - {self.short_description} ({self.scheduled_date}) [{status}]"


class LeadNotes(models.Model):
    """
    Internal staff notes thread for lead communication and activity history.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name="notes",
    )
    author_staff = models.ForeignKey(
        "access_control.GymStaffAssignment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_lead_notes",
    )
    note_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "lead_notes"
        verbose_name = "Lead Note"
        verbose_name_plural = "Lead Notes"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["lead", "-created_at"], name="idx_lead_note_created"),
        ]

    def __str__(self):
        return f"Note on {self.lead.full_name} at {self.created_at}"


# Alias for singular imports
LeadNote = LeadNotes
