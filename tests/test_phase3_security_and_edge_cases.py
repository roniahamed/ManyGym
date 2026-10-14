import uuid
from decimal import Decimal
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
from apps.memberships.models import MembershipPlan, PlanIncludedAmenities
from apps.memberships.services import create_membership_plan
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    UserStatus,
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    PaymentScheduleEnum,
    AmenityGroupEnum,
)


@pytest.fixture(autouse=True)
def setup_seeds(db):
    seed_amenity_catalog()
    seed_default_permissions_and_roles()


def create_user_with_tokens(email="test.phase3@manygym.com", is_verified=True, user_status=UserStatus.ACTIVE):
    user = User.objects.create_user(
        email=email,
        password="SecurePassword123!",
        first_name="Phase3",
        last_name="Tester",
        is_verified=is_verified,
        status=user_status,
    )
    UserProfile.objects.create(user=user)
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return user, client, tokens


def setup_gym_and_plan(owner_email="owner.phase3@manygym.com"):
    owner, client, _ = create_user_with_tokens(owner_email)
    gym = create_gym(owner_user=owner, name="Phase 3 Test Gym")
    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    plan = create_membership_plan(
        gym=gym,
        name="Base Test Plan",
        description="Comprehensive 50-character minimum test description for fitness.",
        plan_status=PlanStatusEnum.DRAFT,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("49.99"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
        joining_fee=Decimal("15.00"),
    )
    return owner, gym, plan, client


# =====================================================================
# 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"name": 12345, "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": ["Plan Name"], "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": {"title": "Plan"}, "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": True, "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": None, "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "duration_value": "twenty", "plan_type": "time_based", "price": "50.00", "duration_unit": "month"},
    {"name": "Valid Name", "duration_value": 3.5, "plan_type": "time_based", "price": "50.00", "duration_unit": "month"},
    {"name": "Valid Name", "duration_value": [1], "plan_type": "time_based", "price": "50.00", "duration_unit": "month"},
    {"name": "Valid Name", "duration_value": {"val": 1}, "plan_type": "time_based", "price": "50.00", "duration_unit": "month"},
    {"name": "Valid Name", "duration_value": True, "plan_type": "time_based", "price": "50.00", "duration_unit": "month"},
    {"name": "Valid Name", "duration_value": None, "plan_type": "time_based", "price": "50.00", "duration_unit": "month"},
    {"name": "Valid Name", "price": "fifty", "duration_value": 1, "plan_type": "time_based", "duration_unit": "month"},
    {"name": "Valid Name", "price": [50.00], "duration_value": 1, "plan_type": "time_based", "duration_unit": "month"},
    {"name": "Valid Name", "price": {"amt": 50}, "duration_value": 1, "plan_type": "time_based", "duration_unit": "month"},
    {"name": "Valid Name", "price": True, "duration_value": 1, "plan_type": "time_based", "duration_unit": "month"},
    {"name": "Valid Name", "price": None, "duration_value": 1, "plan_type": "time_based", "duration_unit": "month"},
    {"name": "Valid Name", "joining_fee": "ten", "price": "50.00", "duration_value": 1, "plan_type": "time_based", "duration_unit": "month"},
    {"name": "Valid Name", "joining_fee": True, "price": "50.00", "duration_value": 1, "plan_type": "time_based", "duration_unit": "month"},
    {"name": "Valid Name", "joining_fee": [10], "price": "50.00", "duration_value": 1, "plan_type": "time_based", "duration_unit": "month"},
    {"name": "Valid Name", "plan_type": 123, "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "plan_type": ["time_based"], "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "plan_type": True, "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "duration_unit": 123, "plan_type": "time_based", "price": "50.00", "duration_value": 1},
    {"name": "Valid Name", "duration_unit": ["month"], "plan_type": "time_based", "price": "50.00", "duration_value": 1},
    {"name": "Valid Name", "duration_unit": True, "plan_type": "time_based", "price": "50.00", "duration_value": 1},
    {"name": "Valid Name", "plan_status": 999, "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "plan_status": True, "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "payment_schedule": 999, "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "payment_schedule": True, "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "cancellation_policy": 12345, "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "refund_policy": ["refund"], "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "included_amenity_ids": "not-a-list", "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "included_amenity_ids": 12345, "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "included_amenity_ids": [123], "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "included_amenity_ids": [True], "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
    {"name": "Valid Name", "included_amenity_ids": [{"id": "uuid"}], "plan_type": "time_based", "price": "50.00", "duration_value": 1, "duration_unit": "month"},
])
def test_plan_create_type_juggling(payload):
    _, _, _, client = setup_gym_and_plan("create_type@manygym.com")
    url = reverse("membership-plans-list-create")
    res = client.post(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "code" in res.json()


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"name": 12345},
    {"name": ["New Name"]},
    {"name": True},
    {"price": "free"},
    {"price": True},
    {"price": [10.00]},
    {"duration_value": "two"},
    {"duration_value": True},
    {"duration_value": 2.5},
    {"joining_fee": "none"},
    {"joining_fee": True},
    {"plan_type": 123},
    {"duration_unit": True},
    {"cancellation_policy": 12345},
    {"refund_policy": 12345},
    {"included_amenity_ids": "invalid"},
    {"included_amenity_ids": [12345]},
])
def test_plan_patch_type_juggling(payload):
    _, _, plan, client = setup_gym_and_plan("patch_type@manygym.com")
    url = reverse("membership-plan-detail", kwargs={"plan_id": plan.id})
    res = client.patch(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "code" in res.json()


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"plan_status": 123},
    {"plan_status": ["active"]},
    {"plan_status": {"status": "active"}},
    {"plan_status": True},
    {"plan_status": None},
    {"plan_status": "non_existent_status"},
])
def test_plan_status_type_juggling(payload):
    _, _, plan, client = setup_gym_and_plan("status_type@manygym.com")
    url = reverse("membership-plan-status", kwargs={"plan_id": plan.id})
    res = client.post(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "code" in res.json()


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"amenity_ids": "not-a-list"},
    {"amenity_ids": 12345},
    {"amenity_ids": True},
    {"amenity_ids": None},
    {"amenity_ids": [12345]},
    {"amenity_ids": [True]},
    {"amenity_ids": ["not-a-uuid"]},
    {"amenity_ids": [{"id": "uuid"}]},
])
def test_plan_amenities_sync_type_juggling(payload):
    _, _, plan, client = setup_gym_and_plan("amenities_type@manygym.com")
    url = reverse("membership-plan-amenities-sync", kwargs={"plan_id": plan.id})
    res = client.put(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "code" in res.json()


# =====================================================================
# 2. BOUNDARY & LENGTH EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_plan_name_length_boundaries():
    _, _, _, client = setup_gym_and_plan("boundaries@manygym.com")
    url = reverse("membership-plans-list-create")
    base_payload = {
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 1,
        "duration_unit": "month",
    }

    # Empty string -> 400
    res = client.post(url, {**base_payload, "name": ""}, format="json")
    assert res.status_code == 400

    # Whitespace only -> 400
    res = client.post(url, {**base_payload, "name": "     "}, format="json")
    assert res.status_code == 400

    # Length 1 (min - 1) -> 400
    res = client.post(url, {**base_payload, "name": "A"}, format="json")
    assert res.status_code == 400

    # Length 2 (exact min) -> 201
    res = client.post(url, {**base_payload, "name": "AB"}, format="json")
    assert res.status_code == 201

    # Length 255 (exact max) -> 201
    res = client.post(url, {**base_payload, "name": "A" * 255}, format="json")
    assert res.status_code == 201

    # Length 256 (max + 1) -> 400
    res = client.post(url, {**base_payload, "name": "A" * 256}, format="json")
    assert res.status_code == 400

    # Extremely long string (10,000 chars) -> 400
    res = client.post(url, {**base_payload, "name": "A" * 10000}, format="json")
    assert res.status_code == 400

    # Name with leading and trailing whitespaces is trimmed cleanly -> 201
    res = client.post(url, {**base_payload, "name": "  Trimmed Plan  "}, format="json")
    assert res.status_code == 201
    assert res.json()["name"] == "Trimmed Plan"


@pytest.mark.django_db
def test_plan_description_length_boundaries():
    _, _, _, client = setup_gym_and_plan("desc_boundaries@manygym.com")
    url = reverse("membership-plans-list-create")
    base_payload = {
        "name": "Description Boundary Plan",
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 1,
        "duration_unit": "month",
    }

    # Description length 49 (min - 1) -> 400
    res = client.post(url, {**base_payload, "description": "A" * 49}, format="json")
    assert res.status_code == 400
    assert "at least 50 characters" in str(res.json()).lower()

    # Description length 50 (exact min) -> 201
    res = client.post(url, {**base_payload, "description": "A" * 50}, format="json")
    assert res.status_code == 201

    # Description whitespace-only -> handled as empty/null -> 201
    res = client.post(url, {**base_payload, "description": "        "}, format="json")
    assert res.status_code == 201
    assert res.json()["description"] is None

    # Description 10,000+ chars -> 201
    res = client.post(url, {**base_payload, "description": "A" * 10000}, format="json")
    assert res.status_code == 201


@pytest.mark.django_db
@pytest.mark.parametrize("price_input,expected_status", [
    ("-0.01", 400),
    ("-100.00", 400),
    ("0.00", 201),
    ("99999999.99", 201),  # Max allowable decimal (8 int digits, 2 decimals = 10 digits)
    ("100000000.00", 400),  # Exceeds max_digits=10
    ("49.999", 400),        # Exceeds 2 decimal places
])
def test_plan_price_boundaries(price_input, expected_status):
    _, _, _, client = setup_gym_and_plan(f"price_{price_input.replace('.', '_').replace('-', 'neg')}@manygym.com")
    url = reverse("membership-plans-list-create")
    res = client.post(url, {
        "name": "Price Boundary Plan",
        "plan_type": "time_based",
        "price": price_input,
        "duration_value": 1,
        "duration_unit": "month",
    }, format="json")
    assert res.status_code == expected_status


@pytest.mark.django_db
@pytest.mark.parametrize("duration_val,expected_status", [
    (0, 400),
    (-1, 400),
    (-100, 400),
    (1, 201),
    (12, 201),
    (99999999999999999999999999999999999999999999999999, 400),
])
def test_plan_duration_value_boundaries(duration_val, expected_status):
    _, _, _, client = setup_gym_and_plan(f"dur_{str(duration_val)[:10]}@manygym.com")
    url = reverse("membership-plans-list-create")
    res = client.post(url, {
        "name": "Duration Boundary Plan",
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": duration_val,
        "duration_unit": "month",
    }, format="json")
    assert res.status_code == expected_status


# =====================================================================
# 3. MISSING, EXTRA & MALFORMED FIELDS
# =====================================================================

@pytest.mark.django_db
def test_empty_and_missing_required_fields():
    _, _, plan, client = setup_gym_and_plan("missing_fields@manygym.com")

    # 1. Completely empty JSON body on POST /plans/ -> 400
    create_url = reverse("membership-plans-list-create")
    res = client.post(create_url, {}, format="json")
    assert res.status_code == 400

    # 2. Missing required fields individually
    required_fields = ["name", "plan_type", "price", "duration_value", "duration_unit"]
    complete_payload = {
        "name": "Valid Test Plan",
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 1,
        "duration_unit": "month",
    }
    for field in required_fields:
        payload = {k: v for k, v in complete_payload.items() if k != field}
        res = client.post(create_url, payload, format="json")
        assert res.status_code == 400, f"Expected 400 when missing required field '{field}'"

    # 3. Completely empty JSON body on status transition -> 400
    status_url = reverse("membership-plan-status", kwargs={"plan_id": plan.id})
    res = client.post(status_url, {}, format="json")
    assert res.status_code == 400

    # 4. Completely empty JSON body on amenities sync -> 400
    amenities_url = reverse("membership-plan-amenities-sync", kwargs={"plan_id": plan.id})
    res = client.put(amenities_url, {}, format="json")
    assert res.status_code == 400


@pytest.mark.django_db
def test_extra_garbage_and_server_controlled_fields():
    _, _, plan, client = setup_gym_and_plan("extra_fields@manygym.com")
    create_url = reverse("membership-plans-list-create")

    # 100+ extra garbage fields injected
    extra_fields = {f"garbage_key_{i}": f"garbage_value_{i}" for i in range(120)}
    payload = {
        "name": "Garbage Resistant Plan",
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 1,
        "duration_unit": "month",
        **extra_fields,
    }
    res = client.post(create_url, payload, format="json")
    assert res.status_code == 201
    created_data = res.json()
    # Ensure garbage fields were NOT stored or reflected in model representation
    for key in extra_fields:
        assert key not in created_data

    # Attempt to pass server-controlled fields in body (id, created_at)
    spoofed_id = str(uuid.uuid4())
    res_spoof = client.post(create_url, {
        "id": spoofed_id,
        "created_at": "1999-01-01T00:00:00Z",
        "name": "Server Field Protection Plan",
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 1,
        "duration_unit": "month",
    }, format="json")
    assert res_spoof.status_code == 201
    # Server-generated UUID must NOT match the client spoofed ID
    assert res_spoof.json()["id"] != spoofed_id


# =====================================================================
# 4. FORMAT-SPECIFIC INVALID INPUTS
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("invalid_uuid", [
    "not-a-valid-uuid",
    "12345",
    "00000000-0000",
    "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
    "null",
    "undefined",
])
def test_malformed_uuids_in_path_and_query(invalid_uuid):
    _, gym, plan, client = setup_gym_and_plan(f"uuid_{invalid_uuid[:5]}@manygym.com")

    # 1. Malformed UUID in path -> 404
    detail_res = client.get(f"/api/v1/plans/{invalid_uuid}/")
    assert detail_res.status_code == 404

    status_res = client.post(f"/api/v1/plans/{invalid_uuid}/status/", {"plan_status": "active"}, format="json")
    assert status_res.status_code == 404

    amenities_res = client.put(f"/api/v1/plans/{invalid_uuid}/amenities/", {"amenity_ids": []}, format="json")
    assert amenities_res.status_code == 404

    # 2. Malformed gym_id in query parameter -> 404
    list_url = f"{reverse('membership-plans-list-create')}?gym_id={invalid_uuid}"
    list_res = client.get(list_url)
    assert list_res.status_code == 404


@pytest.mark.django_db
def test_nonexistent_uuids_return_404():
    _, _, _, client = setup_gym_and_plan("nonexistent_uuid@manygym.com")
    non_existent_id = uuid.uuid4()

    detail_res = client.get(reverse("membership-plan-detail", kwargs={"plan_id": non_existent_id}))
    assert detail_res.status_code == 404

    patch_res = client.patch(reverse("membership-plan-detail", kwargs={"plan_id": non_existent_id}), {"name": "New"}, format="json")
    assert patch_res.status_code == 404

    delete_res = client.delete(reverse("membership-plan-detail", kwargs={"plan_id": non_existent_id}))
    assert delete_res.status_code == 404

    status_res = client.post(reverse("membership-plan-status", kwargs={"plan_id": non_existent_id}), {"plan_status": "active"}, format="json")
    assert status_res.status_code == 404

    amenities_res = client.put(reverse("membership-plan-amenities-sync", kwargs={"plan_id": non_existent_id}), {"amenity_ids": []}, format="json")
    assert amenities_res.status_code == 404


# =====================================================================
# 5. QUERY PARAMETERS, FILTERS, SEARCH & PAGINATION
# =====================================================================

@pytest.mark.django_db
def test_filters_search_and_pagination_edge_cases():
    _, gym, plan, client = setup_gym_and_plan("query_edge@manygym.com")
    url = reverse("membership-plans-list-create")

    # 1. Non-existent filter values return empty list gracefully (no 500)
    res_status = client.get(f"{url}?plan_status=non_existent_status")
    assert res_status.status_code == 200
    assert len(res_status.json()) == 0

    res_type = client.get(f"{url}?plan_type=alien_type")
    assert res_type.status_code == 200
    assert len(res_type.json()) == 0

    # 2. Whitespace-only filters -> return all gym plans
    res_ws = client.get(f"{url}?plan_status=   &plan_type=   ")
    assert res_ws.status_code == 200
    assert len(res_ws.json()) >= 1

    # 3. 5,000 characters search string -> 200 safe
    res_long_search = client.get(f"{url}?search={'A' * 5000}")
    assert res_long_search.status_code == 200
    assert len(res_long_search.json()) == 0

    # 4. Unknown and garbage query parameters ignored
    res_garbage = client.get(f"{url}?random_param=123&garbage=xyz&foo=bar")
    assert res_garbage.status_code == 200

    # 5. Pagination boundary edge cases
    # Invalid page numbers return 404
    for bad_page in [0, -1, "abc", 999999]:
        res_bad_page = client.get(f"{url}?page={bad_page}&page_size=2")
        assert res_bad_page.status_code == 404

    # Invalid page sizes fallback gracefully to default pagination (no 500)
    for bad_size in [0, -5, "abc", 99999]:
        res_bad_size = client.get(f"{url}?page=1&page_size={bad_size}")
        assert res_bad_size.status_code == 200


@pytest.mark.django_db
def test_metrics_on_gym_with_zero_plans():
    owner, client, _ = create_user_with_tokens("empty_metrics@manygym.com")
    empty_gym = create_gym(owner_user=owner, name="Empty Gym")
    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=empty_gym)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    url = reverse("membership-plans-metrics")
    res = client.get(url)
    assert res.status_code == 200
    data = res.json()
    assert data["total_plans"] == 0
    assert data["active_plans"] == 0
    assert data["avg_price"] is None
    assert data["min_price"] is None
    assert data["max_price"] is None


