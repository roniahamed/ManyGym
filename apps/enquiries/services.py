import uuid
from typing import Optional, List, Any
from django.db import transaction
from django.utils import timezone
from apps.enquiries.models import Enquiry
from apps.users.models import User
from apps.gyms.models import Gym
from common.enums import EnquiryTypeEnum, EnquiryStatusEnum
from common.exceptions import DomainValidationError, ResourceNotFoundError


@transaction.atomic
def create_enquiry(
    first_name: str,
    last_name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    manygym_user: Optional[Any] = None,
    gym: Optional[Any] = None,
    type: str = EnquiryTypeEnum.GENERAL_INQUIRY,
    status: str = EnquiryStatusEnum.NEW,
    summary: str = "",
    notes: Optional[List[str]] = None,
) -> Enquiry:
    """
    Creates a new Enquiry record after enforcing mandatory contact and field validations.
    """
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    email = (email or "").strip().lower() or None
    phone = (phone or "").strip() or None

    if not first_name:
        raise DomainValidationError("First name is required.")
    if not last_name:
        raise DomainValidationError("Last name is required.")
    if not email and not phone:
        raise DomainValidationError("Either Email or Phone number is mandatory.")

    # Resolve Manygym User if provided
    user_obj = None
    if manygym_user:
        if isinstance(manygym_user, User):
            user_obj = manygym_user
        else:
            try:
                user_uuid = uuid.UUID(str(manygym_user))
                user_obj = User.objects.get(id=user_uuid)
            except (ValueError, TypeError, AttributeError, User.DoesNotExist):
                raise DomainValidationError("Invalid manygym_user ID.")

    # Resolve Gym if provided
    gym_obj = None
    if gym:
        if isinstance(gym, Gym):
            gym_obj = gym
        else:
            try:
                gym_uuid = uuid.UUID(str(gym))
                gym_obj = Gym.objects.get(id=gym_uuid)
            except (ValueError, TypeError, AttributeError, Gym.DoesNotExist):
                raise DomainValidationError("Invalid gym ID.")

    # Normalize type & status
    normalized_type = str(type).strip().upper() if type else EnquiryTypeEnum.GENERAL_INQUIRY
    valid_types = {c.value for c in EnquiryTypeEnum}
    if normalized_type not in valid_types:
        normalized_type = EnquiryTypeEnum.GENERAL_INQUIRY

    normalized_status = str(status).strip().upper() if status else EnquiryStatusEnum.NEW
    status_alias_map = {
        "BOOK": EnquiryStatusEnum.BOOKED,
        "BOOKED": EnquiryStatusEnum.BOOKED,
        "VISIT": EnquiryStatusEnum.VISIT,
        "CONTACTED": EnquiryStatusEnum.CONTACTED,
        "NEW": EnquiryStatusEnum.NEW,
    }
    normalized_status = status_alias_map.get(normalized_status, EnquiryStatusEnum.NEW)

    clean_notes = []
    if notes is not None:
        if isinstance(notes, list):
            clean_notes = [str(n).strip() for n in notes if str(n).strip()]
        elif isinstance(notes, str) and notes.strip():
            clean_notes = [notes.strip()]

    enquiry = Enquiry.objects.create(
        gym=gym_obj,
        manygym_user=user_obj,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        type=normalized_type,
        status=normalized_status,
        summary=(summary or "").strip(),
        notes=clean_notes,
    )
    return enquiry


