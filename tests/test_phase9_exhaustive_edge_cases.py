import json
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.core import mail
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User
from apps.gyms.models import Gym
from apps.memberships.models import MembershipPlan
from apps.members.models import Member, MemberSubscription
from apps.leads.models import Lead, LeadNextMove
from apps.access_control.models import GymStaffAssignment, Role, Permission, RolePermission
from apps.authentication.models import AuthToken
from apps.members.services import (
    create_member,
    reconcile_expired_subscriptions,
    send_subscription_expiry_reminders,
)
from apps.leads.services import send_lead_followup_reminders
from apps.authentication.services import cleanup_expired_tokens


@pytest.fixture(autouse=True)
def setup_email_backend():
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    if hasattr(mail, "outbox"):
        mail.outbox.clear()


@pytest.fixture
def test_environment(db):
    uid = uuid.uuid4().hex[:6]
    owner = User.objects.create_user(
        email=f"owner_{uid}@test.com",
        password="password123",
        first_name="Owner",
        last_name="Test",
    )
    gym = Gym.objects.create(
        owner_user=owner,
        name=f"Test Gym {uid}",
    )
    # Staff with members:edit permission
    staff_user = User.objects.create_user(
        email=f"staff_{uid}@test.com",
        password="password123",
        first_name="Staff",
        last_name="Test",
    )
    role_with_edit = Role.objects.create(gym=gym, name=f"Manager {uid}", slug=f"manager_{uid}")
    perm_edit, _ = Permission.objects.get_or_create(
        scope_code="members:edit",
        defaults={"name": "Edit Members", "topic": "Members"},
    )
    RolePermission.objects.get_or_create(role=role_with_edit, permission=perm_edit)
    staff_assignment = GymStaffAssignment.objects.create(
        gym=gym,
        user=staff_user,
        role=role_with_edit,
        status="active",
    )

    # Staff without members:edit permission
    staff_no_perm_user = User.objects.create_user(
        email=f"staff_noperm_{uid}@test.com",
        password="password123",
        first_name="StaffNoPerm",
        last_name="Test",
    )
    role_view_only = Role.objects.create(gym=gym, name=f"Viewer {uid}", slug=f"viewer_{uid}")
    perm_read, _ = Permission.objects.get_or_create(
        scope_code="members:read",
        defaults={"name": "Read Members", "topic": "Members"},
    )
    RolePermission.objects.get_or_create(role=role_view_only, permission=perm_read)
    GymStaffAssignment.objects.create(
        gym=gym,
        user=staff_no_perm_user,
        role=role_view_only,
        status="active",
    )

    # Another gym for cross-tenant testing
    other_owner = User.objects.create_user(
        email=f"other_owner_{uid}@test.com",
        password="password123",
        first_name="OtherOwner",
    )
    other_gym = Gym.objects.create(
        owner_user=other_owner,
        name=f"Other Gym {uid}",
    )

    # Member pending onboarding
    member = create_member(
        gym=gym,
        first_name="OnboardingMember",
        last_name="Pending",
        email=f"member_{uid}@test.com",
    )

    # Candidate user to accept invitation
    candidate_user = User.objects.create_user(
        email=f"candidate_{uid}@test.com",
        password="password123",
        first_name="Candidate",
        last_name="User",
    )

    return {
        "owner": owner,
        "gym": gym,
        "staff_user": staff_user,
        "staff_no_perm_user": staff_no_perm_user,
        "other_owner": other_owner,
        "other_gym": other_gym,
        "member": member,
        "candidate_user": candidate_user,
    }