# =====================================================================
# 6. SECURITY & INJECTION TESTING
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("injection_payload", [
    "' OR 1=1 --",
    "\" OR \"\"=\"",
    "'; DROP TABLE membership_plans; --",
    "' UNION SELECT NULL, NULL, NULL --",
    "admin' --",
])
def test_sqli_resilience_in_plans(injection_payload):
    _, _, _, client = setup_gym_and_plan(f"sqli_{injection_payload[:4].strip()}@manygym.com")
    url = reverse("membership-plans-list-create")

    # SQLi in query parameter search
    search_res = client.get(f"{url}?search={injection_payload}")
    assert search_res.status_code == 200

    # SQLi in plan name creation
    create_res = client.post(url, {
        "name": f"SQLi Plan {injection_payload}",
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 1,
        "duration_unit": "month",
        "cancellation_policy": injection_payload,
        "refund_policy": injection_payload,
    }, format="json")
    assert create_res.status_code == 201
    assert MembershipPlan.objects.filter(name__contains=injection_payload).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("xss_payload", [
    "<script>alert('XSS')</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(document.cookie)",
    "<svg/onload=alert(1)>",
    "'\"><script src=//evil.com></script>",
])
def test_xss_payload_safety_in_plans(xss_payload):
    _, _, _, client = setup_gym_and_plan(f"xss_{xss_payload[:6].strip()}@manygym.com")
    url = reverse("membership-plans-list-create")

    res = client.post(url, {
        "name": f"XSS {xss_payload}",
        "description": f"Safe Description with minimum 50 characters: {xss_payload}",
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 1,
        "duration_unit": "month",
        "cancellation_policy": xss_payload,
        "refund_policy": xss_payload,
    }, format="json")
    assert res.status_code == 201
    data = res.json()
    assert xss_payload in data["name"]


