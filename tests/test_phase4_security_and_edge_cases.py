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


# =====================================================================
# 11. ADDITIONAL TYPE JUGGLING ACROSS OTHER PHASE 4 ENDPOINTS
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"first_name": 999},
    {"first_name": ["Bad"]},
    {"first_name": {"nested": "value"}},
    {"last_name": 123},
    {"last_name": ["List"]},
    {"email": 456},
    {"phone": 789},
    {"date_of_birth": 12345},
    {"date_of_birth": "not-a-date"},
    {"assigned_trainer_id": 123},
    {"assigned_trainer_id": ["not-uuid"]},
])
def test_member_patch_type_juggling(payload):
    ctx = setup_gym_and_member_context("patch_tj@manygym.com")
    url = reverse("member-detail", kwargs={"member_id": ctx["member"].id})
    resp = ctx["client"].patch(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"plan_id": 12345},
    {"plan_id": ["not-a-uuid"]},
    {"plan_id": {"id": "uuid"}},
    {"plan_id": True},
    {"start_date": 12345},
    {"start_date": "not-a-date"},
    {"start_date": "2026-13-45"},
    {"extra_amenity_ids": "not-a-list"},
    {"extra_amenity_ids": 12345},
    {"extra_amenity_ids": [12345]},
    {"initial_payment_amount": "invalid-number"},
    {"initial_payment_amount": [50.00]},
    {"initial_payment_amount": -50.00},
    {"initial_payment_amount": 0.00},
    {"initial_payment_method": 12345},
])
def test_subscription_create_type_juggling(payload):
    ctx = setup_gym_and_member_context("sub_create_tj@manygym.com")
    url = reverse("member-subscription-create", kwargs={"member_id": ctx["member"].id})
    # If plan_id is not in payload, supply valid one unless testing plan_id
    if "plan_id" not in payload:
        payload["plan_id"] = str(ctx["plan"].id)
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"amenity_ids": "not-a-list"},
    {"amenity_ids": 12345},
    {"amenity_ids": {"id": "val"}},
    {"amenity_ids": True},
    {"amenity_ids": [12345]},
    {"amenity_ids": ["not-a-uuid"]},
])
def test_extra_amenities_type_juggling(payload):
    ctx = setup_gym_and_member_context("extra_am_tj@manygym.com")
    url = reverse("member-subscription-extra-amenities", kwargs={"subscription_id": ctx["subscription"].id})
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"token": 12345},
    {"token": ["not-a-token"]},
    {"token": {"nested": "token"}},
    {"token": True},
    {"invitation_token": 12345},
    {"invitation_token": ["bad"]},
])
def test_accept_invitation_type_juggling(payload):
    _, client, _ = create_user_with_tokens("accept_tj@manygym.com")
    url = reverse("member-accept-invitation")
    resp = client.post(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"membership_status": 12345},
    {"membership_status": ["bad"]},
    {"membership_status": {"status": "active"}},
    {"membership_status": True},
    {"membership_status": "non_existent_status"},
])
def test_subscription_status_type_juggling(payload):
    ctx = setup_gym_and_member_context("sub_status_tj@manygym.com")
    url = reverse("member-subscription-status", kwargs={"subscription_id": ctx["subscription"].id})
    resp = ctx["client"].patch(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# =====================================================================
# 12. BOUNDARIES, LENGTH & DATE LOGIC
# =====================================================================

@pytest.mark.django_db
def test_subscription_create_end_date_before_start_date():
    ctx = setup_gym_and_member_context("sub_dates@manygym.com")
    url = reverse("member-subscription-create", kwargs={"member_id": ctx["member"].id})
    payload = {
        "plan_id": str(ctx["plan"].id),
        "start_date": str(date.today()),
        "end_date": str(date.today() - timedelta(days=5)),
    }
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "code" in resp.data


@pytest.mark.django_db
def test_subscription_create_session_plan_requires_end_date():
    ctx = setup_gym_and_member_context("sub_session_date@manygym.com")
    url = reverse("member-subscription-create", kwargs={"member_id": ctx["member"].id})
    payload = {
        "plan_id": str(ctx["session_plan"].id),
        "start_date": str(date.today()),
    }
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_extra_amenities_free_amenity_rejection():
    ctx = setup_gym_and_member_context("free_amenity_rej@manygym.com")
    catalog2 = AmenityCatalog.objects.last()
    free_amenity = GymAmenity.objects.create(
        gym=ctx["gym"],
        amenity=catalog2,
        is_paid=False,
    )
    url = reverse("member-subscription-extra-amenities", kwargs={"subscription_id": ctx["subscription"].id})
    resp = ctx["client"].post(url, {"amenity_ids": [str(free_amenity.id)]}, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "free" in str(resp.data).lower()


@pytest.mark.django_db
def test_extra_amenities_deduplication():
    ctx = setup_gym_and_member_context("am_dedup@manygym.com")
    url = reverse("member-subscription-extra-amenities", kwargs={"subscription_id": ctx["subscription"].id})
    aid = str(ctx["gym_amenity"].id)
    resp = ctx["client"].post(url, {"amenity_ids": [aid, aid, aid]}, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
    assert len(resp.data) == 1


# =====================================================================
# 13. MASS ASSIGNMENT & SERVER-CONTROLLED FIELDS PROTECTION
# =====================================================================

@pytest.mark.django_db
def test_member_mass_assignment_protection():
    ctx = setup_gym_and_member_context("mass_assign@manygym.com")
    url = reverse("member-list-create")
    fake_id = uuid.uuid4()
    payload = {
        "id": str(fake_id),
        "first_name": "Injected",
        "last_name": "Member",
        "email": "injected@massassign.com",
        "joining_status": "joined",
        "is_active": False,
        "created_at": "2020-01-01T00:00:00Z",
    }
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.data
    assert str(data["id"]) != str(fake_id)
    assert data["joining_status"] == MemberJoiningStatus.SENT_INVITATION


@pytest.mark.django_db
def test_subscription_mass_assignment_protection():
    ctx = setup_gym_and_member_context("sub_mass_assign@manygym.com")
    url = reverse("member-subscription-create", kwargs={"member_id": ctx["member"].id})
    payload = {
        "plan_id": str(ctx["plan"].id),
        "payment_status": "fully_paid",
        "total_sessions": 9999,
        "remaining_sessions": 9999,
    }
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.data["payment_status"] == PaymentStatusEnum.UNPAID


# =====================================================================
# 14. SECURITY PAYLOADS ACROSS MEMBER FIELDS
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("sec_payload", [
    "'; DROP TABLE apps_members_member; --",
    "\" OR \"\"=\"",
    "<script>alert('XSS')</script>",
    "<img src=x onerror=alert(1)>",
    "../../../../../../etc/passwd",
    "🏋️‍♂️🔥বাংলা টেস্ট ইউজার",
    "العربية / 日本語 / Русский",
    "Z̵a̶l̶g̸o̶ ̷T̷e̴x̵t̸",
])
def test_member_create_security_payloads_in_all_fields(sec_payload):
    ctx = setup_gym_and_member_context("sec_fields@manygym.com")
    url = reverse("member-list-create")
    email = f"user_{uuid.uuid4().hex[:8]}@manygym.com"
    payload = {
        "first_name": sec_payload[:50],
        "last_name": sec_payload[:50],
        "email": email,
        "address": sec_payload[:200],
        "city": sec_payload[:50],
        "country": sec_payload[:50],
        "internal_notes": sec_payload,
        "emergency_contact_name": sec_payload[:50],
        "emergency_contact_relationship": sec_payload[:50],
    }
    resp = ctx["client"].post(url, payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED
    member_id = resp.data["id"]

    detail_url = reverse("member-detail", kwargs={"member_id": member_id})
    detail_resp = ctx["client"].get(detail_url)
    assert detail_resp.status_code == status.HTTP_200_OK


# =====================================================================
# 15. PAYMENT LEDGER CALCULATIONS (PARTIAL, FULL, OVERPAID)
# =====================================================================

@pytest.mark.django_db
def test_payment_ledger_calculations_and_status_transitions():
    ctx = setup_gym_and_member_context("ledger_calc@manygym.com")
    sub = ctx["subscription"]
    assert sub.payment_status == PaymentStatusEnum.UNPAID

    pay_url = reverse("member-subscription-payment-create", kwargs={"subscription_id": sub.id})

    # 1. Partial payment: $50.00
    resp1 = ctx["client"].post(pay_url, {"amount": "50.00", "payment_method": "cash"}, format="json")
    assert resp1.status_code == status.HTTP_201_CREATED
    sub.refresh_from_db()
    assert sub.payment_status == PaymentStatusEnum.PARTIALLY_PAID

    # 2. Settle remaining balance: $70.00 (Total paid = $120.00)
    resp2 = ctx["client"].post(pay_url, {"amount": "70.00", "payment_method": "credit_card"}, format="json")
    assert resp2.status_code == status.HTTP_201_CREATED
    sub.refresh_from_db()
    assert sub.payment_status == PaymentStatusEnum.FULLY_PAID

    # 3. Overpayment: $20.00 (Total paid = $140.00)
    resp3 = ctx["client"].post(pay_url, {"amount": "20.00", "payment_method": "bank_transfer"}, format="json")
    assert resp3.status_code == status.HTTP_201_CREATED
    sub.refresh_from_db()
    assert sub.payment_status == PaymentStatusEnum.FULLY_PAID


# =====================================================================
# 16. EXHAUSTIVE IDOR & CROSS-TENANT ISOLATION
# =====================================================================

@pytest.mark.django_db
def test_cross_tenant_idor_exhaustive_operations():
    gym_a_ctx = setup_gym_and_member_context("gyma_idor@manygym.com")
    gym_b_ctx = setup_gym_and_member_context("gymb_idor@manygym.com")

    member_a = gym_a_ctx["member"]
    sub_a = gym_a_ctx["subscription"]

    # 1. Gym B tries to resend invitation for Gym A's member
    resp = gym_b_ctx["client"].post(reverse("member-resend-invitation", kwargs={"member_id": member_a.id}))
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # 2. Gym B tries to attach subscription to Gym A's member
    resp = gym_b_ctx["client"].post(
        reverse("member-subscription-create", kwargs={"member_id": member_a.id}),
        {"plan_id": str(gym_b_ctx["plan"].id)},
        format="json",
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # 3. Gym B tries to transition status of Gym A's subscription
    resp = gym_b_ctx["client"].patch(
        reverse("member-subscription-status", kwargs={"subscription_id": sub_a.id}),
        {"status": "cancelled"},
        format="json",
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # 4. Gym B tries to attach extra amenities to Gym A's subscription
    resp = gym_b_ctx["client"].post(
        reverse("member-subscription-extra-amenities", kwargs={"subscription_id": sub_a.id}),
        {"amenity_ids": [str(gym_b_ctx["gym_amenity"].id)]},
        format="json",
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # 5. Gym A tries to attach Gym B's amenity to Gym A's subscription
    resp = gym_a_ctx["client"].post(
        reverse("member-subscription-extra-amenities", kwargs={"subscription_id": sub_a.id}),
        {"amenity_ids": [str(gym_b_ctx["gym_amenity"].id)]},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


# =====================================================================
# 17. EXHAUSTIVE RBAC & SCOPE PERMISSIONS
# =====================================================================

@pytest.mark.django_db
def test_rbac_read_only_staff_cannot_perform_mutations():
    ctx = setup_gym_and_member_context("rbac_mutations@manygym.com")
    member = ctx["member"]
    sub = ctx["subscription"]

    staff_user, staff_client, _ = create_user_with_tokens("readonly_staff@manygym.com")
    read_role = Role.objects.create(gym=ctx["gym"], name="Reader Role", slug="reader-role")
    perm = Permission.objects.get(scope_code="members:read")
    read_role.permissions.add(perm)
    GymStaffAssignment.objects.create(
        gym=ctx["gym"],
        user=staff_user,
        role=read_role,
        status="active",
    )
    tokens = issue_context_token(staff_user, context_type=TokenContextType.GYM, gym=ctx["gym"])
    staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # Can read
    assert staff_client.get(reverse("member-list-create")).status_code == status.HTTP_200_OK
    assert staff_client.get(reverse("member-detail", kwargs={"member_id": member.id})).status_code == status.HTTP_200_OK
    assert staff_client.get(reverse("member-metrics")).status_code == status.HTTP_200_OK

    # Cannot mutate
    assert staff_client.post(reverse("member-list-create"), {"first_name": "Test", "last_name": "X", "email": "t@x.com"}).status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.patch(reverse("member-detail", kwargs={"member_id": member.id}), {"first_name": "Y"}).status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.delete(reverse("member-detail", kwargs={"member_id": member.id})).status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.post(reverse("member-resend-invitation", kwargs={"member_id": member.id})).status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.post(reverse("member-subscription-create", kwargs={"member_id": member.id}), {"plan_id": str(ctx["plan"].id)}).status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.patch(reverse("member-subscription-status", kwargs={"subscription_id": sub.id}), {"status": "paused"}).status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.post(reverse("member-subscription-payment-create", kwargs={"subscription_id": sub.id}), {"amount": "10.00", "payment_method": "cash"}).status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.post(reverse("member-subscription-extra-amenities", kwargs={"subscription_id": sub.id}), {"amenity_ids": [str(ctx["gym_amenity"].id)]}).status_code == status.HTTP_403_FORBIDDEN


# =====================================================================
# 18. EXHAUSTIVE HTTP METHOD NOT ALLOWED (405)
# =====================================================================

@pytest.mark.django_db
def test_exhaustive_http_methods_not_allowed():
    ctx = setup_gym_and_member_context("methods_exhaustive@manygym.com")
    member = ctx["member"]
    sub = ctx["subscription"]
    client = ctx["client"]

    # Metrics endpoint: only GET allowed
    assert client.post(reverse("member-metrics"), {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.delete(reverse("member-metrics")).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # Accept invitation endpoint: only POST allowed
    assert client.get(reverse("member-accept-invitation")).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.delete(reverse("member-accept-invitation")).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # Resend invitation endpoint: only POST allowed
    resend_url = reverse("member-resend-invitation", kwargs={"member_id": member.id})
    assert client.get(resend_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.put(resend_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.delete(resend_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # Subscription create endpoint: only POST allowed
    sub_create_url = reverse("member-subscription-create", kwargs={"member_id": member.id})
    assert client.get(sub_create_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.put(sub_create_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.delete(sub_create_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # Subscription status transition endpoint: only PATCH allowed
    sub_status_url = reverse("member-subscription-status", kwargs={"subscription_id": sub.id})
    assert client.get(sub_status_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.post(sub_status_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.delete(sub_status_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # Payment create endpoint: only POST allowed
    pay_url = reverse("member-subscription-payment-create", kwargs={"subscription_id": sub.id})
    assert client.get(pay_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.put(pay_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.delete(pay_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # Extra amenities endpoint: only POST allowed
    am_url = reverse("member-subscription-extra-amenities", kwargs={"subscription_id": sub.id})
    assert client.get(am_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.put(am_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.delete(am_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# =====================================================================
# 19. BUSINESS INVARIANTS & INTEGRATION EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_delete_member_with_and_without_payments():
    ctx = setup_gym_and_member_context("del_invariants@manygym.com")
    member = ctx["member"]
    sub = ctx["subscription"]
    detail_url = reverse("member-detail", kwargs={"member_id": member.id})

    # 1. Record a payment
    record_member_payment(
        subscription=sub,
        amount=Decimal("50.00"),
        payment_method="cash",
        payment_date=date.today(),
    )

    # Attempt to delete member with existing payments -> 409 Conflict
    resp = ctx["client"].delete(detail_url)
    assert resp.status_code == status.HTTP_409_CONFLICT
    assert "code" in resp.data
    assert Member.objects.filter(id=member.id).exists()

    # 2. Create another member with NO payments
    member_no_pay = create_member(
        gym=ctx["gym"],
        first_name="NoPay",
        last_name="Member",
        email="nopay@deltest.com",
    )
    no_pay_url = reverse("member-detail", kwargs={"member_id": member_no_pay.id})
    del_resp = ctx["client"].delete(no_pay_url)
    assert del_resp.status_code == status.HTTP_200_OK
    assert not Member.objects.filter(id=member_no_pay.id).exists()


@pytest.mark.django_db
def test_resend_invitation_already_joined_member():
    ctx = setup_gym_and_member_context("resend_joined@manygym.com")
    member = ctx["member"]
    token = member.invitation_token

    # Accept invitation so member status transitions to 'joined'
    user, client, _ = create_user_with_tokens("joined_user@manygym.com")
    client.post(reverse("member-accept-invitation"), {"invitation_token": str(token)}, format="json")
    member.refresh_from_db()
    assert member.joining_status == MemberJoiningStatus.JOINED

    # Resend invitation must now fail with 400 Bad Request
    resend_url = reverse("member-resend-invitation", kwargs={"member_id": member.id})
    resp = ctx["client"].post(resend_url)
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "already" in str(resp.data).lower()

