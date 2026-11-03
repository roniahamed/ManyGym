import logging
import uuid
import secrets
from datetime import date
from decimal import Decimal
from typing import List, Optional, Any
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from apps.gyms.models import Gym, GymBlockedUser
from apps.users.models import User
from apps.access_control.models import GymStaffAssignment
from apps.memberships.models import MembershipPlan
from apps.members.models import (
    Member,
    MemberPayment,
)
from apps.members.tasks import send_member_invitation_email
from apps.members.services.subscription_services import create_member_subscription
from common.enums import MemberJoiningStatus
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    ResourceConflictError,
)

logger = logging.getLogger(__name__)


def process_member_profile_photo(
    photo_file: Optional[Any] = None,
    photo_url: Optional[str] = None,
) -> Optional[str]:
    """
    Saves and optimizes member profile photo using central MediaOptimizerService.
    """
    from common.media import MediaOptimizerService
    return MediaOptimizerService.process_image_upload(
        file=photo_file,
        url=photo_url,
        subfolder="members/profiles",
        max_dims=(800, 800),
        thumb_dims=(200, 200),
    )


@transaction.atomic
def create_member(
    gym: Gym,
    first_name: str,
    last_name: str,
    email: str,
    phone: Optional[str] = None,
    profile_photo_url: Optional[str] = None,
    profile_photo: Optional[Any] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    date_of_birth: Optional[date] = None,
    sex: Optional[str] = None,
    nationality: Optional[str] = None,
    emergency_contact_name: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
    emergency_contact_relationship: Optional[str] = None,
    assigned_trainer_id: Optional[uuid.UUID] = None,
    internal_notes: Optional[str] = None,
    plan_id: Optional[uuid.UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    extra_amenity_ids: Optional[List[uuid.UUID]] = None,
    initial_payment_amount: Optional[Decimal] = None,
    initial_payment_method: Optional[str] = None,
    initial_payment_date: Optional[date] = None,
    initial_payment_notes: Optional[str] = None,
) -> Member:
    """
    Creates a new gym member record with onboarding invitation and optional initial subscription.
    """
    # 1. Clean and validate inputs
    fn_clean = first_name.strip() if first_name else ""
    ln_clean = last_name.strip() if last_name else ""
    email_clean = email.strip().lower() if email else ""

    if not fn_clean:
        raise DomainValidationError("Member first name is required.")
    if not ln_clean:
        raise DomainValidationError("Member last name is required.")
    if not email_clean or "@" not in email_clean:
        raise DomainValidationError("A valid member email address is required.")

    if Member.objects.filter(gym=gym, email=email_clean).exists():
        raise ResourceConflictError(f"A member with email '{email_clean}' already exists in this gym.")

    if GymBlockedUser.objects.filter(gym=gym, user__email=email_clean).exists():
        raise DomainValidationError(f"User with email '{email_clean}' is currently blocked by this gym.")

    # 2. Validate trainer assignment if provided
    trainer_assignment = None
    if assigned_trainer_id:
        try:
            trainer_assignment = GymStaffAssignment.objects.select_related("user").get(
                id=assigned_trainer_id,
                gym=gym,
            )
        except GymStaffAssignment.DoesNotExist:
            raise DomainValidationError("Assigned trainer does not exist or is not a staff member of this gym.")

    # 3. Generate onboarding invitation token
    invitation_token = secrets.token_urlsafe(32)

    resolved_photo_url = process_member_profile_photo(
        photo_file=profile_photo,
        photo_url=profile_photo_url,
    )

    member = Member(
        gym=gym,
        first_name=fn_clean,
        last_name=ln_clean,
        email=email_clean,
        phone=phone.strip() if phone else None,
        profile_photo_url=resolved_photo_url,
        address=address.strip() if address else None,
        city=city.strip() if city else None,
        country=country.strip() if country else None,
        date_of_birth=date_of_birth,
        sex=sex.strip() if sex else None,
        nationality=nationality.strip() if nationality else None,
        emergency_contact_name=emergency_contact_name.strip() if emergency_contact_name else None,
        emergency_contact_phone=emergency_contact_phone.strip() if emergency_contact_phone else None,
        emergency_contact_relationship=emergency_contact_relationship.strip() if emergency_contact_relationship else None,
        assigned_trainer=trainer_assignment,
        internal_notes=internal_notes.strip() if internal_notes else None,
        joining_status=MemberJoiningStatus.SENT_INVITATION,
        invitation_token=invitation_token,
        invitation_sent_at=timezone.now(),
    )
    try:
        member.full_clean()
        member.save()
    except ValidationError as exc:
        raise DomainValidationError(str(exc))

    # 4. Initialize initial subscription if plan_id is provided
    if plan_id:
        try:
            plan = MembershipPlan.objects.get(id=plan_id, gym=gym)
        except MembershipPlan.DoesNotExist:
            raise DomainValidationError("The selected membership plan does not exist in this gym.")

        sub_start_date = start_date or timezone.now().date()
        create_member_subscription(
            member=member,
            plan=plan,
            start_date=sub_start_date,
            end_date=end_date,
            extra_amenity_ids=extra_amenity_ids,
            initial_payment_amount=initial_payment_amount,
            initial_payment_method=initial_payment_method,
            initial_payment_date=initial_payment_date or sub_start_date,
            initial_payment_notes=initial_payment_notes,
        )

    # 5. Dispatch async invitation email
    send_member_invitation_email.delay(
        member_id=str(member.id),
        email=member.email,
        first_name=member.first_name,
        gym_name=gym.name,
        token=invitation_token,
    )

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        log_admin_action(
            gym=gym,
            action="Create a member",
            action_type=AdminLogActionType.CREATE_MEMBER,
            details=f"Created member {member.first_name} {member.last_name} ({member.email})",
            category=AdminLogCategory.MEMBERS,
            target_type="member",
            target_id=str(member.id),
        )
    except Exception:
        pass

    return member


@transaction.atomic
def resend_member_invitation(member_id: uuid.UUID, gym: Gym) -> Member:
    """
    Regenerates invitation token and re-dispatches onboarding confirmation email.
    Optimized with column projection.
    """
    try:
        member = Member.objects.only(
            "id", "gym_id", "joining_status", "email", "first_name", "invitation_token", "invitation_sent_at"
        ).get(id=member_id, gym=gym)
    except Member.DoesNotExist:
        raise ResourceNotFoundError(f"Member '{member_id}' not found.")

    if member.joining_status == MemberJoiningStatus.JOINED:
        raise DomainValidationError("Member has already completed onboarding and activated their account.")

    new_token = secrets.token_urlsafe(32)
    member.invitation_token = new_token
    member.invitation_sent_at = timezone.now()
    member.save(update_fields=["invitation_token", "invitation_sent_at", "updated_at"])

    send_member_invitation_email.delay(
        member_id=str(member.id),
        email=member.email,
        first_name=member.first_name,
        gym_name=gym.name,
        token=new_token,
    )
    return member


@transaction.atomic
def accept_member_invitation(token: str, user: User) -> Member:
    """
    Validates invitation token, links user account, and transitions status to 'joined'.
    """
    token_clean = token.strip() if token else ""
    if not token_clean:
        raise DomainValidationError("An invitation token is required.")

    try:
        member = (
            Member.objects.select_related("gym")
            .only("id", "gym_id", "user_id", "joining_status", "invitation_token", "gym__id")
            .get(invitation_token=token_clean)
        )
    except Member.DoesNotExist:
        raise DomainValidationError("Invalid or expired invitation token.")

    if member.joining_status == MemberJoiningStatus.JOINED:
        raise DomainValidationError("This invitation has already been accepted.")

    member.user = user
    member.joining_status = MemberJoiningStatus.JOINED
    member.invitation_token = None
    member.save(update_fields=["user", "joining_status", "invitation_token", "updated_at"])

    # Auto-follow connected gym by default (member can unfollow later)
    from apps.gyms.services import auto_follow_gym_for_member
    auto_follow_gym_for_member(user=user, gym=member.gym)

    return member


@transaction.atomic
def update_member_profile(
    member_id: uuid.UUID,
    gym: Gym,
    **update_fields: Any,
) -> Member:
    """
    Updates member profile, demographics, emergency contact, or trainer assignment.
    """
    try:
        member = Member.objects.get(id=member_id, gym=gym)
    except Member.DoesNotExist:
        raise ResourceNotFoundError(f"Member '{member_id}' not found.")

    if "profile_photo" in update_fields or "profile_photo_url" in update_fields:
        photo_file = update_fields.pop("profile_photo", None)
        photo_url = update_fields.pop("profile_photo_url", None)
        resolved_photo_url = process_member_profile_photo(
            photo_file=photo_file,
            photo_url=photo_url,
        )
        if resolved_photo_url is not None or photo_file is not None or photo_url is not None:
            member.profile_photo_url = resolved_photo_url

    if "assigned_trainer_id" in update_fields:
        trainer_id = update_fields.pop("assigned_trainer_id")
        if trainer_id is None:
            member.assigned_trainer = None
        else:
            try:
                assignment = GymStaffAssignment.objects.get(id=trainer_id, gym=gym)
                member.assigned_trainer = assignment
            except GymStaffAssignment.DoesNotExist:
                raise DomainValidationError("Assigned trainer does not belong to this gym.")

    for field, val in update_fields.items():
        if hasattr(member, field):
            setattr(member, field, val)

    try:
        member.full_clean()
        member.save()
    except ValidationError as exc:
        raise DomainValidationError(str(exc))

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        log_admin_action(
            gym=gym,
            action="Update a member",
            action_type=AdminLogActionType.UPDATE_MEMBER,
            details=f"Updated member {member.first_name} {member.last_name} ({member.email})",
            category=AdminLogCategory.MEMBERS,
            target_type="member",
            target_id=str(member.id),
        )
    except Exception:
        pass

    return member


@transaction.atomic
def delete_member(member_id: uuid.UUID, gym: Gym) -> None:
    """
    Deletes a member. If subscriptions with payments exist, archives/cancels them instead.
    """
    try:
        member = Member.objects.get(id=member_id, gym=gym)
    except Member.DoesNotExist:
        raise ResourceNotFoundError(f"Member '{member_id}' not found.")

    has_payments = MemberPayment.objects.filter(member_subscription__member=member).exists()
    if has_payments:
        raise ResourceConflictError("Cannot permanently delete a member with payment ledger history. Cancel their active subscription instead.")

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        from common.enums import AdminLogCategory, AdminLogActionType
        log_admin_action(
            gym=gym,
            action="Delete a member",
            action_type=AdminLogActionType.DELETE_MEMBER,
            details=f"Deleted member {member.first_name} {member.last_name} ({member.email})",
            category=AdminLogCategory.MEMBERS,
            target_type="member",
            target_id=str(member.id),
        )
    except Exception:
        pass

    member.delete()
