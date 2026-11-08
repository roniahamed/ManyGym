import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError

from common.enums import EnquiryTypeEnum, EnquiryStatusEnum


class Enquiry(models.Model):
    """
    Prospective or active enquiry entity for customer support, callbacks,
    complaints, and sales conversions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Multi-tenancy & Gym context (mandatory, scopes enquiry to a gym)
    gym = models.ForeignKey(
        "gyms.Gym",
        on_delete=models.CASCADE,
        related_name="enquiries",
        help_text="Associated gym entity to which this enquiry belongs.",
    )

    # Manygym user (object) (optional)
    manygym_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="enquiries",
        help_text="Optional Manygym registered user account.",
    )

    # First name, Last name (Required)
    first_name = models.CharField(
        max_length=100,
        help_text="First name of the person enquiring.",
    )
    last_name = models.CharField(
        max_length=100,
        help_text="Last name of the person enquiring.",
    )

    # Either Email or Phone number (mandatory)
    email = models.EmailField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Email address (mandatory if phone number is omitted).",
    )
    phone = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Phone number (mandatory if email address is omitted).",
    )

    # Type (Select) (Import from Afrobeutic's Enquiry)
    type = models.CharField(
        max_length=50,
        choices=EnquiryTypeEnum.choices,
        default=EnquiryTypeEnum.GENERAL_INQUIRY,
        db_index=True,
        help_text="Category/Type of enquiry.",
    )

    # Status (Select) (Import from Afrobeutic's Enquiry)
    status = models.CharField(
        max_length=50,
        choices=EnquiryStatusEnum.choices,
        default=EnquiryStatusEnum.NEW,
        db_index=True,
        help_text="Lifecycle status of enquiry.",
    )

    # Summary
    summary = models.TextField(
        blank=True,
        default="",
        help_text="Summary or query description.",
    )

    # Notes (list of text)
    notes = models.JSONField(
        default=list,
        blank=True,
        help_text="Chronological list of text notes.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "enquiries"
        verbose_name = "Enquiry"
        verbose_name_plural = "Enquiries"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["gym", "-created_at"], name="idx_enquiry_gym_created"),
            models.Index(fields=["status", "-created_at"], name="idx_enquiry_status_created"),
            models.Index(fields=["type", "-created_at"], name="idx_enquiry_type_created"),
            models.Index(fields=["email"], name="idx_enquiry_email"),
            models.Index(fields=["phone"], name="idx_enquiry_phone"),
        ]

    def clean(self):
        super().clean()
        if not getattr(self, "gym_id", None) and not getattr(self, "gym", None):
            raise ValidationError("Associated Gym is mandatory.")
        has_email = bool(self.email and str(self.email).strip())
        has_phone = bool(self.phone and str(self.phone).strip())
        if not has_email and not has_phone:
            raise ValidationError("Either Email or Phone number is mandatory.")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Enquiry {self.id}: {self.first_name} {self.last_name} ({self.status})"

    @property
    def full_name(self) -> str:
        """Returns the full name of the enquiring lead."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def type_display(self) -> str:
        """Returns human-readable choice label for enquiry type."""
        return dict(EnquiryTypeEnum.choices).get(self.type, self.type)

    @property
    def status_display(self) -> str:
        """Returns human-readable choice label for enquiry status."""
        return dict(EnquiryStatusEnum.choices).get(self.status, self.status)

    @property
    def notes_count(self) -> int:
        """Returns count of notes associated with the enquiry."""
        return len(self.notes) if isinstance(self.notes, list) else 0

