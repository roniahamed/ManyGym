import uuid
from decimal import Decimal
from datetime import date, timedelta
import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.urls import reverse

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym
from apps.gyms.services import create_gym
from apps.amenities.models import AmenityCatalog, GymAmenity
from apps.amenities.services import seed_amenity_catalog
from apps.access_control.models import Role, Permission, GymStaffAssignment
from apps.access_control.services import seed_default_permissions_and_roles
from apps.memberships.models import MembershipPlan
from apps.memberships.services import create_membership_plan
from apps.authentication.services import issue_context_token
from apps.members.models import Member, MemberSubscription, MemberPayment, MemberExtraAmenities
from apps.members.services import (
    create_member,
    create_member_subscription,
    record_member_payment,
    attach_extra_amenities,
)
from common.enums import (
    TokenContextType,
    UserStatus,
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    PaymentScheduleEnum,
    AmenityGroupEnum,
    MemberJoiningStatus,
    MembershipStatusEnum,
    PaymentStatusEnum,
    PaymentMethodEnum,
)


@pytest.fixture(autouse=True)
def setup_seeds(db):
    seed_amenity_catalog()
    seed_default_permissions_and_roles()


def create_user_with_tokens(email="test.phase4@manygym.com", is_verified=True, user_status=UserStatus.ACTIVE):
    user = User.objects.create_user(
        email=email,
        password="SecurePassword123!",
        first_name="Phase4",
        last_name="Tester",
        is_verified=is_verified,
        status=user_status,
    )
    UserProfile.objects.create(user=user)
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return user, client, tokens


def setup_gym_and_member_context(owner_email="owner.phase4@manygym.com"):
    owner, client, _ = create_user_with_tokens(owner_email)
    gym = create_gym(owner_user=owner, name="Phase 4 Security Gym")
    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    plan = create_membership_plan(
        gym=gym,
        name="Security Pro Plan",
        description="Comprehensive 50-character minimum test description for fitness.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("100.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
        joining_fee=Decimal("20.00"),
    )

    session_plan = create_membership_plan(
        gym=gym,
        name="Security 10-Session Pack",
        description="Ten full private coaching sessions with certified gym trainers.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.SESSION_BASED,
        price=Decimal("250.00"),
        duration_value=10,
        duration_unit=DurationUnitEnum.SESSION,
    )

    catalog_amenity = AmenityCatalog.objects.first()
    gym_amenity = GymAmenity.objects.create(
        gym=gym,
        amenity=catalog_amenity,
        is_paid=True,
        default_price=Decimal("15.00"),
    )

    member = create_member(
        gym=gym,
        first_name="John",
        last_name="Doe",
        email="john.doe@securitytest.com",
        phone="+1234567890",
    )

    subscription = create_member_subscription(
        member=member,
        plan=plan,
        start_date=date.today(),
    )

    return {
        "owner": owner,
        "gym": gym,
        "client": client,
        "plan": plan,
        "session_plan": session_plan,
        "gym_amenity": gym_amenity,
        "member": member,
        "subscription": subscription,
    }