@pytest.mark.django_db
@pytest.mark.parametrize("unicode_string", [
    "🏋️‍♀️🔥💪⚡️",
    "خطة اللياقة البدنية الذهبية",
    "ゴールドメンバーシッププラン",
    "Z̷a̷l̷g̷o̷ ̷T̷e̷x̷t̷",
    "Élite Plan & Spa Ñandú",
    "../../etc/passwd",
])
def test_unicode_and_path_traversal_resilience(unicode_string):
    _, _, _, client = setup_gym_and_plan(f"unicode_{unicode_string[:4].strip()}@manygym.com")
    url = reverse("membership-plans-list-create")

    # Create plan with Unicode / Traversal string
    create_res = client.post(url, {
        "name": f"Uni {unicode_string}",
        "description": f"Comprehensive 50-character minimum test description: {unicode_string}",
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 1,
        "duration_unit": "month",
    }, format="json")
    assert create_res.status_code == 201
    assert unicode_string in create_res.json()["name"]

    # Search with Unicode string
    search_res = client.get(f"{url}?search={unicode_string}")
    assert search_res.status_code == 200


# =====================================================================
# 7. AUTHENTICATION & AUTHORIZATION
# =====================================================================

@pytest.mark.django_db
def test_unauthenticated_requests_rejected():
    anonymous_client = APIClient()
    dummy_id = uuid.uuid4()

    endpoints = [
        ("GET", reverse("membership-plans-list-create")),
        ("POST", reverse("membership-plans-list-create")),
        ("GET", reverse("membership-plans-metrics")),
        ("GET", reverse("membership-plan-detail", kwargs={"plan_id": dummy_id})),
        ("PATCH", reverse("membership-plan-detail", kwargs={"plan_id": dummy_id})),
        ("DELETE", reverse("membership-plan-detail", kwargs={"plan_id": dummy_id})),
        ("POST", reverse("membership-plan-status", kwargs={"plan_id": dummy_id})),
        ("PUT", reverse("membership-plan-amenities-sync", kwargs={"plan_id": dummy_id})),
    ]

    for method, url in endpoints:
        res = getattr(anonymous_client, method.lower())(url)
        assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Failed for {method} {url}"


