import uuid
from decimal import Decimal
from django.db import models
from django.core.exceptions import ValidationError

from common.enums import (
    MemberJoiningStatus,
    MembershipStatusEnum,
    PaymentStatusEnum,
    PaymentMethodEnum,
)


class Member(models.Model):
    """
    Core gym member profile record.
    Can exist independently during invitation/onboarding before user links an account.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="members",
    )
    user = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gym_memberships",
        help_text="Linked user account once onboarding invitation is accepted.",
    )
    assigned_trainer = models.ForeignKey(
        "access_control.GymStaffAssignment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_members",
        help_text="Optional assigned trainer from active gym staff.",
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(max_length=255)
    phone = models.CharField(max_length=50, null=True, blank=True)
    profile_photo_url = models.CharField(max_length=1000, null=True, blank=True)
    address = models.CharField(max_length=500, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=20, null=True, blank=True)
    nationality = models.CharField(max_length=100, null=True, blank=True)

    emergency_contact_name = models.CharField(max_length=150, null=True, blank=True)
    emergency_contact_phone = models.CharField(max_length=50, null=True, blank=True)
    emergency_contact_relationship = models.CharField(max_length=100, null=True, blank=True)

    joining_status = models.CharField(
        max_length=50,
        choices=MemberJoiningStatus.choices,
        default=MemberJoiningStatus.SENT_INVITATION,
        db_index=True,
    )
    invitation_token = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    invitation_sent_at = models.DateTimeField(null=True, blank=True)
    internal_notes = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "members"
        verbose_name = "Gym Member"
        verbose_name_plural = "Gym Members"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["gym", "-created_at"], name="idx_member_gym_created"),
            models.Index(fields=["gym", "joining_status"], name="idx_member_gym_joining"),
            models.Index(fields=["gym", "email"], name="idx_member_gym_email"),
            models.Index(fields=["gym", "first_name", "last_name"], name="idx_member_gym_names"),
        ]

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return f"{self.full_name} ({self.email}) - {self.gym.name}"


class MemberSubscription(models.Model):
    """
    Member subscription contract representing active, paused, or historical plans.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        "memberships.MembershipPlan",
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    membership_status = models.CharField(
        max_length=50,
        choices=MembershipStatusEnum.choices,
        default=MembershipStatusEnum.ACTIVE,
        db_index=True,
    )
    payment_status = models.CharField(
        max_length=50,
        choices=PaymentStatusEnum.choices,
        default=PaymentStatusEnum.UNPAID,
        db_index=True,
    )
    start_date = models.DateField()
    end_date = models.DateField()
    total_sessions = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Total available sessions for session-based plans.",
    )
    remaining_sessions = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Remaining sessions left to consume.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "member_subscriptions"
        verbose_name = "Member Subscription"
        verbose_name_plural = "Member Subscriptions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["member", "-created_at"], name="idx_sub_member_created"),
            models.Index(fields=["membership_status", "end_date"], name="idx_sub_status_end"),
            models.Index(fields=["payment_status"], name="idx_sub_payment_status"),
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "Subscription end date cannot be prior to start date."})

    def __str__(self):
        return f"{self.member.full_name} - {self.plan.name} ({self.get_membership_status_display()})"


class MemberExtraAmenities(models.Model):
    """
    Subscribed extra paid amenities attached to a member's subscription.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    member_subscription = models.ForeignKey(
        MemberSubscription,
        on_delete=models.CASCADE,
        related_name="extra_amenities",
    )
    gym_amenity = models.ForeignKey(
        "amenities.GymAmenity",
        on_delete=models.PROTECT,
        related_name="member_extra_amenities",
    )
    extra_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "member_extra_amenities"
        unique_together = ("member_subscription", "gym_amenity")
        indexes = [
            models.Index(fields=["member_subscription", "gym_amenity"], name="idx_extra_sub_amenity"),
        ]

    def __str__(self):
        return f"{self.member_subscription.member.full_name} - Extra: {self.gym_amenity.amenity.name} (${self.extra_fee})"


class MemberPayment(models.Model):
    """
    Ledger record of payment transactions logged against a member subscription.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    member_subscription = models.ForeignKey(
        MemberSubscription,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(
        max_length=50,
        choices=PaymentMethodEnum.choices,
    )
    payment_date = models.DateField()
    is_initial_payment = models.BooleanField(default=False)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "member_payments"
        verbose_name = "Member Payment"
        verbose_name_plural = "Member Payments"
        ordering = ["-payment_date", "-created_at"]
        indexes = [
            models.Index(fields=["member_subscription", "-payment_date"], name="idx_payment_sub_date"),
        ]

    def __str__(self):
        return f"{self.member_subscription.member.full_name} - Paid ${self.amount} ({self.get_payment_method_display()}) on {self.payment_date}"
