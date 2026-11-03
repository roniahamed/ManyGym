import uuid
from datetime import date
from decimal import Decimal
from typing import Optional, List, Dict, Any

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from apps.gyms.models import Gym, GymBlockedUser
from apps.access_control.models import GymStaffAssignment, StaffStatus
from apps.users.models import User
from apps.members.models import Member, MemberRequest
from apps.members.services.subscription_services import create_member_subscription
from apps.members.services.member_services import process_member_profile_photo
from apps.memberships.models import MembershipPlan
from common.enums import (
    MemberJoiningStatus,
    MemberRequestStatus,
    AudienceJoiningRequestEnum,
    AdminLogCategory,
    AdminLogActionType,
    LeadStageEnum,
    LeadSourceEnum,
)
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    ResourceConflictError,
    PermissionDeniedError,
)


@transaction.atomic
def create_member_request(
    user: User,
    gym_id: Any,
    interested_plan_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Submits a member joining request from an authenticated Manygym user to a gym.
    Enforces:
    - Gym exists, is published, not deactivated, not deleted.
    - GymSetting.who_can_send_joining_request is 'everyone'.
    - User is not blocked by gym.
    - User is not already an active member of this gym.
    - User does not already have a pending request.
    """
    if isinstance(gym_id, Gym):
        gym = gym_id
    else:
        try:
            gym_uuid = uuid.UUID(str(gym_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid gym ID.")

        try:
            gym = Gym.objects.select_related("settings").get(id=gym_uuid)
        except Gym.DoesNotExist:
            raise ResourceNotFoundError("Gym not found.")

    settings_obj = gym.get_settings()
    if settings_obj.is_deleted:
        raise ResourceNotFoundError("Gym not found.")
    if settings_obj.is_deactivated:
        raise DomainValidationError("This gym is currently deactivated.")

    is_owner_or_staff = (
        gym.owner_user_id == user.id
        or user.is_superuser
        or GymStaffAssignment.objects.filter(gym=gym, user=user, status=StaffStatus.ACTIVE).exists()
    )
    if not settings_obj.is_published and not is_owner_or_staff:
        raise ResourceNotFoundError("Gym not found.")

    # 1. Blocklist check
    if GymBlockedUser.objects.filter(gym=gym, user=user).exists():
        raise PermissionDeniedError("You have been blocked from sending joining requests to this gym.")

    # 2. Audience joining request setting check (jei sob gym er user request on kora thakbeh)
    if settings_obj.who_can_send_joining_request == AudienceJoiningRequestEnum.NO_ONE:
        raise PermissionDeniedError("This gym is not currently accepting member joining requests.")

    # 3. Already a member check
    if Member.objects.filter(gym=gym, user=user).exclude(joining_status="removed").exists():
        raise DomainValidationError("You are already a member of this gym.")

    # 4. Optional plan resolution
    plan_obj = None
    if interested_plan_id:
        try:
            plan_uuid = uuid.UUID(str(interested_plan_id))
            plan_obj = MembershipPlan.objects.filter(gym=gym, id=plan_uuid).first()
        except (ValueError, TypeError, AttributeError):
            pass

    # 5. Check if user already has an active pending MemberRequest
    existing_request = MemberRequest.objects.filter(
        gym=gym,
        user=user,
        status=MemberRequestStatus.PENDING,
    ).first()

    if existing_request:
        if plan_obj and not existing_request.interested_plan:
            existing_request.interested_plan = plan_obj
            existing_request.save(update_fields=["interested_plan"])
        return {
            "message": "Member joining request already submitted and pending review.",
            "gym_id": str(gym.id),
            "gym_name": gym.name,
            "status": MemberRequestStatus.PENDING,
            "request_id": str(existing_request.id),
            "created": False,
        }

    # 6. Create MemberRequest
    member_request = MemberRequest.objects.create(
        gym=gym,
        user=user,
        interested_plan=plan_obj,
        notes=notes.strip() if notes else None,
        status=MemberRequestStatus.PENDING,
    )

    # Maintain lead tracking for backward compatibility with sales pipeline
    lead_id_str = None
    try:
        from apps.leads.models import Lead
        from apps.leads.services.action_services import add_lead_note

        lead = Lead.objects.filter(
            gym=gym,
            email=user.email,
            stage__in=[LeadStageEnum.NEW, LeadStageEnum.CONTACTED, LeadStageEnum.VISIT_TRIAL_BOOKED],
        ).first()

        if not lead:
            lead = Lead.objects.create(
                gym=gym,
                first_name=user.first_name or "Applicant",
                last_name=user.last_name or "",
                email=user.email,
                phone=getattr(user, "phone", None) or "",
                interested_plan=plan_obj,
                stage=LeadStageEnum.NEW,
                source=LeadSourceEnum.WEBSITE,
            )
            if notes:
                add_lead_note(lead=lead, note_text=notes.strip())
        lead_id_str = str(lead.id)
    except Exception:
        pass

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        user_name = f"{user.first_name} {user.last_name}".strip() or user.email
        log_admin_action(
            gym=gym,
            actor=user,
            action="Create a member request",
            action_type=AdminLogActionType.CREATE_MEMBER_REQUEST,
            details=f"Received joining request from {user_name} ({user.email})",
            category=AdminLogCategory.MEMBER_REQUESTS,
            target_type="member_request",
            target_id=str(member_request.id),
        )
    except Exception:
        pass

    return {
        "message": "Member joining request sent successfully.",
        "gym_id": str(gym.id),
        "gym_name": gym.name,
        "status": MemberRequestStatus.PENDING,
        "request_id": str(member_request.id),
        "lead_id": lead_id_str,
        "created": True,
    }


def get_member_joining_request_status(user: User, gym_id: Any) -> Dict[str, Any]:
    """
    Returns user eligibility and current status for joining the specified gym.
    """
    if isinstance(gym_id, Gym):
        gym = gym_id
    else:
        try:
            gym_uuid = uuid.UUID(str(gym_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid gym ID.")

        try:
            gym = Gym.objects.select_related("settings").get(id=gym_uuid)
        except Gym.DoesNotExist:
            raise ResourceNotFoundError("Gym not found.")

    settings_obj = gym.get_settings()

    is_blocked = GymBlockedUser.objects.filter(gym=gym, user=user).exists()
    is_member = Member.objects.filter(gym=gym, user=user).exclude(joining_status="removed").exists()
    allows_requests = (
        not settings_obj.is_deleted
        and not settings_obj.is_deactivated
        and settings_obj.who_can_send_joining_request == AudienceJoiningRequestEnum.EVERYONE
        and not is_blocked
        and not is_member
    )

    pending_req = MemberRequest.objects.filter(
        gym=gym,
        user=user,
        status=MemberRequestStatus.PENDING,
    ).first()

    return {
        "gym_id": str(gym.id),
        "can_send_request": allows_requests and (pending_req is None),
        "is_member": is_member,
        "has_pending_request": pending_req is not None,
        "pending_request_id": str(pending_req.id) if pending_req else None,
        "is_blocked": is_blocked,
        "who_can_send_joining_request": settings_obj.who_can_send_joining_request,
    }


@transaction.atomic
def accept_member_request(
    request_id: uuid.UUID,
    gym: Gym,
    reviewer: User,
    plan_id: Optional[uuid.UUID] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    assigned_trainer_id: Optional[uuid.UUID] = None,
    extra_amenity_ids: Optional[List[uuid.UUID]] = None,
    initial_payment_amount: Optional[Decimal] = None,
    initial_payment_method: Optional[str] = None,
    initial_payment_date: Optional[date] = None,
    initial_payment_notes: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    profile_photo: Optional[Any] = None,
    profile_photo_url: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    date_of_birth: Optional[date] = None,
    sex: Optional[str] = None,
    nationality: Optional[str] = None,
    emergency_contact_name: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
    emergency_contact_relationship: Optional[str] = None,
    internal_notes: Optional[str] = None,
) -> Member:
    """
    Accepts a pending member request.
    The staff or admin provides the required membership details (plan, dates, trainer, initial payment, etc.).
    Creates an active Member directly linked to the user account (joining_status='joined').
    """
    try:
        member_request = (
            MemberRequest.objects.select_related("gym", "user", "interested_plan")
            .get(id=request_id, gym=gym)
        )
    except MemberRequest.DoesNotExist:
        raise ResourceNotFoundError("Member request not found.")

    if member_request.status != MemberRequestStatus.PENDING:
        raise ResourceConflictError(f"This member request has already been {member_request.status}.")

    applicant = member_request.user

    # Invariant: User must not already be an enrolled member
    if Member.objects.filter(gym=gym, user=applicant).exclude(joining_status="removed").exists():
        raise ResourceConflictError("This user is already an active member of this gym.")

    # 1. Demographic data resolution
    fn_clean = (first_name.strip() if first_name else "") or (applicant.first_name.strip() if applicant.first_name else "") or "Member"
    ln_clean = (last_name.strip() if last_name else "") or (applicant.last_name.strip() if applicant.last_name else "") or "-"
    email_clean = (email.strip().lower() if email else "") or (applicant.email.strip().lower() if applicant.email else "")

    if not email_clean or "@" not in email_clean:
        raise DomainValidationError("A valid email address is required to enroll a member.")

    if Member.objects.filter(gym=gym, email=email_clean).exclude(joining_status="removed").exists():
        raise ResourceConflictError(f"A member with email '{email_clean}' already exists in this gym.")

    # 2. Trainer assignment validation
    trainer_assignment = None
    if assigned_trainer_id:
        try:
            trainer_assignment = GymStaffAssignment.objects.select_related("user").get(
                id=assigned_trainer_id,
                gym=gym,
                status=StaffStatus.ACTIVE,
            )
        except GymStaffAssignment.DoesNotExist:
            raise DomainValidationError("Assigned trainer does not exist or is not an active staff member of this gym.")

    # 3. Resolve profile photo
    user_avatar = getattr(applicant, "avatar_url", None) or getattr(applicant, "profile_photo_url", None)
    resolved_photo = process_member_profile_photo(
        photo_file=profile_photo,
        photo_url=profile_photo_url or user_avatar,
    )

    phone_clean = (phone.strip() if phone else "") or getattr(applicant, "phone", None) or None

    # 4. Construct internal notes
    notes_parts = []
    if internal_notes and internal_notes.strip():
        notes_parts.append(internal_notes.strip())
    if member_request.notes:
        notes_parts.append(f"Request Note: {member_request.notes.strip()}")
    final_internal_notes = " | ".join(notes_parts) if notes_parts else None

    # 5. Create Member instance linked directly to applicant user
    member = Member(
        gym=gym,
        user=applicant,
        first_name=fn_clean,
        last_name=ln_clean,
        email=email_clean,
        phone=phone_clean,
        profile_photo_url=resolved_photo,
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
        internal_notes=final_internal_notes,
        joining_status=MemberJoiningStatus.JOINED,
    )
    try:
        member.full_clean()
        member.save()
    except ValidationError as exc:
        raise DomainValidationError(str(exc))

    # 6. Initialize subscription if plan specified
    target_plan_id = plan_id or (member_request.interested_plan_id if member_request.interested_plan else None)
    if target_plan_id:
        try:
            plan = MembershipPlan.objects.get(id=target_plan_id, gym=gym)
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

    # 7. Update MemberRequest status
    member_request.status = MemberRequestStatus.ACCEPTED
    member_request.created_member = member
    member_request.reviewed_by = reviewer
    member_request.reviewed_at = timezone.now()
    member_request.save(update_fields=["status", "created_member", "reviewed_by", "reviewed_at", "updated_at"])

    # 8. Synchronize Lead if exists
    try:
        from apps.leads.models import Lead
        lead = Lead.objects.filter(
            gym=gym,
            email=email_clean,
            stage__in=[LeadStageEnum.NEW, LeadStageEnum.CONTACTED, LeadStageEnum.VISIT_TRIAL_BOOKED],
        ).first()
        if lead:
            lead.converted_member = member
            lead.stage = LeadStageEnum.JOINED
            lead.save(update_fields=["converted_member", "stage", "updated_at"])
    except Exception:
        pass

    # 9. Audit Logging
    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        log_admin_action(
            gym=gym,
            actor=reviewer,
            action="Accept member request",
            action_type=AdminLogActionType.ACCEPT_MEMBER_REQUEST,
            details=f"Accepted member request for {member.full_name} ({member.email})",
            category=AdminLogCategory.MEMBER_REQUESTS,
            target_type="member_request",
            target_id=str(member_request.id),
        )
        log_admin_action(
            gym=gym,
            actor=reviewer,
            action="Create a member",
            action_type=AdminLogActionType.CREATE_MEMBER,
            details=f"Created member {member.full_name} ({member.email}) from join request",
            category=AdminLogCategory.MEMBERS,
            target_type="member",
            target_id=str(member.id),
        )
    except Exception:
        pass

    return member


@transaction.atomic
def reject_member_request(
    request_id: uuid.UUID,
    gym: Gym,
    reviewer: User,
    rejection_reason: Optional[str] = None,
) -> MemberRequest:
    """
    Rejects a pending member request.
    """
    try:
        member_request = (
            MemberRequest.objects.select_related("gym", "user")
            .get(id=request_id, gym=gym)
        )
    except MemberRequest.DoesNotExist:
        raise ResourceNotFoundError("Member request not found.")

    if member_request.status != MemberRequestStatus.PENDING:
        raise ResourceConflictError(f"This member request has already been {member_request.status}.")

    member_request.status = MemberRequestStatus.REJECTED
    member_request.rejection_reason = rejection_reason.strip() if rejection_reason else None
    member_request.reviewed_by = reviewer
    member_request.reviewed_at = timezone.now()
    member_request.save(update_fields=["status", "rejection_reason", "reviewed_by", "reviewed_at", "updated_at"])

    # Synchronize lead if exists
    try:
        from apps.leads.models import Lead
        lead = Lead.objects.filter(
            gym=gym,
            email=member_request.user.email,
            stage=LeadStageEnum.NEW,
        ).first()
        if lead:
            lead.stage = LeadStageEnum.NOT_JOINING
            lead.save(update_fields=["stage", "updated_at"])
    except Exception:
        pass

    try:
        from apps.gyms.services.admin_log_services import log_admin_action
        log_admin_action(
            gym=gym,
            actor=reviewer,
            action="Reject member request",
            action_type=AdminLogActionType.REJECT_MEMBER_REQUEST,
            details=f"Rejected member request from {member_request.user.email}",
            category=AdminLogCategory.MEMBER_REQUESTS,
            target_type="member_request",
            target_id=str(member_request.id),
        )
    except Exception:
        pass

    return member_request


@transaction.atomic
def cancel_member_request(
    request_id: uuid.UUID,
    user: User,
) -> MemberRequest:
    """
    Allows a Manygym user to cancel their own pending join request.
    """
    try:
        member_request = MemberRequest.objects.select_related("gym").get(
            id=request_id,
            user=user,
        )
    except MemberRequest.DoesNotExist:
        raise ResourceNotFoundError("Member request not found.")

    if member_request.status != MemberRequestStatus.PENDING:
        raise ResourceConflictError(f"Cannot cancel a request that has already been {member_request.status}.")

    member_request.status = MemberRequestStatus.CANCELLED
    member_request.save(update_fields=["status", "updated_at"])

    return member_request