@pytest.mark.django_db
def test_staff_permission_and_scope_enforcement():
    """
    Ensures staff members without appropriate scopes (plans:read, plans:write, plans:delete)
    are rejected with 403 Forbidden.
    """
    owner, gym, plan, _ = setup_gym_and_plan("scope_owner@manygym.com")

    # Create staff user without plan permissions
    staff_user, staff_client, _ = create_user_with_tokens("staff.noscope@manygym.com")
    role_empty = Role.objects.create(name="Restricted Role", slug="restricted-role", is_custom=True)
    GymStaffAssignment.objects.create(gym=gym, user=staff_user, role=role_empty)

    # Issue gym context token for staff user (scopes will be empty)
    tokens = issue_context_token(staff_user, context_type=TokenContextType.GYM, gym=gym)
    staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    list_url = reverse("membership-plans-list-create")
    detail_url = reverse("membership-plan-detail", kwargs={"plan_id": plan.id})
    metrics_url = reverse("membership-plans-metrics")
    status_url = reverse("membership-plan-status", kwargs={"plan_id": plan.id})
    amenities_url = reverse("membership-plan-amenities-sync", kwargs={"plan_id": plan.id})

    # Read requires plans:read
    assert staff_client.get(list_url).status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.get(detail_url).status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.get(metrics_url).status_code == status.HTTP_403_FORBIDDEN

    # Write requires plans:write
    assert staff_client.post(list_url, {"name": "X", "plan_type": "time_based", "price": "10.00", "duration_value": 1, "duration_unit": "month"}, format="json").status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.patch(detail_url, {"name": "Y"}, format="json").status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.post(status_url, {"plan_status": "active"}, format="json").status_code == status.HTTP_403_FORBIDDEN
    assert staff_client.put(amenities_url, {"amenity_ids": []}, format="json").status_code == status.HTTP_403_FORBIDDEN

    # Delete requires plans:delete
    assert staff_client.delete(detail_url).status_code == status.HTTP_403_FORBIDDEN


