import uuid
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User
from apps.gyms.models import Gym, GymAdminLog
from apps.gyms.services import create_gym, log_admin_action
from apps.access_control.services import seed_default_permissions_and_roles, invite_staff_member
from apps.access_control.models import Role
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    AdminLogCategory,
    AdminLogActionType,
)


@pytest.fixture
def owner_user(db):
    return User.objects.create_user(
        email="gym.owner.sarah@example.com",
        password="SecurePassword123!",
        first_name="Sarah",
        last_name="Ahmed",
        is_verified=True,
    )


@pytest.fixture
def second_owner_user(db):
    return User.objects.create_user(
        email="other.owner.karim@example.com",
        password="SecurePassword123!",
        first_name="Karim",
        last_name="Hasan",
        is_verified=True,
    )


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        email="staff.rafi@example.com",
        password="SecurePassword123!",
        first_name="Rafi",
        last_name="Islam",
        is_verified=True,
    )


@pytest.fixture
def unauthorized_user(db):
    return User.objects.create_user(
        email="unauth.eve@example.com",
        password="SecurePassword123!",
        first_name="Eve",
        last_name="Attacker",
        is_verified=True,
    )


@pytest.fixture
def test_gym(owner_user):
    return create_gym(owner_user=owner_user, name="Apex Performance Gym")


@pytest.fixture
def other_gym(second_owner_user):
    return create_gym(owner_user=second_owner_user, name="Rival Fitness Gym")