@transaction.atomic
def update_enquiry(
    enquiry_id,
    gym_id: Optional[str] = None,
    **kwargs: Any,
) -> Enquiry:
    """
    Updates an existing Enquiry entity.
    """
    from apps.enquiries.selectors import get_enquiry_by_id

    enquiry = get_enquiry_by_id(enquiry_id=enquiry_id, gym_id=gym_id)
    update_fields = []

    if "first_name" in kwargs and kwargs["first_name"] is not None:
        fn = str(kwargs["first_name"]).strip()
        if not fn:
            raise DomainValidationError("First name cannot be empty.")
        enquiry.first_name = fn
        update_fields.append("first_name")

    if "last_name" in kwargs and kwargs["last_name"] is not None:
        ln = str(kwargs["last_name"]).strip()
        if not ln:
            raise DomainValidationError("Last name cannot be empty.")
        enquiry.last_name = ln
        update_fields.append("last_name")

    if "email" in kwargs:
        em = str(kwargs["email"]).strip().lower() if kwargs["email"] else None
        enquiry.email = em
        update_fields.append("email")

    if "phone" in kwargs:
        ph = str(kwargs["phone"]).strip() if kwargs["phone"] else None
        enquiry.phone = ph
        update_fields.append("phone")

    # Re-validate that either email or phone is present
    if "email" in kwargs or "phone" in kwargs:
        if not enquiry.email and not enquiry.phone:
            raise DomainValidationError("Either Email or Phone number is mandatory.")

    if "manygym_user_id" in kwargs:
        uid = kwargs["manygym_user_id"]
        if uid:
            try:
                user_uuid = uuid.UUID(str(uid))
                enquiry.manygym_user = User.objects.get(id=user_uuid)
            except (ValueError, TypeError, AttributeError, User.DoesNotExist):
                raise DomainValidationError("Invalid manygym_user ID.")
        else:
            enquiry.manygym_user = None
        update_fields.append("manygym_user")

    if "type" in kwargs and kwargs["type"] is not None:
        raw_type = str(kwargs["type"]).strip().upper()
        if raw_type in {c.value for c in EnquiryTypeEnum}:
            enquiry.type = raw_type
            update_fields.append("type")
        else:
            raise DomainValidationError(f"Invalid enquiry type '{kwargs['type']}'.")

    if "status" in kwargs and kwargs["status"] is not None:
        raw_status = str(kwargs["status"]).strip().upper()
        status_alias_map = {
            "BOOK": EnquiryStatusEnum.BOOKED,
            "BOOKED": EnquiryStatusEnum.BOOKED,
            "VISIT": EnquiryStatusEnum.VISIT,
            "CONTACTED": EnquiryStatusEnum.CONTACTED,
            "NEW": EnquiryStatusEnum.NEW,
        }
        if raw_status in status_alias_map:
            enquiry.status = status_alias_map[raw_status]
            update_fields.append("status")
        else:
            raise DomainValidationError(f"Invalid enquiry status '{kwargs['status']}'.")

    if "summary" in kwargs and kwargs["summary"] is not None:
        enquiry.summary = str(kwargs["summary"]).strip()
        update_fields.append("summary")

    if "notes" in kwargs and kwargs["notes"] is not None:
        raw_notes = kwargs["notes"]
        if isinstance(raw_notes, list):
            enquiry.notes = [str(n).strip() for n in raw_notes if str(n).strip()]
        elif isinstance(raw_notes, str) and raw_notes.strip():
            enquiry.notes = [raw_notes.strip()]
        update_fields.append("notes")

    if "append_note" in kwargs and kwargs["append_note"]:
        note_str = str(kwargs["append_note"]).strip()
        if note_str:
            current_notes = list(enquiry.notes or [])
            current_notes.append(note_str)
            enquiry.notes = current_notes
            if "notes" not in update_fields:
                update_fields.append("notes")

    if update_fields:
        enquiry.updated_at = timezone.now()
        update_fields.append("updated_at")
        enquiry.save(update_fields=update_fields)

    return enquiry


@transaction.atomic
def delete_enquiry(enquiry_id, gym_id: Optional[str] = None) -> bool:
    """
    Deletes an Enquiry entity.
    """
    from apps.enquiries.selectors import get_enquiry_by_id

    enquiry = get_enquiry_by_id(enquiry_id=enquiry_id, gym_id=gym_id)
    enquiry.delete()
    return True


@transaction.atomic
def add_enquiry_note(enquiry_id, note_text: str, gym_id: Optional[str] = None) -> Enquiry:
    """
    Appends a new note string to an existing enquiry.
    """
    note_clean = (note_text or "").strip()
    if not note_clean:
        raise DomainValidationError("Note text cannot be empty.")
    return update_enquiry(enquiry_id=enquiry_id, gym_id=gym_id, append_note=note_clean)