# =====================================================================
# 8. IDOR & OBJECT-LEVEL AUTHORIZATION
# =====================================================================

@pytest.mark.django_db
def test_idor_cross_tenant_isolation_on_plans():
    """
    Ensures Gym A cannot view, update, delete, transition, or sync amenities on Gym B's plans.
    """
    _, gym_a, plan_a, client_a = setup_gym_and_plan("idor_gym_a@manygym.com")
    _, gym_b, plan_b, client_b = setup_gym_and_plan("idor_gym_b@manygym.com")

    # Gym A attempts actions on Gym B's plan
    url_b_detail = reverse("membership-plan-detail", kwargs={"plan_id": plan_b.id})
    url_b_status = reverse("membership-plan-status", kwargs={"plan_id": plan_b.id})
    url_b_amenities = reverse("membership-plan-amenities-sync", kwargs={"plan_id": plan_b.id})

    # GET Gym B's plan -> 404 (does not exist in Gym A context)
    assert client_a.get(url_b_detail).status_code == 404

    # PATCH Gym B's plan -> 404
    assert client_a.patch(url_b_detail, {"name": "Hacked Plan"}, format="json").status_code == 404

    # DELETE Gym B's plan -> 404
    assert client_a.delete(url_b_detail).status_code == 404

    # Transition Gym B's plan status -> 404
    assert client_a.post(url_b_status, {"plan_status": "active"}, format="json").status_code == 404

    # Sync amenities on Gym B's plan -> 404
    assert client_a.put(url_b_amenities, {"amenity_ids": []}, format="json").status_code == 404