@pytest.fixture
def auth_client(owner_user):
    tokens = issue_context_token(owner_user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def other_auth_client(second_owner_user):
    tokens = issue_context_token(second_owner_user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def unauth_client():
    return APIClient()


@pytest.mark.django_db
class TestGymAdminLogsExhaustiveEdgeCases:
    """
    Exhaustive edge-case, security, negative, boundary, and regression tests
    for Gym Admin Logs endpoints.
    """

    # =========================================================================
    # 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
    # =========================================================================

    def test_type_juggling_action_as_integer(self, auth_client, test_gym):
        """Action field passed as integer should be rejected or gracefully validated."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        payload = {"action": 12345, "details": "Some details"}
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", payload, format="json")
        assert resp.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_201_CREATED]
        if resp.status_code == status.HTTP_201_CREATED:
            assert resp.json()["action"] == "12345"

    def test_type_juggling_action_as_list(self, auth_client, test_gym):
        """Action field passed as array/list must return 400 Bad Request."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        payload = {"action": ["Updated info", "second item"], "details": "test"}
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_type_juggling_action_as_dict(self, auth_client, test_gym):
        """Action field passed as dict/object must return 400 Bad Request."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        payload = {"action": {"title": "nested"}, "details": "test"}
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_type_juggling_action_as_null(self, auth_client, test_gym):
        """Action field passed as null must return 400 Bad Request."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        payload = {"action": None}
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_type_juggling_metadata_as_string(self, auth_client, test_gym):
        """Metadata field passed as string where dict is expected must return 400."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        payload = {"action": "Valid Action", "metadata": "not-a-dict"}
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_type_juggling_metadata_as_list(self, auth_client, test_gym):
        """Metadata field passed as list where dict is expected must return 400."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        payload = {"action": "Valid Action", "metadata": [1, 2, 3]}
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    # =========================================================================
    # 2. BOUNDARY & LENGTH EDGE CASES
    # =========================================================================

    def test_action_empty_string(self, auth_client, test_gym):
        """Empty action string must be rejected with 400."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": ""}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_action_whitespace_only(self, auth_client, test_gym):
        """Whitespace-only action string must be rejected with 400."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "     \t\n  "}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_action_exact_boundary_255_chars(self, auth_client, test_gym):
        """Action string with exactly 255 chars is valid and succeeds."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        exact_255 = "A" * 255
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": exact_255}, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["action"] == exact_255

    def test_action_boundary_exceeded_256_chars(self, auth_client, test_gym):
        """Action string exceeding 255 chars must return 400."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        exceeded_256 = "A" * 256
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": exceeded_256}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_action_extremely_long_string_10000_chars(self, auth_client, test_gym):
        """10,000+ character action must be safely rejected with 400."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        huge_str = "X" * 10000
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": huge_str}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_details_extremely_long_text(self, auth_client, test_gym):
        """TextField details safely accepts very long descriptive text."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        huge_details = "D" * 5000
        resp = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"action": "Large Details Action", "details": huge_details},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["details"] == huge_details

    # =========================================================================
    # 3. MISSING, EXTRA & MALFORMED FIELDS
    # =========================================================================

    def test_empty_json_body(self, auth_client, test_gym):
        """Completely empty JSON body {} returns 400."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_100_unexpected_garbage_fields(self, auth_client, test_gym):
        """Request containing 100+ unexpected fields should safely succeed without mass-assignment."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        payload = {"action": "Valid Action"}
        for i in range(100):
            payload[f"garbage_field_{i}"] = f"random_value_{i}"
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["action"] == "Valid Action"

    def test_read_only_and_server_controlled_fields_ignored(self, auth_client, test_gym, second_owner_user):
        """Attempting to inject server-controlled fields like id, created_at, or actor is ignored."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        fake_uuid = str(uuid.uuid4())
        payload = {
            "id": fake_uuid,
            "action": "Spoof Attempt",
            "actor": str(second_owner_user.id),
            "created_at": "2020-01-01T00:00:00Z",
            "date_and_time": "2020-01-01T00:00:00Z",
        }
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["id"] != fake_uuid  # Server generates real UUID
        assert data["admin"]["full_name"] == "Sarah Ahmed"  # Server assigns authenticated user

    # =========================================================================
    # 4. FORMAT-SPECIFIC INVALID INPUTS (DATES, UUIDs, EXPORT FORMATS)
    # =========================================================================

    def test_invalid_date_month_13_returns_400_not_500(self, auth_client, test_gym):
        """Invalid month '2026-13-45' in start_date must return 400 Bad Request, never 500."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}&start_date=2026-13-45")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_leap_year_feb_30_returns_400_not_500(self, auth_client, test_gym):
        """Invalid day '2026-02-30' must return 400 Bad Request, never 500."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}&end_date=2026-02-30")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_date_format_text_returns_400(self, auth_client, test_gym):
        """Non-date text 'yesterday' returns 400 Bad Request."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}&start_date=yesterday")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_actor_id_uuid_returns_400(self, auth_client, test_gym):
        """Invalid UUID format in actor_id query param returns 400 Bad Request."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}&actor_id=not-a-valid-uuid")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_export_format_returns_400(self, auth_client, test_gym):
        """Unsupported format like format=yaml returns 400 Bad Request."""
        url = reverse("gyms_v1:gym-admin-logs-export")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}&format=yaml")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_log_id_in_detail_returns_404(self, auth_client, test_gym):
        """Non-existent UUID in detail URL returns 404 Not Found."""
        random_uuid = uuid.uuid4()
        url = reverse("gyms_v1:gym-admin-log-detail", kwargs={"log_id": random_uuid})
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    # =========================================================================
    # 5. QUERY PARAMETERS, FILTERS, SEARCH & PAGINATION
    # =========================================================================

    def test_pagination_page_zero_or_negative_clamped_safely(self, auth_client, test_gym):
        """page=0 and page=-5 are safely defaulted without crashing."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}&page=0")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["page"] == 1

        resp_neg = auth_client.get(f"{url}?gym_id={test_gym.id}&page=-5")
        assert resp_neg.status_code == status.HTTP_200_OK
        assert resp_neg.json()["page"] == 1

    def test_pagination_page_size_clamped_to_100(self, auth_client, test_gym):
        """page_size exceeding 100 is clamped to 100."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}&page_size=5000")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["page_size"] == 100

    def test_pagination_huge_page_does_not_overflow_bigint(self, auth_client, test_gym):
        """Extremely large page number does not cause bigint overflow 500 error."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        huge_page = "9999999999999999999999999999"
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}&page={huge_page}")
        assert resp.status_code == status.HTTP_200_OK

    def test_unknown_category_and_action_type_returns_empty_results(self, auth_client, test_gym):
        """Non-existent category returns empty results without exception."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}&category=nonexistent_cat_123")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["count"] == 0

    def test_search_with_special_characters_and_whitespace(self, auth_client, test_gym):
        """Search query with punctuation and whitespace executes safely."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}&search=!@#$%^&*()_+-=[]")
        assert resp.status_code == status.HTTP_200_OK

    # =========================================================================
    # 6. SECURITY & INJECTION TESTING (SQLi, XSS, NUL BYTES, UNICODE)
    # =========================================================================

    def test_sqli_injection_in_search(self, auth_client, test_gym):
        """SQL injection attempt in search query is safely parameterized."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        sqli_payloads = [
            "' OR 1=1 --",
            '" OR ""="',
            "'; DROP TABLE gyms; --",
            "admin'--",
            "1 UNION SELECT null, null, null--",
        ]
        for payload in sqli_payloads:
            resp = auth_client.get(f"{url}?gym_id={test_gym.id}&search={payload}")
            assert resp.status_code == status.HTTP_200_OK

    def test_nul_byte_in_search_does_not_crash_postgres(self, auth_client, test_gym):
        """Postgres null byte in search query is safely stripped and does not cause DataError 500."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}&search=test%00evil")
        assert resp.status_code == status.HTTP_200_OK

    def test_nul_byte_in_post_payload_rejected(self, auth_client, test_gym):
        """Null byte in POST body action or details is caught and rejected with 400."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"action": "Bad\x00Action", "details": "details"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_xss_payload_in_action_and_details_safely_stored(self, auth_client, test_gym):
        """XSS strings are stored harmlessly without execution or corruption."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        xss_action = "<script>alert(1)</script>"
        xss_details = "<img src=x onerror=alert('XSS')>"
        resp = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"action": xss_action, "details": xss_details},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["action"] == xss_action
        assert data["details"] == xss_details

    def test_unicode_and_emojis(self, auth_client, test_gym):
        """Unicode, Bengali text, and emojis are properly supported."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        action = "🏋️‍♂️ জিম অডিট লগ অ্যাকশন 🚀"
        details = "تفاصيل العملية الادارية بنجاح"
        resp = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"action": action, "details": details},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.json()["action"] == action
        assert resp.json()["details"] == details

    # =========================================================================
    # 7. AUTHENTICATION & AUTHORIZATION
    # =========================================================================

    def test_missing_authentication_returns_401(self, unauth_client, test_gym):
        """Unauthenticated client returns 401 Unauthorized across all endpoints."""
        list_url = reverse("gyms_v1:gym-admin-logs-list")
        assert unauth_client.get(f"{list_url}?gym_id={test_gym.id}").status_code == status.HTTP_401_UNAUTHORIZED
        assert unauth_client.post(f"{list_url}?gym_id={test_gym.id}", {"action": "x"}).status_code == status.HTTP_401_UNAUTHORIZED

        metrics_url = reverse("gyms_v1:gym-admin-logs-metrics")
        assert unauth_client.get(f"{metrics_url}?gym_id={test_gym.id}").status_code == status.HTTP_401_UNAUTHORIZED

        export_url = reverse("gyms_v1:gym-admin-logs-export")
        assert unauth_client.get(f"{export_url}?gym_id={test_gym.id}").status_code == status.HTTP_401_UNAUTHORIZED

    def test_unauthorized_user_forbidden_across_endpoints(self, unauthorized_user, test_gym):
        """User without gym relationship returns 403 Forbidden."""
        tokens = issue_context_token(unauthorized_user, context_type=TokenContextType.PERSONAL)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        list_url = reverse("gyms_v1:gym-admin-logs-list")
        assert client.get(f"{list_url}?gym_id={test_gym.id}").status_code == status.HTTP_403_FORBIDDEN
        assert client.post(f"{list_url}?gym_id={test_gym.id}", {"action": "x"}).status_code == status.HTTP_403_FORBIDDEN

        metrics_url = reverse("gyms_v1:gym-admin-logs-metrics")
        assert client.get(f"{metrics_url}?gym_id={test_gym.id}").status_code == status.HTTP_403_FORBIDDEN

        export_url = reverse("gyms_v1:gym-admin-logs-export")
        assert client.get(f"{export_url}?gym_id={test_gym.id}").status_code == status.HTTP_403_FORBIDDEN

    # =========================================================================
    # 8. IDOR & OBJECT-LEVEL AUTHORIZATION (TENANT ISOLATION)
    # =========================================================================

    def test_cross_tenant_idor_log_detail_rejected(self, auth_client, other_auth_client, test_gym, other_gym, owner_user, second_owner_user):
        """Owner of Gym A cannot view Gym B's admin log detail."""
        log_b = log_admin_action(
            gym=other_gym,
            actor=second_owner_user,
            action="Gym B Secret Action",
            category=AdminLogCategory.SETTINGS,
        )

        detail_url = reverse("gyms_v1:gym-admin-log-detail", kwargs={"log_id": log_b.id})

        # Gym A owner attempts to fetch Gym B's log using Gym A's context: 404 (scoped to Gym A)
        resp_scoped = auth_client.get(f"{detail_url}?gym_id={test_gym.id}")
        assert resp_scoped.status_code == status.HTTP_404_NOT_FOUND

        # Gym A owner attempts to access Gym B directly using Gym B's ID: 403 (forbidden for other gym)
        resp_direct = auth_client.get(f"{detail_url}?gym_id={other_gym.id}")
        assert resp_direct.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_idor_export_rejected(self, auth_client, other_gym):
        """Owner of Gym A cannot export Gym B's logs."""
        export_url = reverse("gyms_v1:gym-admin-logs-export")
        resp = auth_client.get(f"{export_url}?gym_id={other_gym.id}")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_gym_id_returns_400(self, auth_client):
        """Missing gym_id parameter returns 400 Bad Request."""
        list_url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(list_url)
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_malformed_gym_id_returns_404(self, auth_client):
        """Malformed gym_id returns 404 Not Found."""
        list_url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(f"{list_url}?gym_id=not-a-valid-uuid")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    # =========================================================================
    # 9. HTTP METHOD VALIDATION
    # =========================================================================

    def test_http_methods_not_allowed(self, auth_client, test_gym, owner_user):
        """Endpoints reject unsupported HTTP methods with 405 Method Not Allowed."""
        log_entry = log_admin_action(
            gym=test_gym,
            actor=owner_user,
            action="Action For Method Test",
            category=AdminLogCategory.GENERAL,
        )

        detail_url = reverse("gyms_v1:gym-admin-log-detail", kwargs={"log_id": log_entry.id})
        # Log detail is read-only (no PUT, PATCH, DELETE)
        assert auth_client.put(f"{detail_url}?gym_id={test_gym.id}", {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert auth_client.patch(f"{detail_url}?gym_id={test_gym.id}", {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert auth_client.delete(f"{detail_url}?gym_id={test_gym.id}").status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        metrics_url = reverse("gyms_v1:gym-admin-logs-metrics")
        # Metrics is GET only
        assert auth_client.post(f"{metrics_url}?gym_id={test_gym.id}", {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert auth_client.delete(f"{metrics_url}?gym_id={test_gym.id}").status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        actions_url = reverse("gyms_v1:gym-admin-logs-actions")
        # Actions is GET only
        assert auth_client.post(actions_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        export_url = reverse("gyms_v1:gym-admin-logs-export")
        # Export is GET only
        assert auth_client.post(f"{export_url}?gym_id={test_gym.id}", {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # =========================================================================
    # 10. RECIPIENT & ACTOR LIFECYCLE (DELETED USERS)
    # =========================================================================

    def test_admin_logs_survive_actor_deletion(self, test_gym):
        """If an actor user is deleted, their log entry remains intact with name/email snapshot."""
        temp_user = User.objects.create_user(
            email="temporary.staff@example.com",
            password="SecurePassword123!",
            first_name="Temp",
            last_name="Staff",
        )
        log_entry = log_admin_action(
            gym=test_gym,
            actor=temp_user,
            action="Temporary Staff Action",
            details="Executed before account termination",
            category=AdminLogCategory.GENERAL,
        )

        assert log_entry.actor_id == temp_user.id
        assert log_entry.actor_name == "Temp Staff"
        assert log_entry.actor_email == "temporary.staff@example.com"

        # Delete the user
        temp_user.delete()

        # Reload log entry
        log_entry.refresh_from_db()
        assert log_entry.actor is None  # ForeignKey set to NULL
        assert log_entry.actor_name == "Temp Staff"  # Name is preserved!
        assert log_entry.actor_email == "temporary.staff@example.com"  # Email is preserved!

        # Check API serializer handles deleted actor gracefully
        tokens = issue_context_token(test_gym.owner_user, context_type=TokenContextType.PERSONAL)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        detail_url = reverse("gyms_v1:gym-admin-log-detail", kwargs={"log_id": log_entry.id})
        resp = client.get(f"{detail_url}?gym_id={test_gym.id}")
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["admin"]["id"] is None
        assert data["admin"]["full_name"] == "Temp Staff"
        assert data["admin"]["email"] == "temporary.staff@example.com"