# =====================================================================
# 1. TYPE JUGGLING / DATA TYPE MISMATCHES
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"first_name": 12345, "last_name": "Doe", "email": "valid@test.com"},
    {"first_name": ["John"], "last_name": "Doe", "email": "valid@test.com"},
    {"first_name": {"name": "John"}, "last_name": "Doe", "email": "valid@test.com"},
    {"first_name": True, "last_name": "Doe", "email": "valid@test.com"},
    {"first_name": "John", "last_name": 12345, "email": "valid@test.com"},
    {"first_name": "John", "last_name": ["Doe"], "email": "valid@test.com"},
    {"first_name": "John", "last_name": {"n": "Doe"}, "email": "valid@test.com"},
    {"first_name": "John", "last_name": True, "email": "valid@test.com"},
    {"first_name": "John", "last_name": "Doe", "email": 12345},
    {"first_name": "John", "last_name": "Doe", "email": ["valid@test.com"]},
    {"first_name": "John", "last_name": "Doe", "email": {"mail": "valid@test.com"}},
    {"first_name": "John", "last_name": "Doe", "email": True},
    {"first_name": "John", "last_name": "Doe", "email": "valid@test.com", "phone": 12345678},
    {"first_name": "John", "last_name": "Doe", "email": "valid@test.com", "assigned_trainer_id": 123},
    {"first_name": "John", "last_name": "Doe", "email": "valid@test.com", "assigned_trainer_id": ["not-uuid"]},
])
def test_member_create_type_juggling(payload):
    ctx = setup_gym_and_member_context("type_juggling_mem@manygym.com")
    url = reverse("member-list-create")
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in resp.data or resp.status_code in [400, 422]


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"amount": "not-a-number", "payment_method": "cash"},
    {"amount": [50.00], "payment_method": "cash"},
    {"amount": {"val": 50}, "payment_method": "cash"},
    {"amount": True, "payment_method": "cash"},
    {"amount": "50.00", "payment_method": 1234},
    {"amount": "50.00", "payment_method": ["cash"]},
    {"amount": "50.00", "payment_method": {"m": "cash"}},
    {"amount": "50.00", "payment_method": True},
])
def test_payment_create_type_juggling(payload):
    ctx = setup_gym_and_member_context("type_juggling_pay@manygym.com")
    url = reverse("member-subscription-payment-create", kwargs={"subscription_id": ctx["subscription"].id})
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# =====================================================================
# 2. BOUNDARY VALUES & EDGE CASES
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"first_name": "", "last_name": "Doe", "email": "test@boundary.com"},
    {"first_name": "   ", "last_name": "Doe", "email": "test@boundary.com"},
    {"first_name": "John", "last_name": "", "email": "test@boundary.com"},
    {"first_name": "John", "last_name": "   ", "email": "test@boundary.com"},
    {"first_name": "A" * 150, "last_name": "Doe", "email": "test@boundary.com"},  # max_length 100
    {"first_name": "John", "last_name": "B" * 150, "email": "test@boundary.com"},
    {"first_name": "John", "last_name": "Doe", "email": "not-an-email"},
    {"first_name": "John", "last_name": "Doe", "email": "user@" + "a" * 300 + ".com"},
])
def test_member_create_boundary_validation(payload):
    ctx = setup_gym_and_member_context("boundary_mem@manygym.com")
    url = reverse("member-list-create")
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"amount": "0.00", "payment_method": "cash"},
    {"amount": "-10.00", "payment_method": "cash"},
    {"amount": "-0.01", "payment_method": "cash"},
    {"amount": "99999999999999.00", "payment_method": "cash"},  # Exceeds max_digits 10
])
def test_payment_create_boundary_validation(payload):
    ctx = setup_gym_and_member_context("boundary_pay@manygym.com")
    url = reverse("member-subscription-payment-create", kwargs={"subscription_id": ctx["subscription"].id})
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# =====================================================================
# 3. EXTRA, UNEXPECTED & MISSING FIELDS
# =====================================================================