# ============================================================================
# 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
# ============================================================================
@pytest.mark.django_db
class TestPhase9TypeJuggling:
    @pytest.mark.parametrize(
        "bad_token",
        [
            12345,
            12.34,
            True,
            False,
            ["token_in_list"],
            {"nested": "token"},
            None,
        ],
    )
    def test_accept_invitation_type_juggling_token(self, test_environment, bad_token):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post(
            "/api/v1/members/accept-invitation/",
            {"token": bad_token},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize(
        "bad_token",
        [
            12345,
            12.34,
            True,
            False,
            ["nested_in_list"],
            {"key": "val"},
        ],
    )
    def test_accept_invitation_type_juggling_invitation_token_field(self, test_environment, bad_token):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post(
            "/api/v1/members/accept-invitation/",
            {"invitation_token": bad_token},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize(
        "bad_gym_id",
        [
            "12345",
            "12.34",
            "true",
            "false",
            "null",
            "NaN",
            "[1,2,3]",
            "undefined",
        ],
    )
    def test_resend_invitation_gym_id_type_juggling(self, test_environment, bad_gym_id):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        member_id = test_environment["member"].id
        resp = client.post(f"/api/v1/members/{member_id}/resend-invitation/?gym_id={bad_gym_id}")
        assert resp.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]
        assert resp.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ============================================================================
# 2. BOUNDARY & LENGTH EDGE CASES
# ============================================================================
@pytest.mark.django_db
class TestPhase9BoundariesAndLengths:
    @pytest.mark.parametrize(
        "bad_token",
        [
            "",
            " ",
            "         ",
            "          " * 2,
            "123456789",
        ],
    )
    def test_accept_invitation_below_minimum_or_blank(self, test_environment, bad_token):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post(
            "/api/v1/members/accept-invitation/",
            {"token": bad_token},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "VALIDATION_ERROR"

    def test_accept_invitation_exact_minimum_length_validates_token(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        # Exactly 10 characters non-existent token
        resp = client.post(
            "/api/v1/members/accept-invitation/",
            {"token": "abcdefghij"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid or expired" in resp.data["message"]

    def test_accept_invitation_exact_max_and_over_max_length(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])

        # Exactly 255 chars (max_length) -> passes serializer, fails domain token lookup
        resp_max = client.post(
            "/api/v1/members/accept-invitation/",
            {"token": "a" * 255},
            format="json",
        )
        assert resp_max.status_code == status.HTTP_400_BAD_REQUEST
        assert resp_max.data["code"] == "VALIDATION_ERROR"

        # 256 chars (max + 1) -> rejected by serializer max_length
        resp_over = client.post(
            "/api/v1/members/accept-invitation/",
            {"token": "a" * 256},
            format="json",
        )
        assert resp_over.status_code == status.HTTP_400_BAD_REQUEST
        assert resp_over.data["code"] == "VALIDATION_ERROR"

        # 10,000+ characters extreme length
        resp_extreme = client.post(
            "/api/v1/members/accept-invitation/",
            {"token": "x" * 15000},
            format="json",
        )
        assert resp_extreme.status_code == status.HTTP_400_BAD_REQUEST
        assert resp_extreme.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_resend_invitation_extreme_query_string_length(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        member_id = test_environment["member"].id
        extreme_gym = "a" * 10000
        resp = client.post(f"/api/v1/members/{member_id}/resend-invitation/?gym_id={extreme_gym}")
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# 3. MISSING, EXTRA & MALFORMED FIELDS
# ============================================================================
@pytest.mark.django_db
class TestPhase9MissingExtraAndMalformedFields:
    def test_accept_invitation_completely_empty_json(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post("/api/v1/members/accept-invitation/", {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "VALIDATION_ERROR"

    def test_accept_invitation_missing_token_field(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post("/api/v1/members/accept-invitation/", {"wrong_key": "some_value"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.data["code"] == "VALIDATION_ERROR"

    def test_accept_invitation_hundred_garbage_fields_with_valid_token(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        valid_token = test_environment["member"].invitation_token

        payload = {f"garbage_key_{i}": f"garbage_val_{i}" for i in range(120)}
        payload["token"] = valid_token

        resp = client.post("/api/v1/members/accept-invitation/", payload, format="json")
        assert resp.status_code == status.HTTP_200_OK
        # Member is now successfully linked to candidate user
        test_environment["member"].refresh_from_db()
        assert test_environment["member"].user == test_environment["candidate_user"]
        assert test_environment["member"].joining_status == "joined"

    def test_accept_invitation_mass_assignment_protection(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        valid_token = test_environment["member"].invitation_token

        # Attempt to inject server-controlled fields
        malicious_payload = {
            "token": valid_token,
            "id": str(uuid.uuid4()),
            "is_superuser": True,
            "role": "SuperAdmin",
            "joining_status": "fraudulent",
            "user_id": str(uuid.uuid4()),
        }
        resp = client.post("/api/v1/members/accept-invitation/", malicious_payload, format="json")
        assert resp.status_code == status.HTTP_200_OK

        test_environment["member"].refresh_from_db()
        # Verify malicious fields were NOT mass-assigned
        assert test_environment["member"].joining_status == "joined"
        assert not test_environment["candidate_user"].is_superuser

    def test_accept_invitation_malformed_json_body(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        # Send raw non-JSON malformed syntax
        resp = client.post(
            "/api/v1/members/accept-invitation/",
            data="{'malformed': json, unclosed",
            content_type="application/json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ============================================================================
# 4. FORMAT-SPECIFIC INVALID INPUTS
# ============================================================================
@pytest.mark.django_db
class TestPhase9FormatSpecificInvalidInputs:
    def test_accept_invitation_nonexistent_valid_format_token(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post(
            "/api/v1/members/accept-invitation/",
            {"token": "random_valid_format_token_1234567890"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid or expired" in resp.data["message"]

    def test_resend_invitation_nonexistent_member_uuid(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        random_member_uuid = uuid.uuid4()
        gym_id = test_environment["gym"].id
        resp = client.post(f"/api/v1/members/{random_member_uuid}/resend-invitation/?gym_id={gym_id}")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data["code"] == "RESOURCE_NOT_FOUND"

    def test_resend_invitation_nonexistent_gym_uuid(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        member_id = test_environment["member"].id
        random_gym_uuid = uuid.uuid4()
        resp = client.post(f"/api/v1/members/{member_id}/resend-invitation/?gym_id={random_gym_uuid}")
        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert resp.data["code"] == "RESOURCE_NOT_FOUND"

    def test_resend_invitation_invalid_url_path_uuid(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        gym_id = test_environment["gym"].id
        # Invalid UUID format in URL path
        resp = client.post(f"/api/v1/members/not-a-valid-uuid/resend-invitation/?gym_id={gym_id}")
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# 5. QUERY PARAMETERS, FILTERS & SEARCH
# ============================================================================
@pytest.mark.django_db
class TestPhase9QueryParamsAndFilters:
    def test_resend_invitation_missing_gym_id_param(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        member_id = test_environment["member"].id
        resp = client.post(f"/api/v1/members/{member_id}/resend-invitation/")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "gym_id" in resp.data["message"]

    def test_resend_invitation_blank_gym_id_param(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        member_id = test_environment["member"].id
        resp = client.post(f"/api/v1/members/{member_id}/resend-invitation/?gym_id=")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_resend_invitation_fifty_garbage_query_params(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        member_id = test_environment["member"].id
        gym_id = test_environment["gym"].id

        garbage_qs = "&".join([f"filter_{i}=value_{i}" for i in range(50)])
        url = f"/api/v1/members/{member_id}/resend-invitation/?gym_id={gym_id}&{garbage_qs}"
        resp = client.post(url)
        assert resp.status_code == status.HTTP_200_OK

    def test_accept_invitation_ignores_unexpected_query_params(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        valid_token = test_environment["member"].invitation_token
        url = f"/api/v1/members/accept-invitation/?page=0&page_size=-10&search=' OR 1=1"
        resp = client.post(url, {"token": valid_token}, format="json")
        assert resp.status_code == status.HTTP_200_OK


# ============================================================================
# 6. SECURITY & INJECTION TESTING
# ============================================================================
@pytest.mark.django_db
class TestPhase9SecurityAndInjections:
    @pytest.mark.parametrize(
        "sqli_payload",
        [
            "' OR 1=1 --",
            '" OR ""="',
            "'; DROP TABLE members; --",
            "UNION SELECT NULL, NULL, NULL --",
            "1' AND SLEEP(2) --",
            "admin'--",
            "'; SELECT pg_sleep(1); --",
        ],
    )
    def test_accept_invitation_sql_injection_payloads_blocked(self, test_environment, sqli_payload):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post("/api/v1/members/accept-invitation/", {"token": sqli_payload}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert resp.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize(
        "sqli_payload",
        [
            "' OR 1=1 --",
            "'; DROP TABLE gyms; --",
            "UNION SELECT 1,2,3 --",
        ],
    )
    def test_resend_invitation_sql_injection_in_gym_id_blocked(self, test_environment, sqli_payload):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        member_id = test_environment["member"].id
        resp = client.post(f"/api/v1/members/{member_id}/resend-invitation/?gym_id={sqli_payload}")
        assert resp.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]
        assert resp.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize(
        "xss_payload",
        [
            "<script>alert('xss')</script>",
            "<img src=x onerror=alert(document.cookie)>",
            "javascript:alert('pwned')",
            "<svg/onload=alert('xss')>",
        ],
    )
    def test_accept_invitation_xss_payloads_handled_safely(self, test_environment, xss_payload):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post("/api/v1/members/accept-invitation/", {"token": xss_payload}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize(
        "path_payload",
        [
            "../../etc/passwd",
            "..%2F..%2Fetc%2Fpasswd",
            "/etc/shadow",
            r"..\..\windows\system32",
        ],
    )
    def test_path_traversal_payloads_blocked(self, test_environment, path_payload):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post("/api/v1/members/accept-invitation/", {"token": path_payload}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize(
        "unicode_str",
        [
            "🏋️‍♂️💪🔥📊",
            "رمز_دعوة_غير_صالح_اختبار",
            "טוקן_הזמנה_שגוי_בדיקה",
            "邀请令牌无效测试数据",
            "Z̸a̴l̸g̵o̶ T̷e̸x̷t̵",
        ],
    )
    def test_unicode_and_adversarial_encoding_handled(self, test_environment, unicode_str):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post("/api/v1/members/accept-invitation/", {"token": unicode_str}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ============================================================================
# 7. AUTHENTICATION, AUTHORIZATION & PERMISSIONS
# ============================================================================
@pytest.mark.django_db
class TestPhase9AuthAndPermissions:
    def test_unauthenticated_requests_rejected_with_401(self, test_environment):
        client = APIClient()
        # Accept invitation without token
        resp1 = client.post("/api/v1/members/accept-invitation/", {"token": "some_token_123"}, format="json")
        assert resp1.status_code == status.HTTP_401_UNAUTHORIZED

        # Resend invitation without token
        member_id = test_environment["member"].id
        gym_id = test_environment["gym"].id
        resp2 = client.post(f"/api/v1/members/{member_id}/resend-invitation/?gym_id={gym_id}")
        assert resp2.status_code == status.HTTP_401_UNAUTHORIZED

    def test_malformed_authorization_header_rejected_with_401(self, test_environment):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer malformed.jwt.token")
        resp = client.post("/api/v1/members/accept-invitation/", {"token": "some_token_123"}, format="json")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_staff_lacking_members_edit_scope_rejected_with_403(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["staff_no_perm_user"])
        member_id = test_environment["member"].id
        gym_id = test_environment["gym"].id
        resp = client.post(f"/api/v1/members/{member_id}/resend-invitation/?gym_id={gym_id}")
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert resp.data["code"] == "PERMISSION_DENIED"

    def test_authorized_staff_with_members_edit_succeeds_with_200(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["staff_user"])
        member_id = test_environment["member"].id
        gym_id = test_environment["gym"].id
        resp = client.post(f"/api/v1/members/{member_id}/resend-invitation/?gym_id={gym_id}")
        assert resp.status_code == status.HTTP_200_OK

    def test_gym_owner_succeeds_with_200(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        member_id = test_environment["member"].id
        gym_id = test_environment["gym"].id
        resp = client.post(f"/api/v1/members/{member_id}/resend-invitation/?gym_id={gym_id}")
        assert resp.status_code == status.HTTP_200_OK

    def test_inactive_user_account_rejected_with_401_or_403(self, test_environment):
        inactive_user = User.objects.create_user(
            email=f"inactive_{uuid.uuid4().hex[:6]}@test.com",
            password="password123",
            is_active=False,
        )
        client = APIClient()
        client.force_authenticate(user=inactive_user)
        resp = client.post("/api/v1/members/accept-invitation/", {"token": "some_token_123"}, format="json")
        assert resp.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN]


# ============================================================================
# 8. IDOR & OBJECT-LEVEL AUTHORIZATION
# ============================================================================
@pytest.mark.django_db
class TestPhase9IDORAndObjectAuthorization:
    def test_cross_tenant_idor_resend_invitation_with_other_gym_id(self, test_environment):
        """
        Owner of Gym B attempts to resend invitation for Member of Gym A by passing Gym A's ID.
        Must be rejected with 403 Forbidden.
        """
        client = APIClient()
        client.force_authenticate(user=test_environment["other_owner"])
        member_id = test_environment["member"].id
        gym_a_id = test_environment["gym"].id

        resp = client.post(f"/api/v1/members/{member_id}/resend-invitation/?gym_id={gym_a_id}")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_idor_resend_invitation_with_own_gym_id(self, test_environment):
        """
        Owner of Gym B attempts to resend invitation for Member of Gym A by passing Gym B's ID.
        Must be rejected with 404 (Member not found in Gym B).
        """
        client = APIClient()
        client.force_authenticate(user=test_environment["other_owner"])
        member_of_gym_a_id = test_environment["member"].id
        gym_b_id = test_environment["other_gym"].id

        resp = client.post(f"/api/v1/members/{member_of_gym_a_id}/resend-invitation/?gym_id={gym_b_id}")
        assert resp.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# 9. BUSINESS LOGIC & INVALID STATE TRANSITIONS
# ============================================================================
@pytest.mark.django_db
class TestPhase9BusinessLogicAndStateTransitions:
    def test_resend_invitation_for_already_joined_member_fails(self, test_environment):
        member = test_environment["member"]
        member.joining_status = "joined"
        member.user = test_environment["candidate_user"]
        member.save()

        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        gym_id = test_environment["gym"].id
        resp = client.post(f"/api/v1/members/{member.id}/resend-invitation/?gym_id={gym_id}")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "already completed onboarding" in resp.data["message"]

    def test_accept_invitation_twice_fails_on_second_attempt(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        valid_token = test_environment["member"].invitation_token

        # First attempt: succeeds
        resp1 = client.post("/api/v1/members/accept-invitation/", {"token": valid_token}, format="json")
        assert resp1.status_code == status.HTTP_200_OK

        # Second attempt with same token: rejected
        resp2 = client.post("/api/v1/members/accept-invitation/", {"token": valid_token}, format="json")
        assert resp2.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid or expired" in resp2.data["message"]

    def test_accept_invitation_when_member_is_marked_joined_fails(self, test_environment):
        member = test_environment["member"]
        # Manually retain token but set joining_status to joined
        member.joining_status = "joined"
        member.save()

        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post("/api/v1/members/accept-invitation/", {"token": member.invitation_token}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "already been accepted" in resp.data["message"]

    def test_background_workers_with_corrupted_data_do_not_crash(self, test_environment):
        today = timezone.localdate()
        gym = test_environment["gym"]
        plan = MembershipPlan.objects.create(
            gym=gym,
            name="Corrupt Test Plan",
            price=Decimal("100.00"),
            plan_type="fixed_period",
            duration_value=30,
            duration_unit="days",
        )

        # 1. Member with empty email
        corrupt_member = Member.objects.create(
            gym=gym,
            first_name="NoEmail",
            last_name="Member",
            email="",
        )
        MemberSubscription.objects.create(
            member=corrupt_member,
            plan=plan,
            membership_status="active",
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=7),
        )

        # 2. Lead Next Move with no assigned staff and gym owner has no email
        orphan_owner = User.objects.create_user(
            email=f"temp_owner_{uuid.uuid4().hex[:6]}@test.com",
            password="password123",
        )
        orphan_gym = Gym.objects.create(owner_user=orphan_owner, name="Orphan Gym")
        orphan_owner.email = ""
        orphan_owner.save()

        orphan_lead = Lead.objects.create(
            gym=orphan_gym,
            first_name="OrphanLead",
            last_name="Test",
            phone="1234567890",
            stage="new",
        )
        LeadNextMove.objects.create(
            lead=orphan_lead,
            scheduled_date=today,
            short_description="Test corrupt move",
            is_completed=False,
        )

        # Execute workers: MUST NOT CRASH
        reminders_sent = send_subscription_expiry_reminders()
        lead_reminders_sent = send_lead_followup_reminders()
        reconcile_count = reconcile_expired_subscriptions()
        deleted_tokens = cleanup_expired_tokens()

        assert isinstance(reminders_sent, int)
        assert isinstance(lead_reminders_sent, int)
        assert isinstance(reconcile_count, int)
        assert isinstance(deleted_tokens, int)


# ============================================================================
# 10. HTTP METHODS VALIDATION
# ============================================================================
@pytest.mark.django_db
class TestPhase9HTTPMethodsValidation:
    @pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
    def test_resend_invitation_unsupported_http_methods(self, test_environment, method):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        member_id = test_environment["member"].id
        gym_id = test_environment["gym"].id
        url = f"/api/v1/members/{member_id}/resend-invitation/?gym_id={gym_id}"

        caller = getattr(client, method)
        resp = caller(url)
        assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert resp.data["code"] == "METHOD_NOT_ALLOWED"

    @pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
    def test_accept_invitation_unsupported_http_methods(self, test_environment, method):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        url = "/api/v1/members/accept-invitation/"

        caller = getattr(client, method)
        resp = caller(url)
        assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert resp.data["code"] == "METHOD_NOT_ALLOWED"


# ============================================================================
# 11. RESPONSE CONTRACT & ENVELOPE VALIDATION
# ============================================================================
@pytest.mark.django_db
class TestPhase9ResponseContracts:
    def test_resend_invitation_success_envelope(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["owner"])
        member_id = test_environment["member"].id
        gym_id = test_environment["gym"].id
        resp = client.post(f"/api/v1/members/{member_id}/resend-invitation/?gym_id={gym_id}")
        assert resp.status_code == status.HTTP_200_OK
        assert "message" in resp.data
        assert "sent successfully" in resp.data["message"]

    def test_accept_invitation_success_envelope(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        valid_token = test_environment["member"].invitation_token
        resp = client.post("/api/v1/members/accept-invitation/", {"token": valid_token}, format="json")
        assert resp.status_code == status.HTTP_200_OK

        data = resp.data
        assert "id" in data
        assert "first_name" in data
        assert "last_name" in data
        assert "email" in data
        assert "joining_status" in data
        assert data["joining_status"] == "joined"
        assert "subscriptions" in data
        assert isinstance(data["subscriptions"], list)

    def test_error_envelope_consistency(self, test_environment):
        client = APIClient()
        client.force_authenticate(user=test_environment["candidate_user"])
        resp = client.post("/api/v1/members/accept-invitation/", {"token": ""}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST
        assert "code" in resp.data
        assert "message" in resp.data
        assert "details" in resp.data
