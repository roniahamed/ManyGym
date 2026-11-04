import io
import uuid
from decimal import Decimal
from datetime import date, timedelta
import pytest
from django.urls import reverse
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym, GymBlockedUser
from apps.gyms.services import create_gym
from apps.access_control.models import GymStaffAssignment, StaffStatus, Role, Permission, RolePermission
from apps.members.models import Member, MemberRequest
from apps.memberships.models import MembershipPlan
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    MemberRequestStatus,
    MemberJoiningStatus,
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    AudienceJoiningRequestEnum,
    PaymentMethodEnum,
)


def make_auth_client(user: User) -> APIClient:
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def owner_user(db):
    user = User.objects.create_user(
        email=f"owner_{uuid.uuid4().hex[:8]}@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    return user


@pytest.fixture
def other_owner(db):
    user = User.objects.create_user(
        email=f"other_owner_{uuid.uuid4().hex[:8]}@example.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Other",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    return user


@pytest.fixture
def normal_user(db):
    user = User.objects.create_user(
        email=f"user_{uuid.uuid4().hex[:8]}@example.com",
        password="SecurePassword123!",
        first_name="John",
        last_name="Applicant",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    return user


@pytest.fixture
def second_user(db):
    user = User.objects.create_user(
        email=f"second_{uuid.uuid4().hex[:8]}@example.com",
        password="SecurePassword123!",
        first_name="Sarah",
        last_name="Victim",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    return user


@pytest.fixture
def gym(owner_user):
    return create_gym(owner_user=owner_user, name="Main Edge Gym")


@pytest.fixture
def other_gym(other_owner):
    return create_gym(owner_user=other_owner, name="Other Security Gym")


@pytest.fixture
def plan(gym):
    return MembershipPlan.objects.create(
        gym=gym,
        name="Standard Plan",
        price=Decimal("49.99"),
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )


@pytest.fixture
def other_gym_plan(other_gym):
    return MembershipPlan.objects.create(
        gym=other_gym,
        name="Foreign Plan",
        price=Decimal("120.00"),
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )


@pytest.fixture
def staff_user(db, gym):
    user = User.objects.create_user(
        email=f"staff_{uuid.uuid4().hex[:8]}@example.com",
        password="SecurePassword123!",
        first_name="Staff",
        last_name="Member",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    role = Role.objects.create(gym=gym, name="Member Manager", slug=f"member-mgr-{uuid.uuid4().hex[:6]}", description="Staff")
    p_read, _ = Permission.objects.get_or_create(scope_code="members:read", defaults={"name": "Read Members", "topic": "members"})
    p_edit, _ = Permission.objects.get_or_create(scope_code="members:edit", defaults={"name": "Edit Members", "topic": "members"})
    RolePermission.objects.create(role=role, permission=p_read)
    RolePermission.objects.create(role=role, permission=p_edit)
    GymStaffAssignment.objects.create(
        gym=gym,
        user=user,
        role=role,
        status=StaffStatus.ACTIVE,
    )
    return user


@pytest.fixture
def read_only_staff_user(db, gym):
    user = User.objects.create_user(
        email=f"ro_staff_{uuid.uuid4().hex[:8]}@example.com",
        password="SecurePassword123!",
        first_name="ReadOnly",
        last_name="Staff",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    role = Role.objects.create(gym=gym, name="Read Only Staff", slug=f"ro-staff-{uuid.uuid4().hex[:6]}", description="Staff")
    p_read, _ = Permission.objects.get_or_create(scope_code="members:read", defaults={"name": "Read Members", "topic": "members"})
    RolePermission.objects.create(role=role, permission=p_read)
    GymStaffAssignment.objects.create(
        gym=gym,
        user=user,
        role=role,
        status=StaffStatus.ACTIVE,
    )
    return user


# ==============================================================================
# 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
# ==============================================================================
@pytest.mark.django_db
class TestDataTypesAndTypeJuggling:

    def test_submit_request_type_mismatches(self, normal_user, gym):
        client = make_auth_client(normal_user)
        url = reverse("member-request-list")

        mismatched_payloads = [
            {"gym_id": 12345},
            {"gym_id": True},
            {"gym_id": ["not-a-uuid"]},
            {"gym_id": {"nested": "dict"}},
            {"gym_id": str(gym.id), "notes": 12345},
            {"gym_id": str(gym.id), "notes": True},
            {"gym_id": str(gym.id), "notes": ["list", "of", "strings"]},
            {"gym_id": str(gym.id), "notes": {"nested": "dict"}},
            {"gym_id": str(gym.id), "interested_plan_id": 12345},
            {"gym_id": str(gym.id), "interested_plan_id": True},
            {"gym_id": str(gym.id), "interested_plan_id": ["uuid"]},
            {"gym_id": str(gym.id), "interested_plan_id": {"id": "123"}},
        ]

        for payload in mismatched_payloads:
            res = client.post(url, data=payload, format="json")
            assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND), (
                f"Expected 400 or 404 for payload {payload}, got {res.status_code}: {res.data}"
            )
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_accept_request_type_mismatches(self, owner_user, gym, normal_user, plan):
        req = MemberRequest.objects.create(gym=gym, user=normal_user, interested_plan=plan)
        client = make_auth_client(owner_user)
        url = reverse("member-request-accept", kwargs={"request_id": req.id})

        mismatched_payloads = [
            {"gym_id": str(gym.id), "first_name": 12345},
            {"gym_id": str(gym.id), "first_name": True},
            {"gym_id": str(gym.id), "first_name": ["Jane"]},
            {"gym_id": str(gym.id), "first_name": {"nested": "name"}},
            {"gym_id": str(gym.id), "last_name": 12345},
            {"gym_id": str(gym.id), "last_name": {"nested": "last"}},
            {"gym_id": str(gym.id), "email": ["not_a_string@test.com"]},
            {"gym_id": str(gym.id), "email": {"email": "obj"}},
            {"gym_id": str(gym.id), "email": 12345},
            {"gym_id": str(gym.id), "initial_payment_amount": "twenty"},
            {"gym_id": str(gym.id), "initial_payment_amount": ["100.00"]},
            {"gym_id": str(gym.id), "initial_payment_amount": {"amt": "100.00"}},
            {"gym_id": str(gym.id), "initial_payment_amount": True},
            {"gym_id": str(gym.id), "initial_payment_method": 12345},
            {"gym_id": str(gym.id), "initial_payment_method": ["cash"]},
            {"gym_id": str(gym.id), "initial_payment_method": {"method": "cash"}},
            {"gym_id": str(gym.id), "extra_amenity_ids": "not-a-list"},
            {"gym_id": str(gym.id), "extra_amenity_ids": 12345},
            {"gym_id": str(gym.id), "extra_amenity_ids": {"id": "123"}},
            {"gym_id": str(gym.id), "plan_id": 12345},
            {"gym_id": str(gym.id), "plan_id": ["not-a-uuid"]},
            {"gym_id": str(gym.id), "plan_id": {"id": "test"}},
            {"gym_id": str(gym.id), "assigned_trainer_id": 9999},
            {"gym_id": str(gym.id), "assigned_trainer_id": ["trainer"]},
        ]

        for payload in mismatched_payloads:
            res = client.post(url, data=payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, (
                f"Expected 400 for payload {payload}, got {res.status_code}: {res.data}"
            )
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_reject_request_type_mismatches(self, owner_user, gym, normal_user):
        req = MemberRequest.objects.create(gym=gym, user=normal_user)
        client = make_auth_client(owner_user)
        url = reverse("member-request-reject", kwargs={"request_id": req.id})

        mismatched_payloads = [
            {"gym_id": str(gym.id), "rejection_reason": 12345},
            {"gym_id": str(gym.id), "rejection_reason": True},
            {"gym_id": str(gym.id), "rejection_reason": ["list", "reason"]},
            {"gym_id": str(gym.id), "rejection_reason": {"reason": "nested"}},
        ]

        for payload in mismatched_payloads:
            res = client.post(url, data=payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, (
                f"Expected 400 for payload {payload}, got {res.status_code}: {res.data}"
            )
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==============================================================================
# 2. BOUNDARY & LENGTH EDGE CASES
# ==============================================================================
@pytest.mark.django_db
class TestBoundaryAndLengthEdgeCases:

    def test_submit_notes_string_boundaries(self, normal_user, gym):
        client = make_auth_client(normal_user)
        url = reverse("member-request-list")

        # 1. Empty string & whitespace
        for blank_val in ["", " ", "   ", "\t", "\n\r\n"]:
            res = client.post(url, data={"gym_id": str(gym.id), "notes": blank_val}, format="json")
            assert res.status_code == status.HTTP_201_CREATED, f"Failed for blank val '{blank_val}': {res.data}"
            req_id = res.data["request_id"]
            MemberRequest.objects.filter(id=req_id).delete()

        # 2. Exactly max_length (500)
        max_str = "A" * 500
        res = client.post(url, data={"gym_id": str(gym.id), "notes": max_str}, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        req_id = res.data["request_id"]
        MemberRequest.objects.filter(id=req_id).delete()

        # 3. Beyond max_length (501 and 10,000+ characters)
        over_max = "B" * 501
        res = client.post(url, data={"gym_id": str(gym.id), "notes": over_max}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        huge_str = "C" * 12000
        res = client.post(url, data={"gym_id": str(gym.id), "notes": huge_str}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_reject_reason_length_boundaries(self, owner_user, gym, normal_user):
        req = MemberRequest.objects.create(gym=gym, user=normal_user)
        client = make_auth_client(owner_user)
        url = reverse("member-request-reject", kwargs={"request_id": req.id})

        # Beyond 500 chars -> 400
        res = client.post(url, data={"gym_id": str(gym.id), "rejection_reason": "R" * 501}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        res = client.post(url, data={"gym_id": str(gym.id), "rejection_reason": "R" * 10000}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Exactly 500 chars -> 200
        res = client.post(url, data={"gym_id": str(gym.id), "rejection_reason": "R" * 500}, format="json")
        assert res.status_code == status.HTTP_200_OK
        req.refresh_from_db()
        assert req.status == MemberRequestStatus.REJECTED

    def test_initial_payment_numeric_boundaries(self, owner_user, gym, normal_user, plan):
        client = make_auth_client(owner_user)

        # Negative amount
        req1 = MemberRequest.objects.create(gym=gym, user=normal_user, interested_plan=plan)
        url1 = reverse("member-request-accept", kwargs={"request_id": req1.id})
        res = client.post(url1, data={
            "gym_id": str(gym.id),
            "initial_payment_amount": "-50.00",
            "initial_payment_method": "cash",
        }, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Zero amount (min_value is 0.01)
        res = client.post(url1, data={
            "gym_id": str(gym.id),
            "initial_payment_amount": "0.00",
            "initial_payment_method": "cash",
        }, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Very large positive amount exceeding 10 digits
        res = client.post(url1, data={
            "gym_id": str(gym.id),
            "initial_payment_amount": "99999999999999999999.00",
            "initial_payment_method": "cash",
        }, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Valid minimum boundary 0.01
        res = client.post(url1, data={
            "gym_id": str(gym.id),
            "initial_payment_amount": "0.01",
            "initial_payment_method": "cash",
        }, format="json")
        assert res.status_code == status.HTTP_201_CREATED


# ==============================================================================
# 3. MISSING, EXTRA & MALFORMED FIELDS
# ==============================================================================
@pytest.mark.django_db
class TestMissingExtraAndMalformedFields:

    def test_completely_empty_body(self, normal_user, owner_user, gym):
        client_user = make_auth_client(normal_user)
        client_owner = make_auth_client(owner_user)

        # 1. Submit request with empty body and no query param -> 400 (missing gym_id)
        url_submit = reverse("member-request-list")
        res = client_user.post(url_submit, data={}, format="json")
        assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)

        # 2. Reject request with empty body -> valid because rejection_reason is optional
        req = MemberRequest.objects.create(gym=gym, user=normal_user)
        url_reject = reverse("member-request-reject", kwargs={"request_id": req.id})
        res = client_owner.post(f"{url_reject}?gym_id={gym.id}", data={}, format="json")
        assert res.status_code == status.HTTP_200_OK

        # 3. Cancel with empty body -> valid (takes request_id from URL)
        req2 = MemberRequest.objects.create(gym=gym, user=normal_user)
        url_cancel = reverse("member-request-cancel", kwargs={"request_id": req2.id})
        res = client_user.post(url_cancel, data={}, format="json")
        assert res.status_code == status.HTTP_200_OK

    def test_one_hundred_unexpected_garbage_fields(self, normal_user, gym):
        client = make_auth_client(normal_user)
        url = reverse("member-request-list")

        payload = {"gym_id": str(gym.id), "notes": "Testing garbage fields"}
        for i in range(120):
            payload[f"unexpected_garbage_field_{i}"] = f"garbage_value_{i}"

        res = client.post(url, data=payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert "request_id" in res.data
        MemberRequest.objects.filter(id=res.data["request_id"]).delete()

    def test_mass_assignment_and_privilege_escalation_tampering(self, normal_user, gym):
        client = make_auth_client(normal_user)
        url = reverse("member-request-list")

        forged_id = str(uuid.uuid4())
        forged_member_id = str(uuid.uuid4())
        malicious_payload = {
            "gym_id": str(gym.id),
            "id": forged_id,
            "status": "accepted",
            "created_member_id": forged_member_id,
            "reviewed_by_id": str(normal_user.id),
            "reviewed_at": "2020-01-01T00:00:00Z",
            "is_superuser": True,
            "notes": "Trying to forge fields",
        }

        res = client.post(url, data=malicious_payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED

        created_id = res.data["request_id"]
        # Invariant: Server generated its own ID, status is pending, created_member_id is None
        assert created_id != forged_id
        req_obj = MemberRequest.objects.get(id=created_id)
        assert req_obj.status == MemberRequestStatus.PENDING
        assert req_obj.created_member_id is None
        assert req_obj.reviewed_by is None
        assert req_obj.reviewed_at is None


# ==============================================================================
# 4. FORMAT-SPECIFIC INVALID INPUTS
# ==============================================================================
@pytest.mark.django_db
class TestFormatSpecificInvalidInputs:

    def test_invalid_dates_in_accept_request(self, owner_user, gym, normal_user, plan):
        req = MemberRequest.objects.create(gym=gym, user=normal_user, interested_plan=plan)
        client = make_auth_client(owner_user)
        url = reverse("member-request-accept", kwargs={"request_id": req.id})

        invalid_dates = [
            "2026-13-45",
            "31/12/2026",
            "today",
            "yesterday",
            "2026-02-30",
            "not-a-date",
            1700000000,
        ]

        for d in invalid_dates:
            res = client.post(url, data={
                "gym_id": str(gym.id),
                "start_date": d,
            }, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_end_date_prior_to_start_date(self, owner_user, gym, normal_user, plan):
        req = MemberRequest.objects.create(gym=gym, user=normal_user, interested_plan=plan)
        client = make_auth_client(owner_user)
        url = reverse("member-request-accept", kwargs={"request_id": req.id})

        res = client.post(url, data={
            "gym_id": str(gym.id),
            "start_date": "2026-05-10",
            "end_date": "2026-05-01",
        }, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "end_date" in str(res.data)

    def test_invalid_emails_in_accept_request(self, owner_user, gym, normal_user, plan):
        client = make_auth_client(owner_user)

        invalid_emails = [
            "plainaddress",
            "#@%^%#$@#$@#.com",
            "@example.com",
            "Joe Smith <email@example.com>",
            "email.example.com",
            "email@example@example.com",
            ".email@example.com",
            "email.@example.com",
            "email..email@example.com",
            "email @example.com",
        ]

        for em in invalid_emails:
            req = MemberRequest.objects.create(gym=gym, user=normal_user, interested_plan=plan)
            url = reverse("member-request-accept", kwargs={"request_id": req.id})
            res = client.post(url, data={
                "gym_id": str(gym.id),
                "email": em,
            }, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400 for '{em}', got {res.status_code}: {res.data}"
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
            req.delete()

    def test_invalid_uuids_everywhere(self, owner_user, gym, normal_user):
        client = make_auth_client(owner_user)

        # 1. In URL path parameter
        url_bad_uuid = "/api/v1/members/requests/not-a-valid-uuid/"
        res = client.get(url_bad_uuid)
        assert res.status_code == status.HTTP_404_NOT_FOUND

        url_bad_accept = "/api/v1/members/requests/12345/accept/"
        res = client.post(url_bad_accept, data={"gym_id": str(gym.id)}, format="json")
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # 2. In query params
        res = client.get(f"{reverse('member-request-list')}?gym_id=invalid-gym-uuid")
        assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)

        # 3. Non-existent UUID in path parameter
        non_existent_uuid = uuid.uuid4()
        res = client.get(f"{reverse('member-request-detail', kwargs={'request_id': non_existent_uuid})}?gym_id={gym.id}")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_unsupported_file_upload_in_profile_photo(self, owner_user, gym, normal_user, plan):
        req = MemberRequest.objects.create(gym=gym, user=normal_user, interested_plan=plan)
        client = make_auth_client(owner_user)
        url = reverse("member-request-accept", kwargs={"request_id": req.id})

        bad_file = SimpleUploadedFile("malicious.exe", b"MZ\x90\x00\x03\x00\x00\x00", content_type="application/x-dosexec")
        res = client.post(f"{url}?gym_id={gym.id}", data={
            "profile_photo": bad_file,
        }, format="multipart")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "profile_photo" in str(res.data)


# ==============================================================================
# 5. QUERY PARAMETERS, FILTERS, SEARCH & PAGINATION
# ==============================================================================
@pytest.mark.django_db
class TestQueryParametersFiltersSearchPagination:

    def test_pagination_boundary_and_garbage_values(self, owner_user, gym, normal_user):
        MemberRequest.objects.create(gym=gym, user=normal_user, notes="Searchable request")
        client = make_auth_client(owner_user)
        base_url = reverse("member-request-list")

        cases = [
            f"?gym_id={gym.id}&page=0",
            f"?gym_id={gym.id}&page=-1",
            f"?gym_id={gym.id}&page=abc",
            f"?gym_id={gym.id}&page=99999999",
            f"?gym_id={gym.id}&page_size=0",
            f"?gym_id={gym.id}&page_size=-1",
            f"?gym_id={gym.id}&page_size=abc",
            f"?gym_id={gym.id}&page_size=1000000",
            f"?gym_id={gym.id}&page=1&page_size=10",
        ]

        for query in cases:
            res = client.get(f"{base_url}{query}")
            assert res.status_code in (status.HTTP_200_OK, status.HTTP_404_NOT_FOUND), (
                f"Unexpected status {res.status_code} for query '{query}': {res.data}"
            )
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_search_and_status_filter_edge_cases(self, owner_user, gym, normal_user):
        MemberRequest.objects.create(gym=gym, user=normal_user, notes="Active testing item")
        client = make_auth_client(owner_user)
        base_url = reverse("member-request-list")

        filter_cases = [
            f"?gym_id={gym.id}&status=UNKNOWN_STATUS_XYZ",
            f"?gym_id={gym.id}&status=",
            f"?gym_id={gym.id}&status=   ",
            f"?gym_id={gym.id}&status=PENDING",
            f"?gym_id={gym.id}&status=pending",
            f"?gym_id={gym.id}&search=",
            f"?gym_id={gym.id}&search=   ",
            f"?gym_id={gym.id}&search={'X' * 5000}",
            f"?gym_id={gym.id}&search={'%20' * 50}",
            f"?gym_id={gym.id}&search=John",
            f"?gym_id={gym.id}&search=NonExistentApplicantName",
            f"?gym_id={gym.id}&random_garbage_param=true&another_param=123",
        ]

        for query in filter_cases:
            res = client.get(f"{base_url}{query}")
            assert res.status_code == status.HTTP_200_OK, f"Failed for {query}: {res.data}"
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==============================================================================
# 6. SECURITY & INJECTION TESTING
# ==============================================================================
@pytest.mark.django_db
class TestSecurityAndInjection:

    def test_sql_injection_payloads_in_all_inputs(self, normal_user, owner_user, gym):
        client_user = make_auth_client(normal_user)
        client_owner = make_auth_client(owner_user)

        sqli_payloads = [
            "' OR 1=1 --",
            '" OR ""="',
            "'; DROP TABLE member_requests; --",
            "1; SELECT pg_sleep(1); --",
            "' UNION SELECT id, email, password FROM users --",
            "admin' --",
        ]

        # 1. SQLi in search query parameter
        list_url = reverse("member-request-list")
        for payload in sqli_payloads:
            res = client_owner.get(f"{list_url}?gym_id={gym.id}&search={payload}")
            assert res.status_code == status.HTTP_200_OK
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

        # 2. SQLi in notes body parameter
        for payload in sqli_payloads:
            res = client_user.post(list_url, data={"gym_id": str(gym.id), "notes": payload}, format="json")
            assert res.status_code in (status.HTTP_201_CREATED, status.HTTP_200_OK)
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
            if "request_id" in res.data:
                MemberRequest.objects.filter(id=res.data["request_id"]).delete()

        # 3. SQLi in rejection_reason
        req = MemberRequest.objects.create(gym=gym, user=normal_user)
        reject_url = reverse("member-request-reject", kwargs={"request_id": req.id})
        for payload in sqli_payloads:
            res = client_owner.post(f"{reject_url}?gym_id={gym.id}", data={"rejection_reason": payload}, format="json")
            assert res.status_code in (status.HTTP_200_OK, status.HTTP_409_CONFLICT)
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_xss_injection_payloads(self, normal_user, owner_user, gym):
        client_user = make_auth_client(normal_user)
        client_owner = make_auth_client(owner_user)

        xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert(1)>",
            "javascript:alert(document.cookie)",
            "<svg onload=alert(1)>",
            "\"><script>alert(1)</script>",
        ]

        list_url = reverse("member-request-list")
        for payload in xss_payloads:
            res = client_user.post(list_url, data={"gym_id": str(gym.id), "notes": payload}, format="json")
            assert res.status_code == status.HTTP_201_CREATED
            req_id = res.data["request_id"]

            # Detail view returns payload cleanly without crash or execution
            detail_url = reverse("member-request-detail", kwargs={"request_id": req_id})
            det_res = client_owner.get(f"{detail_url}?gym_id={gym.id}")
            assert det_res.status_code == status.HTTP_200_OK
            assert det_res.data["notes"] == payload

            MemberRequest.objects.filter(id=req_id).delete()

    def test_adversarial_unicode_and_emojis(self, normal_user, owner_user, gym):
        client_user = make_auth_client(normal_user)
        client_owner = make_auth_client(owner_user)

        unicode_payloads = [
            "🏋️‍♂️ Gym Lover 💪🔥 💯",
            "مرحبا بكم في صالة الألعاب الرياضية",
            "ברוכים הבאים לחדר הכושר",
            "Z̷a̸l̶g̶o̶ ̸T̷e̶x̵t̶",
            "Mixed 🏋️ LTR and RTL עִבְרִית text",
        ]

        list_url = reverse("member-request-list")
        for payload in unicode_payloads:
            res = client_user.post(list_url, data={"gym_id": str(gym.id), "notes": payload}, format="json")
            assert res.status_code == status.HTTP_201_CREATED
            req_id = res.data["request_id"]

            detail_url = reverse("member-request-detail", kwargs={"request_id": req_id})
            det_res = client_owner.get(f"{detail_url}?gym_id={gym.id}")
            assert det_res.status_code == status.HTTP_200_OK
            assert det_res.data["notes"] == payload

            MemberRequest.objects.filter(id=req_id).delete()


# ==============================================================================
# 7. AUTHENTICATION, AUTHORIZATION & PERMISSIONS
# ==============================================================================
@pytest.mark.django_db
class TestAuthenticationAuthorizationPermissions:

    def test_unauthenticated_requests_return_401(self, gym):
        anon_client = APIClient()
        fake_uuid = uuid.uuid4()

        endpoints = [
            ("get", reverse("member-request-list")),
            ("post", reverse("member-request-list")),
            ("get", reverse("member-request-detail", kwargs={"request_id": fake_uuid})),
            ("post", reverse("member-request-accept", kwargs={"request_id": fake_uuid})),
            ("post", reverse("member-request-reject", kwargs={"request_id": fake_uuid})),
            ("post", reverse("member-request-cancel", kwargs={"request_id": fake_uuid})),
            ("get", reverse("gyms_v1:gym-join-request", kwargs={"gym_id": gym.id})),
        ]

        for method, url in endpoints:
            handler = getattr(anon_client, method)
            res = handler(url)
            assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Expected 401 for {method.upper()} {url}, got {res.status_code}"

    def test_malformed_and_garbage_auth_tokens(self, gym):
        client = APIClient()
        fake_uuid = uuid.uuid4()

        for bad_header in [
            "Bearer invalid_jwt_token_string",
            "Bearer ",
            "Token abc12345",
            "Basic admin:admin",
            "Bearer " + "a" * 1000,
        ]:
            client.credentials(HTTP_AUTHORIZATION=bad_header)
            res = client.get(reverse("member-request-list"))
            assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_non_staff_user_cannot_access_staff_endpoints(self, normal_user, gym):
        client = make_auth_client(normal_user)
        req = MemberRequest.objects.create(gym=gym, user=normal_user)

        # Normal user cannot list requests
        res = client.get(f"{reverse('member-request-list')}?gym_id={gym.id}")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # Normal user cannot view details
        res = client.get(f"{reverse('member-request-detail', kwargs={'request_id': req.id})}?gym_id={gym.id}")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # Normal user cannot accept
        res = client.post(f"{reverse('member-request-accept', kwargs={'request_id': req.id})}?gym_id={gym.id}", data={}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # Normal user cannot reject
        res = client.post(f"{reverse('member-request-reject', kwargs={'request_id': req.id})}?gym_id={gym.id}", data={}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_read_only_staff_cannot_accept_or_reject(self, read_only_staff_user, gym, normal_user):
        req = MemberRequest.objects.create(gym=gym, user=normal_user)
        client = make_auth_client(read_only_staff_user)

        # Read-only staff can list and view detail
        res = client.get(f"{reverse('member-request-list')}?gym_id={gym.id}")
        assert res.status_code == status.HTTP_200_OK

        res = client.get(f"{reverse('member-request-detail', kwargs={'request_id': req.id})}?gym_id={gym.id}")
        assert res.status_code == status.HTTP_200_OK

        # Read-only staff cannot accept (requires members:edit)
        res = client.post(f"{reverse('member-request-accept', kwargs={'request_id': req.id})}?gym_id={gym.id}", data={}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # Read-only staff cannot reject (requires members:edit)
        res = client.post(f"{reverse('member-request-reject', kwargs={'request_id': req.id})}?gym_id={gym.id}", data={}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN


# ==============================================================================
# 8. IDOR & OBJECT-LEVEL AUTHORIZATION
# ==============================================================================
@pytest.mark.django_db
class TestIDORAndObjectLevelAuthorization:

    def test_user_cannot_cancel_another_users_request(self, normal_user, second_user, gym):
        # Request created by second_user
        req = MemberRequest.objects.create(gym=gym, user=second_user)

        # normal_user attempts to cancel it
        attacker_client = make_auth_client(normal_user)
        url = reverse("member-request-cancel", kwargs={"request_id": req.id})
        res = attacker_client.post(url)
        assert res.status_code == status.HTTP_404_NOT_FOUND

        req.refresh_from_db()
        assert req.status == MemberRequestStatus.PENDING

    def test_foreign_gym_admin_cannot_view_or_mutate_request(self, other_owner, gym, normal_user):
        req = MemberRequest.objects.create(gym=gym, user=normal_user)
        attacker_client = make_auth_client(other_owner)

        # Attempt to view Gym A's request as Gym B's owner
        detail_url = reverse("member-request-detail", kwargs={"request_id": req.id})
        res = attacker_client.get(f"{detail_url}?gym_id={gym.id}")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # Attempt to accept Gym A's request as Gym B's owner
        accept_url = reverse("member-request-accept", kwargs={"request_id": req.id})
        res = attacker_client.post(f"{accept_url}?gym_id={gym.id}", data={}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # Attempt to reject Gym A's request as Gym B's owner
        reject_url = reverse("member-request-reject", kwargs={"request_id": req.id})
        res = attacker_client.post(f"{reject_url}?gym_id={gym.id}", data={}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        req.refresh_from_db()
        assert req.status == MemberRequestStatus.PENDING


# ==============================================================================
# 9. BUSINESS LOGIC & INVALID STATE TRANSITIONS
# ==============================================================================
@pytest.mark.django_db
class TestBusinessLogicAndInvalidStateTransitions:

    def test_re_accepting_already_accepted_request_returns_409(self, owner_user, gym, normal_user, plan):
        req = MemberRequest.objects.create(gym=gym, user=normal_user, interested_plan=plan)
        client = make_auth_client(owner_user)
        url = reverse("member-request-accept", kwargs={"request_id": req.id})

        # First accept succeeds
        res1 = client.post(url, data={"gym_id": str(gym.id)}, format="json")
        assert res1.status_code == status.HTTP_201_CREATED

        # Second accept returns 409 Conflict
        res2 = client.post(url, data={"gym_id": str(gym.id)}, format="json")
        assert res2.status_code == status.HTTP_409_CONFLICT

    def test_rejecting_already_accepted_request_returns_409(self, owner_user, gym, normal_user, plan):
        req = MemberRequest.objects.create(gym=gym, user=normal_user, interested_plan=plan)
        client = make_auth_client(owner_user)

        res_acc = client.post(reverse("member-request-accept", kwargs={"request_id": req.id}), data={"gym_id": str(gym.id)}, format="json")
        assert res_acc.status_code == status.HTTP_201_CREATED

        res_rej = client.post(reverse("member-request-reject", kwargs={"request_id": req.id}), data={"gym_id": str(gym.id)}, format="json")
        assert res_rej.status_code == status.HTTP_409_CONFLICT

    def test_cancelling_already_accepted_or_rejected_request_returns_409(self, normal_user, owner_user, gym, plan):
        client_user = make_auth_client(normal_user)
        client_owner = make_auth_client(owner_user)

        # 1. Accepted request
        req1 = MemberRequest.objects.create(gym=gym, user=normal_user, interested_plan=plan)
        client_owner.post(reverse("member-request-accept", kwargs={"request_id": req1.id}), data={"gym_id": str(gym.id)}, format="json")
        res1 = client_user.post(reverse("member-request-cancel", kwargs={"request_id": req1.id}))
        assert res1.status_code == status.HTTP_409_CONFLICT

        # 2. Rejected request
        user2 = User.objects.create_user(email="second_req_user@example.com", password="Password123!")
        UserProfile.objects.create(user=user2)
        client_user2 = make_auth_client(user2)

        req2 = MemberRequest.objects.create(gym=gym, user=user2)
        client_owner.post(reverse("member-request-reject", kwargs={"request_id": req2.id}), data={"gym_id": str(gym.id)}, format="json")
        res2 = client_user2.post(reverse("member-request-cancel", kwargs={"request_id": req2.id}))
        assert res2.status_code == status.HTTP_409_CONFLICT

    def test_submitting_request_to_deactivated_or_deleted_gym(self, normal_user, gym):
        client = make_auth_client(normal_user)
        url = reverse("member-request-list")

        # Deactivated gym
        settings = gym.get_settings()
        settings.is_deactivated = True
        settings.save(update_fields=["is_deactivated"])

        res = client.post(url, data={"gym_id": str(gym.id)}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Soft-deleted gym
        settings.is_deactivated = False
        settings.is_deleted = True
        settings.save(update_fields=["is_deactivated", "is_deleted"])

        res = client.post(url, data={"gym_id": str(gym.id)}, format="json")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_blocked_user_joining_request_restriction(self, normal_user, gym):
        GymBlockedUser.objects.create(gym=gym, user=normal_user, reason="Security policy violation")
        client = make_auth_client(normal_user)

        res = client.post(reverse("member-request-list"), data={"gym_id": str(gym.id)}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        status_res = client.get(reverse("gyms_v1:gym-join-request", kwargs={"gym_id": gym.id}))
        assert status_res.status_code == status.HTTP_200_OK
        assert status_res.data["can_send_request"] is False
        assert status_res.data["is_blocked"] is True

    def test_existing_member_cannot_send_request(self, normal_user, gym):
        Member.objects.create(
            gym=gym,
            user=normal_user,
            first_name=normal_user.first_name,
            last_name=normal_user.last_name,
            email=normal_user.email,
            joining_status=MemberJoiningStatus.JOINED,
        )
        client = make_auth_client(normal_user)

        res = client.post(reverse("member-request-list"), data={"gym_id": str(gym.id)}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        status_res = client.get(reverse("gyms_v1:gym-join-request", kwargs={"gym_id": gym.id}))
        assert status_res.status_code == status.HTTP_200_OK
        assert status_res.data["can_send_request"] is False
        assert status_res.data["is_member"] is True

    def test_accept_request_with_trainer_or_plan_from_foreign_gym(self, owner_user, gym, normal_user, other_gym, other_gym_plan):
        req = MemberRequest.objects.create(gym=gym, user=normal_user)
        client = make_auth_client(owner_user)
        url = reverse("member-request-accept", kwargs={"request_id": req.id})

        # Plan belongs to other_gym
        res = client.post(url, data={"gym_id": str(gym.id), "plan_id": str(other_gym_plan.id)}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "plan" in str(res.data).lower()

        # Trainer belongs to other_gym
        foreign_staff = User.objects.create_user(email="foreign_staff@example.com", password="Password123!")
        UserProfile.objects.create(user=foreign_staff)
        foreign_role = Role.objects.create(gym=other_gym, name="Trainer", slug=f"trainer-{uuid.uuid4().hex[:6]}")
        foreign_assign = GymStaffAssignment.objects.create(gym=other_gym, user=foreign_staff, role=foreign_role, status=StaffStatus.ACTIVE)

        res = client.post(url, data={"gym_id": str(gym.id), "assigned_trainer_id": str(foreign_assign.id)}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "trainer" in str(res.data).lower()


# ==============================================================================
# 10. HTTP METHOD VALIDATION
# ==============================================================================
@pytest.mark.django_db
class TestHttpMethodValidation:

    def test_unsupported_methods_return_405(self, owner_user, normal_user, gym):
        client = make_auth_client(owner_user)
        req = MemberRequest.objects.create(gym=gym, user=normal_user)

        # 1. MemberRequestListView: allows GET, POST. Disallows PUT, PATCH, DELETE
        list_url = reverse("member-request-list")
        assert client.put(list_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert client.patch(list_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert client.delete(list_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # 2. MemberRequestDetailView: allows GET. Disallows POST, PUT, PATCH, DELETE
        detail_url = reverse("member-request-detail", kwargs={"request_id": req.id})
        assert client.post(detail_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert client.put(detail_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert client.delete(detail_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # 3. MemberRequestAcceptView: allows POST. Disallows GET, PUT, DELETE
        accept_url = reverse("member-request-accept", kwargs={"request_id": req.id})
        assert client.get(accept_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert client.put(accept_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert client.delete(accept_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # 4. MemberRequestRejectView: allows POST. Disallows GET, PUT, DELETE
        reject_url = reverse("member-request-reject", kwargs={"request_id": req.id})
        assert client.get(reject_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert client.put(reject_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert client.delete(reject_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # 5. MemberRequestCancelView: allows POST. Disallows GET, PUT, DELETE
        cancel_url = reverse("member-request-cancel", kwargs={"request_id": req.id})
        assert client.get(cancel_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert client.put(cancel_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert client.delete(cancel_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # 6. GymMemberJoiningRequestView: allows GET, POST. Disallows PUT, DELETE
        join_url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": gym.id})
        assert client.put(join_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert client.delete(join_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