@pytest.mark.django_db
def test_member_create_missing_required_fields():
    ctx = setup_gym_and_member_context("missing_fields@manygym.com")
    url = reverse("member-list-create")
    
    # Empty body
    resp = ctx["client"].post(url, {}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # Missing email
    resp = ctx["client"].post(url, {"first_name": "Sam", "last_name": "Smith"}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # Missing first_name
    resp = ctx["client"].post(url, {"last_name": "Smith", "email": "sam@test.com"}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_member_create_with_100_extra_garbage_fields():
    ctx = setup_gym_and_member_context("garbage_fields@manygym.com")
    url = reverse("member-list-create")
    payload = {
        "first_name": "Valid",
        "last_name": "User",
        "email": "valid.user.garbage@test.com",
    }
    for i in range(100):
        payload[f"garbage_key_{i}"] = f"garbage_val_{i}"

    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.data["email"] == "valid.user.garbage@test.com"


# =====================================================================
# 4. FORMAT-SPECIFIC INPUTS (MALFORMED & NON-EXISTENT UUIDS)
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("bad_uuid", [
    "not-a-uuid",
    "12345",
    "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "../../../etc/passwd",
    "<script>alert(1)</script>",
])
def test_member_detail_malformed_uuids(bad_uuid):
    ctx = setup_gym_and_member_context("bad_uuid@manygym.com")
    url = f"/api/v1/members/{bad_uuid}/"
    resp = ctx["client"].get(url)
    assert resp.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]


@pytest.mark.django_db
def test_member_detail_non_existent_uuid():
    ctx = setup_gym_and_member_context("non_existent_uuid@manygym.com")
    url = reverse("member-detail", kwargs={"member_id": uuid.uuid4()})
    resp = ctx["client"].get(url)
    assert resp.status_code == status.HTTP_404_NOT_FOUND


# =====================================================================
# 5. QUERY PARAMS, PAGINATION & ADVERSARIAL INPUTS
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("page_param", ["0", "-1", "abc", "99999999", "1.5"])
def test_member_list_pagination_edge_cases(page_param):
    ctx = setup_gym_and_member_context("pag_edge@manygym.com")
    url = f"{reverse('member-list-create')}?page={page_param}"
    resp = ctx["client"].get(url)
    assert resp.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]
    assert resp.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


@pytest.mark.django_db
@pytest.mark.parametrize("search_term", [
    "'; DROP TABLE apps_members_member; --",
    "<script>alert('XSS')</script>",
    "🔥🏋️‍♂️বাংলা ইউনিকোড",
    "A" * 1000,
    "%20%27%3D",
])
def test_member_list_adversarial_search_inputs(search_term):
    ctx = setup_gym_and_member_context("adv_search@manygym.com")
    url = reverse("member-list-create")
    resp = ctx["client"].get(url, {"search": search_term})
    assert resp.status_code == status.HTTP_200_OK
    assert isinstance(resp.data, list)


# =====================================================================
# 6. AUTHENTICATION & RBAC PERMISSIONS
# =====================================================================

@pytest.mark.django_db
def test_member_endpoints_unauthenticated():
    client = APIClient()  # No token
    url = reverse("member-list-create")
    resp = client.get(url)
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    resp = client.post(url, {"first_name": "No", "last_name": "Auth", "email": "noauth@test.com"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_member_endpoints_personal_context_forbidden():
    user, client, _ = create_user_with_tokens("personal_ctx@manygym.com")
    # Using personal context token on gym member endpoint
    url = reverse("member-list-create")
    resp = client.get(url)
    assert resp.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN]


@pytest.mark.django_db
def test_member_endpoints_insufficient_permissions():
    ctx = setup_gym_and_member_context("staff_noperms@manygym.com")
    
    # Create staff user with role having NO member permissions
    staff_user, staff_client, _ = create_user_with_tokens("limited_staff@manygym.com")
    empty_role = Role.objects.create(gym=ctx["gym"], name="Empty Staff Role", slug="empty-staff-role")
    GymStaffAssignment.objects.create(
        gym=ctx["gym"],
        user=staff_user,
        role=empty_role,
        status="active",
    )
    tokens = issue_context_token(staff_user, context_type=TokenContextType.GYM, gym=ctx["gym"])
    staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # Try list members
    resp = staff_client.get(reverse("member-list-create"))
    assert resp.status_code == status.HTTP_403_FORBIDDEN

    # Try create member
    resp = staff_client.post(
        reverse("member-list-create"),
        {"first_name": "Deny", "last_name": "User", "email": "deny@test.com"},
        format="json",
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# =====================================================================
# 7. IDOR & MULTI-TENANT ISOLATION
# =====================================================================

@pytest.mark.django_db
def test_cross_tenant_idor_member_isolation():
    gym_a_ctx = setup_gym_and_member_context("gyma_owner@manygym.com")
    gym_b_ctx = setup_gym_and_member_context("gymb_owner@manygym.com")

    # Gym B client tries to view Gym A member
    url = reverse("member-detail", kwargs={"member_id": gym_a_ctx["member"].id})
    resp = gym_b_ctx["client"].get(url)
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # Gym B client tries to update Gym A member
    resp = gym_b_ctx["client"].patch(url, {"first_name": "HackedName"}, format="json")
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # Gym B client tries to delete Gym A member
    resp = gym_b_ctx["client"].delete(url)
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # Gym B client tries to view Gym A member's subscription
    sub_url = reverse(
        "member-subscription-payment-create",
        kwargs={"subscription_id": gym_a_ctx["subscription"].id},
    )
    resp = gym_b_ctx["client"].post(sub_url, {"amount": "50.00", "payment_method": "cash"}, format="json")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_cross_tenant_plan_attachment_forbidden():
    gym_a_ctx = setup_gym_and_member_context("gyma_crossplan@manygym.com")
    gym_b_ctx = setup_gym_and_member_context("gymb_crossplan@manygym.com")

    # Try to create subscription in Gym A using Gym B's membership plan
    url = reverse("member-subscription-create", kwargs={"member_id": gym_a_ctx["member"].id})
    payload = {
        "membership_plan_id": str(gym_b_ctx["plan"].id),
        "start_date": str(date.today()),
    }
    resp = gym_a_ctx["client"].post(url, payload, format="json")
    assert resp.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]


# =====================================================================
# 8. BUSINESS INVARIANTS & STATE TRANSITIONS
# =====================================================================

@pytest.mark.django_db
def test_duplicate_email_member_creation_in_same_gym():
    ctx = setup_gym_and_member_context("dup_email_ctx@manygym.com")
    url = reverse("member-list-create")
    payload = {
        "first_name": "Duplicate",
        "last_name": "Tester",
        "email": ctx["member"].email,  # same email as existing member in this gym
    }
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_409_CONFLICT


@pytest.mark.django_db
def test_double_accept_invitation_rejection():
    ctx = setup_gym_and_member_context("double_accept@manygym.com")
    member = ctx["member"]
    token = member.invitation_token
    assert token is not None

    user, client, _ = create_user_with_tokens("invitee.user@manygym.com")
    accept_url = reverse("member-accept-invitation")
    
    # First acceptance: should succeed
    resp1 = client.post(accept_url, {"invitation_token": str(token)}, format="json")
    assert resp1.status_code == status.HTTP_200_OK

    # Second acceptance: token is now cleared/invalidated
    resp2 = client.post(accept_url, {"invitation_token": str(token)}, format="json")
    assert resp2.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]


@pytest.mark.django_db
def test_invalid_subscription_status_transition():
    ctx = setup_gym_and_member_context("status_trans@manygym.com")
    url = reverse("member-subscription-status", kwargs={"subscription_id": ctx["subscription"].id})

    # Transition to invalid string status
    resp = ctx["client"].patch(url, {"status": "invalid_status_xyz"}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # Cancel subscription
    resp = ctx["client"].patch(url, {"status": "cancelled"}, format="json")
    assert resp.status_code == status.HTTP_200_OK

    # Once cancelled, cannot transition back to active directly
    resp = ctx["client"].patch(url, {"status": "active"}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# =====================================================================
# 9. METHOD NOT ALLOWED (405)
# =====================================================================

@pytest.mark.django_db
def test_http_method_not_allowed():
    ctx = setup_gym_and_member_context("method_405@manygym.com")
    list_url = reverse("member-list-create")
    detail_url = reverse("member-detail", kwargs={"member_id": ctx["member"].id})

    # PUT on list
    resp = ctx["client"].put(list_url)
    assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # DELETE on list
    resp = ctx["client"].delete(list_url)
    assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # POST on detail
    resp = ctx["client"].post(detail_url, {})
    assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# =====================================================================
# 10. ERROR ENVELOPE CONSISTENCY
# =====================================================================

@pytest.mark.django_db
def test_standard_error_envelope_structure():
    ctx = setup_gym_and_member_context("envelope_check@manygym.com")
    url = reverse("member-list-create")

    # Send invalid payload to trigger 400
    resp = ctx["client"].post(url, {"first_name": ""}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    
    # Assert envelope format
    assert "code" in resp.data
    assert "message" in resp.data
    assert "details" in resp.data