# =====================================================================
# 9. BUSINESS LOGIC & INVALID STATE TRANSITIONS
# =====================================================================

@pytest.mark.django_db
def test_invalid_state_transitions_and_business_rules():
    _, gym, plan, client = setup_gym_and_plan("business_rules@manygym.com")
    status_url = reverse("membership-plan-status", kwargs={"plan_id": plan.id})
    detail_url = reverse("membership-plan-detail", kwargs={"plan_id": plan.id})

    # 1. draft -> active (valid)
    res_active = client.post(status_url, {"plan_status": "active"}, format="json")
    assert res_active.status_code == 200
    assert res_active.json()["plan_status"] == "active"

    # 2. active -> archived (valid)
    res_archived = client.post(status_url, {"plan_status": "archived"}, format="json")
    assert res_archived.status_code == 200
    assert res_archived.json()["plan_status"] == "archived"

    # 3. archived -> draft (FORBIDDEN invariant) -> 400
    res_forbidden = client.post(status_url, {"plan_status": "draft"}, format="json")
    assert res_forbidden.status_code == 400
    assert "cannot be reverted back to draft" in str(res_forbidden.json()).lower()

    # 4. Incompatible plan type and duration unit combinations -> 400
    create_url = reverse("membership-plans-list-create")
    res_incompatible1 = client.post(create_url, {
        "name": "Invalid Unit Plan",
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 5,
        "duration_unit": "session",  # Invalid for time_based
    }, format="json")
    assert res_incompatible1.status_code == 400

    res_incompatible2 = client.post(create_url, {
        "name": "Invalid Session Plan",
        "plan_type": "session_based",
        "price": "50.00",
        "duration_value": 5,
        "duration_unit": "month",  # Invalid for session_based
    }, format="json")
    assert res_incompatible2.status_code == 400

    # 5. Duplicate amenity IDs in sync amenities are gracefully deduplicated (NO 500 IntegrityError)
    cat = AmenityCatalog.objects.create(name="Towel Service", group_name=AmenityGroupEnum.CHANGING_AND_STORAGE)
    gym_amenity = GymAmenity.objects.create(gym=gym, amenity=cat, is_paid=False)
    amenities_url = reverse("membership-plan-amenities-sync", kwargs={"plan_id": plan.id})

    # Send duplicates [aid, aid, aid]
    res_dups = client.put(amenities_url, {"amenity_ids": [str(gym_amenity.id), str(gym_amenity.id)]}, format="json")
    assert res_dups.status_code == 200
    assert len(res_dups.json()["included_amenities"]) == 1


