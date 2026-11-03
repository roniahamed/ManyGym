from datetime import date
from decimal import Decimal
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile
from apps.gyms.models import GymBlockedUser
from apps.gyms.services import create_gym, update_gym_settings
from apps.members.models import Member, MemberRequest, MemberSubscription, MemberPayment
from apps.memberships.models import MembershipPlan
from apps.access_control.models import GymStaffAssignment, StaffStatus, Role, Permission
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    AudienceJoiningRequestEnum,
    MemberRequestStatus,
    MemberJoiningStatus,
    MembershipStatusEnum,
    PaymentStatusEnum,
    PaymentMethodEnum,
)


def get_error_message(response):
    if isinstance(response.data, dict):
        return response.data.get("message") or response.data.get("detail") or str(response.data)
    return str(response.data)


def make_client(user):
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def owner_user(db):
    user = User.objects.create_user(
        email="owner.alice@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, date_of_birth=date(1990, 1, 1))
    return user


@pytest.fixture
def outsider_adult_user(db):
    user = User.objects.create_user(
        email="adult.outsider@example.com",
        password="SecurePassword123!",
        first_name="Charlie",
        last_name="Adult",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, date_of_birth=date(2000, 3, 20))
    return user


@pytest.fixture
def member_user(db):
    user = User.objects.create_user(
        email="member.bob@example.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Member",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, date_of_birth=date(1995, 5, 15))
    return user


@pytest.fixture
def staff_user(db):
    user = User.objects.create_user(
        email="staff.sam@example.com",
        password="SecurePassword123!",
        first_name="Sam",
        last_name="Staff",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, date_of_birth=date(1992, 8, 10))
    return user


@pytest.fixture
def test_gym(owner_user):
    return create_gym(owner_user=owner_user, name="Iron Paradise")


@pytest.fixture
def owner_client(owner_user):
    return make_client(owner_user)


@pytest.fixture
def outsider_client(outsider_adult_user):
    return make_client(outsider_adult_user)


@pytest.fixture
def member_client(member_user):
    return make_client(member_user)


@pytest.fixture
def active_member(test_gym, member_user):
    return Member.objects.create(
        gym=test_gym,
        user=member_user,
        first_name=member_user.first_name,
        last_name=member_user.last_name,
        email=member_user.email,
        joining_status=MemberJoiningStatus.JOINED,
    )


@pytest.fixture
def plan(test_gym):
    from common.enums import PlanStatusEnum, PlanTypeEnum, DurationUnitEnum
    return MembershipPlan.objects.create(
        gym=test_gym,
        name="Gold VIP Monthly",
        price=Decimal("150.00"),
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )


@pytest.fixture
def staff_client(test_gym, staff_user):
    """Staff member with members:read and members:edit permissions."""
    role = Role.objects.create(gym=test_gym, name="FrontDeskManager")
    p_read, _ = Permission.objects.get_or_create(topic="Members", scope_code="members:read", name="Read Members")
    p_edit, _ = Permission.objects.get_or_create(topic="Members", scope_code="members:edit", name="Edit Members")
    role.permissions.add(p_read, p_edit)

    GymStaffAssignment.objects.create(
        gym=test_gym,
        user=staff_user,
        role=role,
        status=StaffStatus.ACTIVE,
    )
    return make_client(staff_user)


@pytest.mark.django_db
class TestMemberJoiningRequestSubmission:

    def test_user_can_submit_request_when_enabled(self, outsider_client, test_gym, outsider_adult_user):
        """User can submit request when gym has user requests enabled (who_can_send_joining_request=everyone)."""
        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        res = outsider_client.post(url, {}, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["status"] == "pending"
        assert res.data["gym_id"] == str(test_gym.id)
        assert res.data["created"] is True

        # Verify DB record
        req = MemberRequest.objects.get(gym=test_gym, user=outsider_adult_user)
        assert req.status == MemberRequestStatus.PENDING
        assert req.notes is None

    def test_user_can_submit_request_with_notes_and_plan(self, outsider_client, test_gym, outsider_adult_user, plan):
        """User just submits request with optional note and interested plan."""
        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        payload = {
            "interested_plan_id": str(plan.id),
            "notes": "I would love to join your morning cardio batches.",
        }
        res = outsider_client.post(url, payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["status"] == "pending"

        req = MemberRequest.objects.get(gym=test_gym, user=outsider_adult_user)
        assert req.interested_plan == plan
        assert "morning cardio" in req.notes

    def test_duplicate_pending_request_returns_already_submitted(self, outsider_client, test_gym):
        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        res1 = outsider_client.post(url, {}, format="json")
        assert res1.status_code == status.HTTP_201_CREATED

        res2 = outsider_client.post(url, {}, format="json")
        assert res2.status_code == status.HTTP_200_OK
        assert res2.data["created"] is False
        assert "already submitted" in res2.data["message"]

    def test_request_rejected_when_gym_setting_disabled(self, outsider_client, test_gym):
        """When gym has user requests turned OFF (no_one), requests are rejected."""
        update_gym_settings(test_gym, who_can_send_joining_request=AudienceJoiningRequestEnum.NO_ONE)

        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        res = outsider_client.post(url, {}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert "not currently accepting" in get_error_message(res)

    def test_user_request_enabled_toggle_via_settings_api(self, owner_client, test_gym, outsider_client):
        """Admin can toggle user_request_enabled via gym settings API."""
        settings_url = reverse("gyms_v1:gym-settings")

        # Disable via user_request_enabled
        res = owner_client.patch(f"{settings_url}?gym_id={test_gym.id}", {"user_request_enabled": False}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["who_can_send_joining_request"] == "no_one"
        assert res.data["is_member_request_enabled"] is False

        # Request fails
        join_url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        res = outsider_client.post(join_url, {}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # Re-enable via user_request_enabled
        res = owner_client.patch(f"{settings_url}?gym_id={test_gym.id}", {"user_request_enabled": True}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["who_can_send_joining_request"] == "everyone"
        assert res.data["is_member_request_enabled"] is True

        # Request succeeds now
        res = outsider_client.post(join_url, {}, format="json")
        assert res.status_code == status.HTTP_201_CREATED

    def test_blocked_user_cannot_send_request(self, outsider_client, test_gym, outsider_adult_user):
        GymBlockedUser.objects.create(gym=test_gym, user=outsider_adult_user)
        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        res = outsider_client.post(url, {}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert "blocked" in get_error_message(res)

    def test_existing_member_cannot_send_request(self, member_client, test_gym, active_member):
        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        res = member_client.post(url, {}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "already a member" in get_error_message(res)


@pytest.mark.django_db
class TestAdminMemberRequestReviewAndAccept:

    def test_admin_and_staff_can_list_requests(self, owner_client, staff_client, outsider_client, test_gym, outsider_adult_user):
        # Outsider sends request
        outsider_client.post(reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id}), {"notes": "Please accept"}, format="json")

        # Owner lists requests
        url = reverse("member-request-list")
        res = owner_client.get(f"{url}?gym_id={test_gym.id}")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["count"] == 1
        item = res.data["results"][0]
        assert item["user"]["email"] == outsider_adult_user.email
        assert item["status"] == "pending"

        # Also via alias under gyms
        alias_url = reverse("gyms_v1:gym-member-requests-list", kwargs={"gym_id": test_gym.id})
        alias_res = owner_client.get(alias_url)
        assert alias_res.status_code == status.HTTP_200_OK
        assert alias_res.data["count"] == 1

        # Staff with members:read also lists requests
        res_staff = staff_client.get(f"{url}?gym_id={test_gym.id}")
        assert res_staff.status_code == status.HTTP_200_OK
        assert res_staff.data["count"] == 1

        # Outsider cannot list gym requests
        res_outsider = outsider_client.get(f"{url}?gym_id={test_gym.id}")
        assert res_outsider.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_accepts_request_and_supplies_member_details(self, owner_client, outsider_client, test_gym, outsider_adult_user, plan):
        """
        When admin accepts request, admin/staff supplies the required membership details
        (plan, start_date, trainer, emergency contact, initial payment, etc.).
        """
        # User submits request
        res = outsider_client.post(reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id}), {"notes": "Interested in joining"}, format="json")
        request_id = res.data["request_id"]

        # Admin accepts request and fills in the member details
        accept_url = reverse("member-request-accept", kwargs={"request_id": request_id})
        payload = {
            "plan_id": str(plan.id),
            "start_date": str(date.today()),
            "initial_payment_amount": "150.00",
            "initial_payment_method": "credit_card",
            "initial_payment_date": str(date.today()),
            "initial_payment_notes": "Paid at front desk via POS machine",
            "emergency_contact_name": "Jane Doe",
            "emergency_contact_phone": "+1234567890",
            "emergency_contact_relationship": "Sister",
            "address": "123 Gym Street",
            "city": "Metropolis",
            "country": "USA",
            "internal_notes": "Preferred morning workouts.",
        }

        accept_res = owner_client.post(f"{accept_url}?gym_id={test_gym.id}", payload, format="json")
        assert accept_res.status_code == status.HTTP_201_CREATED
        assert "accepted and member successfully enrolled" in accept_res.data["message"]

        # Verify created member
        member_data = accept_res.data["member"]
        assert member_data["email"] == outsider_adult_user.email
        assert member_data["joining_status"] == MemberJoiningStatus.JOINED

        member_obj = Member.objects.get(id=member_data["id"])
        assert member_obj.user == outsider_adult_user
        assert member_obj.emergency_contact_name == "Jane Doe"
        assert member_obj.city == "Metropolis"
        assert "Preferred morning workouts" in member_obj.internal_notes

        # Verify subscription was initialized
        sub = MemberSubscription.objects.get(member=member_obj)
        assert sub.plan == plan
        assert sub.membership_status == MembershipStatusEnum.ACTIVE
        assert sub.payment_status == PaymentStatusEnum.FULLY_PAID

        # Verify payment was recorded
        pay = MemberPayment.objects.get(member_subscription=sub)
        assert pay.amount == Decimal("150.00")
        assert pay.payment_method == PaymentMethodEnum.CREDIT_CARD

        # Verify request status transitioned to accepted
        req = MemberRequest.objects.get(id=request_id)
        assert req.status == MemberRequestStatus.ACCEPTED
        assert req.created_member == member_obj
        assert req.reviewed_by is not None

        # Trying to accept again fails with 409
        duplicate_accept = owner_client.post(f"{accept_url}?gym_id={test_gym.id}", payload, format="json")
        assert duplicate_accept.status_code == status.HTTP_409_CONFLICT

    def test_admin_rejects_request_with_reason(self, owner_client, outsider_client, test_gym, outsider_adult_user):
        res = outsider_client.post(reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id}), {"notes": "Let me in"}, format="json")
        request_id = res.data["request_id"]

        reject_url = reverse("member-request-reject", kwargs={"request_id": request_id})
        reject_res = owner_client.post(
            f"{reject_url}?gym_id={test_gym.id}",
            {"rejection_reason": "Gym capacity reached for this month."},
            format="json",
        )
        assert reject_res.status_code == status.HTTP_200_OK

        req = MemberRequest.objects.get(id=request_id)
        assert req.status == MemberRequestStatus.REJECTED
        assert "capacity reached" in req.rejection_reason
        assert req.reviewed_by is not None

    def test_user_can_cancel_own_request(self, outsider_client, test_gym):
        res = outsider_client.post(reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id}), {}, format="json")
        request_id = res.data["request_id"]

        cancel_url = reverse("member-request-cancel", kwargs={"request_id": request_id})
        cancel_res = outsider_client.post(cancel_url)
        assert cancel_res.status_code == status.HTTP_200_OK

        req = MemberRequest.objects.get(id=request_id)
        assert req.status == MemberRequestStatus.CANCELLED
