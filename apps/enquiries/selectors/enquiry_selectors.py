import uuid
from typing import Optional, Union
from django.db.models import QuerySet, Q

from apps.enquiries.models import Enquiry
from common.exceptions import ResourceNotFoundError, DomainValidationError


def list_enquiries(
    gym_id: Optional[Union[str, uuid.UUID]] = None,
    status: Optional[str] = None,
    type: Optional[str] = None,
    search: Optional[str] = None,
    user_id: Optional[Union[str, uuid.UUID]] = None,
) -> QuerySet[Enquiry]:
    """
    Retrieves filtered and search-optimized QuerySet of Enquiry entities.
    Eagerly loads related manygym_user, profile, and gym to prevent N+1 queries.
    """
    qs = Enquiry.objects.select_related("manygym_user", "manygym_user__profile", "gym")

    if gym_id:
        try:
            gym_uuid = gym_id if isinstance(gym_id, uuid.UUID) else uuid.UUID(str(gym_id))
            qs = qs.filter(gym_id=gym_uuid)
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid gym_id format.")

    if user_id:
        try:
            user_uuid = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id))
            qs = qs.filter(manygym_user_id=user_uuid)
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid user_id format.")

    if status and str(status).strip():
        qs = qs.filter(status=str(status).strip().upper())

    if type and str(type).strip():
        qs = qs.filter(type=str(type).strip().upper())

    if search and str(search).strip():
        term = str(search).strip()
        qs = qs.filter(
            Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(email__icontains=term)
            | Q(phone__icontains=term)
            | Q(summary__icontains=term)
        )

    return qs.order_by("-created_at")


def get_enquiry_by_id(
    enquiry_id: Union[str, uuid.UUID],
    gym_id: Optional[Union[str, uuid.UUID]] = None,
) -> Enquiry:
    """
    Retrieves a single Enquiry entity by UUID with related relations.
    """
    try:
        enquiry_uuid = enquiry_id if isinstance(enquiry_id, uuid.UUID) else uuid.UUID(str(enquiry_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid enquiry_id format.")

    qs = Enquiry.objects.select_related("manygym_user", "manygym_user__profile", "gym")
    if gym_id:
        try:
            gym_uuid = gym_id if isinstance(gym_id, uuid.UUID) else uuid.UUID(str(gym_id))
            qs = qs.filter(gym_id=gym_uuid)
        except (ValueError, TypeError, AttributeError):
            pass

    enquiry = qs.filter(id=enquiry_uuid).first()
    if not enquiry:
        raise ResourceNotFoundError("Enquiry not found.")

    return enquiry