# =====================================================================
# 10. HTTP METHOD VALIDATION (405 METHOD NOT ALLOWED)
# =====================================================================

@pytest.mark.django_db
def test_unsupported_http_methods_on_all_phase3_endpoints():
    _, _, plan, client = setup_gym_and_plan("methods_test@manygym.com")

    list_url = reverse("membership-plans-list-create")
    detail_url = reverse("membership-plan-detail", kwargs={"plan_id": plan.id})
    metrics_url = reverse("membership-plans-metrics")
    status_url = reverse("membership-plan-status", kwargs={"plan_id": plan.id})
    amenities_url = reverse("membership-plan-amenities-sync", kwargs={"plan_id": plan.id})

    # /api/v1/plans/ -> PUT, DELETE unsupported
    assert client.put(list_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.delete(list_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # /api/v1/plans/{id}/ -> POST unsupported
    assert client.post(detail_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # /api/v1/plans/{id}/status/ -> GET, PUT, DELETE unsupported
    assert client.get(status_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.put(status_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.delete(status_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # /api/v1/plans/{id}/amenities/ -> GET, POST, DELETE unsupported
    assert client.get(amenities_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.post(amenities_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.delete(amenities_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # /api/v1/plans/metrics/ -> POST, PUT, PATCH, DELETE unsupported
    assert client.post(metrics_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.put(metrics_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.patch(metrics_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert client.delete(metrics_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# =====================================================================
# 11. STANDARDIZED ERROR ENVELOPE CONSISTENCY
# =====================================================================

@pytest.mark.django_db
def test_standardized_error_envelope_consistency():
    """
    Ensures every 4xx response conforms to the standard error structure:
    {"code": "...", "message": "...", "details": {...}}
    """
    _, _, plan, client = setup_gym_and_plan("envelope_test@manygym.com")

    # 400 Bad Request
    res_400 = client.post(reverse("membership-plans-list-create"), {}, format="json")
    assert res_400.status_code == 400
    data_400 = res_400.json()
    assert "code" in data_400
    assert "message" in data_400
    assert "details" in data_400

    # 404 Not Found
    res_404 = client.get(reverse("membership-plan-detail", kwargs={"plan_id": uuid.uuid4()}))
    assert res_404.status_code == 404
    data_404 = res_404.json()
    assert "code" in data_404
    assert "message" in data_404
