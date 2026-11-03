import uuid
from typing import Optional, Tuple
from django.db import transaction
from apps.gyms.models import Gym, GymFollow, GymBlockedUser
from apps.users.models import User
from common.exceptions import DomainValidationError, ResourceNotFoundError, PermissionDeniedError


@transaction.atomic
def follow_gym(user: User, gym_id) -> Tuple[GymFollow, bool]:
    """
    Enables an authenticated user to follow a Gym entity.
    Checks:
    - Target gym exists, is not deleted, and is not deactivated.
    - User is not blocked by the gym.
    Returns:
    - (GymFollow instance, created: bool)
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
    if settings_obj.is_deleted or settings_obj.is_deactivated:
        raise DomainValidationError("This gym is currently inactive or unavailable.")

    # Check if user is blocked by gym
    if GymBlockedUser.objects.filter(gym=gym, user=user).exists():
        raise PermissionDeniedError("You are blocked from following this gym.")

    follow_instance, created = GymFollow.objects.get_or_create(
        user=user,
        gym=gym,
    )
    return follow_instance, created


@transaction.atomic
def unfollow_gym(user: User, gym_id) -> bool:
    """
    Unfollows a gym previously followed by user.
    """
    if isinstance(gym_id, Gym):
        gym_uuid = gym_id.id
    else:
        try:
            gym_uuid = uuid.UUID(str(gym_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid gym ID.")

    deleted_count, _ = GymFollow.objects.filter(user=user, gym_id=gym_uuid).delete()
    if deleted_count == 0:
        raise ResourceNotFoundError("You are not currently following this gym.")

    return True


def auto_follow_gym_for_member(user: User, gym: Gym) -> Optional[GymFollow]:
    """
    Automatically follows a gym when a member connects their user account.
    Gym members can unfollow later at their own discretion.
    Uses single-query atomic insert with ON CONFLICT DO NOTHING to eliminate savepoints and extra queries.
    """
    if not user or not gym:
        return None
    created = GymFollow.objects.bulk_create([GymFollow(user=user, gym=gym)], ignore_conflicts=True)
    return created[0] if created else None


@transaction.atomic
def send_member_joining_request(
    user: User,
    gym_id,
    interested_plan_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """
    Submits a member joining request from an authenticated Manygym user to a gym.
    Enforces:
    - Gym exists and is not deleted.
    - Gym is not deactivated.
    - User is not blocked in GymBlockedUser.
    - GymSetting.who_can_send_joining_request is not NO_ONE.
    - User is not already an active member of this gym.
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

    # 1. Blocklist check
    if GymBlockedUser.objects.filter(gym=gym, user=user).exists():
        raise PermissionDeniedError("You have been blocked from sending joining requests to this gym.")

    # 2. Audience joining request setting check
    from common.enums import AudienceJoiningRequestEnum
    if settings_obj.who_can_send_joining_request == AudienceJoiningRequestEnum.NO_ONE:
        raise PermissionDeniedError("This gym is not currently accepting member joining requests.")

    # 3. Already a member check
    from apps.members.models import Member
    if Member.objects.filter(gym=gym, user=user).exclude(joining_status="removed").exists():
        raise DomainValidationError("You are already a member of this gym.")

    # 4. Optional plan resolution
    plan_obj = None
    if interested_plan_id:
        from apps.memberships.models import MembershipPlan
        try:
            plan_uuid = uuid.UUID(str(interested_plan_id))
            plan_obj = MembershipPlan.objects.filter(gym=gym, id=plan_uuid).first()
        except (ValueError, TypeError, AttributeError):
            pass

    # 5. Check if user already has an active pending request in leads
    from apps.leads.models import Lead
    from common.enums import LeadStageEnum, LeadSourceEnum
    existing_lead = Lead.objects.filter(
        gym=gym,
        email=user.email,
        stage__in=[LeadStageEnum.NEW, LeadStageEnum.CONTACTED, LeadStageEnum.VISIT_TRIAL_BOOKED],
    ).first()

    if existing_lead:
        if plan_obj and not existing_lead.interested_plan:
            existing_lead.interested_plan = plan_obj
            existing_lead.save(update_fields=["interested_plan"])
        return {
            "message": "Member joining request already submitted and pending review.",
            "gym_id": str(gym.id),
            "gym_name": gym.name,
            "status": "pending",
            "lead_id": str(existing_lead.id),
            "created": False,
        }

    # Create new lead representing this joining request
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
        from apps.leads.services.action_services import add_lead_note
        add_lead_note(lead=lead, note_text=notes.strip())

    return {
        "message": "Member joining request sent successfully.",
        "gym_id": str(gym.id),
        "gym_name": gym.name,
        "status": "pending",
        "lead_id": str(lead.id),
        "created": True,
    }


def get_member_joining_request_status(user: User, gym_id) -> dict:
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
    from common.enums import AudienceJoiningRequestEnum
    from apps.members.models import Member
    from apps.leads.models import Lead
    from common.enums import LeadStageEnum

    is_blocked = GymBlockedUser.objects.filter(gym=gym, user=user).exists()
    is_member = Member.objects.filter(gym=gym, user=user).exclude(joining_status="removed").exists()
    allows_requests = (
        not settings_obj.is_deleted
        and not settings_obj.is_deactivated
        and settings_obj.who_can_send_joining_request == AudienceJoiningRequestEnum.EVERYONE
        and not is_blocked
        and not is_member
    )
    has_pending = Lead.objects.filter(
        gym=gym,
        email=user.email,
        stage__in=[LeadStageEnum.NEW, LeadStageEnum.CONTACTED, LeadStageEnum.VISIT_TRIAL_BOOKED],
    ).exists()

    return {
        "gym_id": str(gym.id),
        "can_send_request": allows_requests and not has_pending,
        "is_member": is_member,
        "has_pending_request": has_pending,
        "is_blocked": is_blocked,
        "who_can_send_joining_request": settings_obj.who_can_send_joining_request,
    }
