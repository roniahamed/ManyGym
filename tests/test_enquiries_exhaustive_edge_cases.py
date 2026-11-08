import uuid
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym
from apps.gyms.services import create_gym
from apps.enquiries.models import Enquiry
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, EnquiryTypeEnum, EnquiryStatusEnum


@pytest.fixture
def auth_user(db):
    user = User.objects.create_user(
        email="qa_tester@manygym.com",
        password="SecurePassword123!",
        first_name="QA",
        last_name="Tester",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def registered_user(db):
    user = User.objects.create_user(
        email="customer@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Customer",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def auth_client(auth_user):
    token = issue_context_token(user=auth_user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def gym_instance(auth_user):
    return create_gym(
        owner_user=auth_user,
        name="Metropolis Fitness",
        short_description="Metropolis premier bodybuilding and wellness facility with high-end machinery." * 2,
    )


@pytest.fixture
def sample_enquiry(auth_user, gym_instance):
    return Enquiry.objects.create(
        gym=gym_instance,
        first_name="Bruce",
        last_name="Wayne",
        email="bruce@wayne.com",
        phone="+1234567890",
        type=EnquiryTypeEnum.GENERAL_INQUIRY,
        status=EnquiryStatusEnum.NEW,
        summary="Inquiry about private gym hours",
        notes=["Initial note from client"],
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
# ══════════════════════════════════════════════════════════════════════════════

class TestDataTypeMismatches:
    """Verifies that non-string, unexpected objects, and invalid types return 400 and never 500."""

    @pytest.mark.parametrize("invalid_val", [
        12345,
        3.14159,
        True,
        False,
        ["Sarah"],
        {"name": "Sarah"},
    ])
    def test_first_name_type_mismatches_create(self, auth_client, invalid_val):
        payload = {
            "first_name": invalid_val,
            "last_name": "Connor",
            "email": "sarah@example.com",
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_val", [
        12345,
        True,
        ["Connor"],
        {"last": "Connor"},
    ])
    def test_last_name_type_mismatches_create(self, auth_client, invalid_val):
        payload = {
            "first_name": "Sarah",
            "last_name": invalid_val,
            "email": "sarah@example.com",
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_val", [
        12345,
        True,
        ["sarah@example.com"],
        {"email": "sarah@example.com"},
    ])
    def test_email_type_mismatches_create(self, auth_client, invalid_val):
        payload = {
            "first_name": "Sarah",
            "last_name": "Connor",
            "email": invalid_val,
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_val", [
        12345,
        True,
        ["+1234567890"],
        {"phone": "123"},
    ])
    def test_phone_type_mismatches_create(self, auth_client, invalid_val):
        payload = {
            "first_name": "Sarah",
            "last_name": "Connor",
            "phone": invalid_val,
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_val", [
        12345,
        True,
        "not-a-uuid",
        ["uuid"],
        {"id": 123},
    ])
    def test_manygym_user_id_type_mismatches(self, auth_client, invalid_val):
        payload = {
            "first_name": "Sarah",
            "last_name": "Connor",
            "email": "sarah@example.com",
            "manygym_user_id": invalid_val,
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_val", [
        12345,
        True,
        "not-a-uuid",
        ["uuid"],
        {"id": 123},
    ])
    def test_gym_id_type_mismatches(self, auth_client, invalid_val):
        payload = {
            "first_name": "Sarah",
            "last_name": "Connor",
            "email": "sarah@example.com",
            "gym_id": invalid_val,
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_val", [
        "not-a-list",
        12345,
        True,
        {"note": "text"},
        [123],
        [True],
        [{"text": "note"}],
    ])
    def test_notes_type_mismatches_create(self, auth_client, invalid_val):
        payload = {
            "first_name": "Sarah",
            "last_name": "Connor",
            "email": "sarah@example.com",
            "notes": invalid_val,
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_val", [
        12345,
        True,
        ["GENERAL_INQUIRY"],
        {"type": "GENERAL_INQUIRY"},
    ])
    def test_type_and_status_type_mismatches(self, auth_client, invalid_val):
        res1 = auth_client.post("/api/v1/enquiries/", data={"first_name": "A", "last_name": "B", "email": "a@b.com", "type": invalid_val}, format="json")
        assert res1.status_code == status.HTTP_400_BAD_REQUEST

        res2 = auth_client.post("/api/v1/enquiries/", data={"first_name": "A", "last_name": "B", "email": "a@b.com", "status": invalid_val}, format="json")
        assert res2.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_val", [
        12345,
        True,
        ["Summary"],
        {"summary": "text"},
    ])
    def test_summary_type_mismatches(self, auth_client, invalid_val):
        payload = {
            "first_name": "Sarah",
            "last_name": "Connor",
            "email": "sarah@example.com",
            "summary": invalid_val,
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_val", [
        12345,
        True,
        ["note"],
        {"note": "text"},
    ])
    def test_add_note_endpoint_type_mismatches(self, auth_client, sample_enquiry, invalid_val):
        res = auth_client.post(
            f"/api/v1/enquiries/{sample_enquiry.id}/notes/",
            data={"note_text": invalid_val},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST


# ══════════════════════════════════════════════════════════════════════════════
# 2. BOUNDARY & LENGTH EDGE CASES
# ══════════════════════════════════════════════════════════════════════════════

class TestBoundaryAndLengthEdgeCases:
    """Tests empty, whitespace, and extreme string boundary constraints."""

    @pytest.mark.parametrize("bad_str", ["", " ", "   ", "\t", "\n", "\r\n"])
    def test_empty_or_whitespace_names_rejected(self, auth_client, bad_str):
        # Empty first_name
        res1 = auth_client.post("/api/v1/enquiries/", data={"first_name": bad_str, "last_name": "Valid", "email": "v@v.com"}, format="json")
        assert res1.status_code == status.HTTP_400_BAD_REQUEST

        # Empty last_name
        res2 = auth_client.post("/api/v1/enquiries/", data={"first_name": "Valid", "last_name": bad_str, "email": "v@v.com"}, format="json")
        assert res2.status_code == status.HTTP_400_BAD_REQUEST

    def test_exact_100_char_boundary_names(self, auth_client, gym_instance):
        # 100 chars -> OK
        name_100 = "A" * 100
        res = auth_client.post("/api/v1/enquiries/", data={"gym_id": str(gym_instance.id), "first_name": name_100, "last_name": name_100, "email": "boundary@test.com"}, format="json")
        assert res.status_code == status.HTTP_201_CREATED

        # 101 chars -> Fails (max_length=100)
        name_101 = "A" * 101
        res_fail = auth_client.post("/api/v1/enquiries/", data={"gym_id": str(gym_instance.id), "first_name": name_101, "last_name": "Valid", "email": "boundary2@test.com"}, format="json")
        assert res_fail.status_code == status.HTTP_400_BAD_REQUEST

    def test_extremely_long_strings_handling(self, auth_client, gym_instance):
        huge_text = "Gym enquiry details: " + ("lorem ipsum " * 1000)  # > 10,000 chars
        payload = {
            "gym_id": str(gym_instance.id),
            "first_name": "Long",
            "last_name": "Summary",
            "email": "long@summary.com",
            "summary": huge_text,
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        # TextField should accept without crashing or 500
        assert res.status_code == status.HTTP_201_CREATED
        assert len(res.json()["summary"]) > 5000

    def test_notes_with_whitespace_item_rejected(self, auth_client, gym_instance):
        payload = {
            "gym_id": str(gym_instance.id),
            "first_name": "Test",
            "last_name": "Notes",
            "email": "test@notes.com",
            "notes": ["Valid note", "   ", "Another valid note"],
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST


# ══════════════════════════════════════════════════════════════════════════════
# 3. MISSING, EXTRA & MALFORMED FIELDS
# ══════════════════════════════════════════════════════════════════════════════

class TestMissingAndMalformedFields:
    """Tests completely empty bodies, missing combinations, and mass assignment protections."""

    def test_empty_json_body_returns_400(self, auth_client):
        res = auth_client.post("/api/v1/enquiries/", data={}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_gym_id_returns_400(self, auth_client):
        res = auth_client.post(
            "/api/v1/enquiries/",
            data={"first_name": "No", "last_name": "Gym", "email": "nogym@example.com"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "gym_id" in str(res.json()).lower()

    def test_missing_contact_info_returns_400(self, auth_client, gym_instance):
        # Neither email nor phone
        res = auth_client.post(
            "/api/v1/enquiries/",
            data={"gym_id": str(gym_instance.id), "first_name": "No", "last_name": "Contact"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Either Email or Phone" in str(res.json())

    def test_100_garbage_fields_ignored_safely(self, auth_client, gym_instance):
        payload = {
            "gym_id": str(gym_instance.id),
            "first_name": "Clean",
            "last_name": "Fields",
            "email": "clean@fields.com",
        }
        # Inject 100 garbage fields
        for i in range(100):
            payload[f"garbage_key_{i}"] = f"garbage_value_{i}"

        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["first_name"] == "Clean"
        assert "garbage_key_0" not in data

    def test_client_cannot_override_read_only_id_and_timestamps(self, auth_client, sample_enquiry):
        fake_uuid = str(uuid.uuid4())
        fake_created_at = "1999-01-01T00:00:00Z"

        res = auth_client.patch(
            f"/api/v1/enquiries/{sample_enquiry.id}/",
            data={
                "id": fake_uuid,
                "created_at": fake_created_at,
                "summary": "Updated summary",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        # id and created_at must remain untouched
        assert data["id"] == str(sample_enquiry.id)
        assert data["id"] != fake_uuid
        assert data["created_at"] != fake_created_at


# ══════════════════════════════════════════════════════════════════════════════
# 4. FORMAT-SPECIFIC INVALID INPUTS
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatSpecificInvalidInputs:
    """Tests invalid emails, malformed UUIDs, and unknown foreign keys."""

    @pytest.mark.parametrize("invalid_email", [
        "notanemail",
        "missingatsign.com",
        "@missinguser.com",
        "user@missingtld.",
        "user @spaced.com",
        "user@@multipleat.com",
    ])
    def test_malformed_email_rejected(self, auth_client, invalid_email):
        payload = {
            "first_name": "Format",
            "last_name": "Test",
            "email": invalid_email,
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_nonexistent_manygym_user_id_rejected(self, auth_client, gym_instance):
        payload = {
            "gym_id": str(gym_instance.id),
            "first_name": "Ghost",
            "last_name": "User",
            "email": "ghost@user.com",
            "manygym_user_id": str(uuid.uuid4()),  # does not exist in DB
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "manygym_user" in str(res.json()).lower()

    def test_nonexistent_gym_id_rejected(self, auth_client):
        payload = {
            "first_name": "Ghost",
            "last_name": "Gym",
            "email": "ghost@gym.com",
            "gym_id": str(uuid.uuid4()),  # does not exist in DB
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "gym" in str(res.json()).lower()

    def test_invalid_uuid_path_parameter_returns_404(self, auth_client):
        # Non-UUID string in path parameter
        res1 = auth_client.get("/api/v1/enquiries/not-a-valid-uuid/")
        assert res1.status_code == status.HTTP_404_NOT_FOUND

        res2 = auth_client.patch("/api/v1/enquiries/12345/", data={"summary": "New"}, format="json")
        assert res2.status_code == status.HTTP_404_NOT_FOUND

        res3 = auth_client.delete("/api/v1/enquiries/12345/")
        assert res3.status_code == status.HTTP_404_NOT_FOUND


# ══════════════════════════════════════════════════════════════════════════════
# 5. QUERY PARAMETERS, FILTERS, SEARCH & PAGINATION
# ══════════════════════════════════════════════════════════════════════════════

class TestQueryParametersAndFilters:
    """Verifies that invalid or adversarial query params never produce a 500 error."""

    def test_invalid_gym_id_query_param_handled_gracefully(self, auth_client):
        res = auth_client.get("/api/v1/enquiries/?gym_id=not-a-valid-uuid")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_user_id_query_param_handled_gracefully(self, auth_client):
        res = auth_client.get("/api/v1/enquiries/?user_id=not-a-valid-uuid")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_unknown_status_and_type_query_param_returns_empty_safely(self, auth_client):
        res_status = auth_client.get("/api/v1/enquiries/?status=FICTIONAL_STATUS_XYZ")
        assert res_status.status_code == status.HTTP_200_OK
        data = res_status.json()
        results = data.get("results", data)
        assert len(results) == 0

        res_type = auth_client.get("/api/v1/enquiries/?type=FICTIONAL_TYPE_XYZ")
        assert res_type.status_code == status.HTTP_200_OK
        data_t = res_type.json()
        results_t = data_t.get("results", data_t)
        assert len(results_t) == 0

    @pytest.mark.parametrize("page_val", [0, -1, "abc", -999])
    def test_invalid_page_number_handled(self, auth_client, page_val):
        res = auth_client.get(f"/api/v1/enquiries/?page={page_val}")
        # DRF PageNumberPagination returns 404 Not Found for invalid pages
        assert res.status_code in [status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST]

    @pytest.mark.parametrize("page_size_val", [0, -1, "invalid", 999999])
    def test_extreme_page_size_clamped_safely(self, auth_client, page_size_val):
        res = auth_client.get(f"/api/v1/enquiries/?page_size={page_size_val}")
        assert res.status_code == status.HTTP_200_OK

    def test_extremely_long_search_query_handled_safely(self, auth_client):
        long_query = "search_test_" + ("a" * 2000)
        res = auth_client.get(f"/api/v1/enquiries/?search={long_query}")
        assert res.status_code == status.HTTP_200_OK


# ══════════════════════════════════════════════════════════════════════════════
# 6. SECURITY & ADVERSARIAL PAYLOADS (SQLi, XSS, UNICODE)
# ══════════════════════════════════════════════════════════════════════════════

class TestSecurityAndInjection:
    """Verifies protection against SQL Injection, XSS, and Unicode edge cases."""

    @pytest.mark.parametrize("sqli_payload", [
        "' OR '1'='1",
        "'; DROP TABLE enquiries; --",
        '" OR ""="',
        "1' or '1'='1",
        "admin'--",
    ])
    def test_sql_injection_payloads_in_search_and_fields(self, auth_client, gym_instance, sqli_payload):
        # 1. Search param injection
        res_search = auth_client.get(f"/api/v1/enquiries/?search={sqli_payload}")
        assert res_search.status_code == status.HTTP_200_OK

        # 2. In summary and notes fields
        payload = {
            "gym_id": str(gym_instance.id),
            "first_name": "Test",
            "last_name": "SQLi",
            "email": "sqli@test.com",
            "summary": sqli_payload,
            "notes": [sqli_payload],
        }
        res_create = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res_create.status_code == status.HTTP_201_CREATED
        assert Enquiry.objects.filter(summary=sqli_payload).exists()

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(document.cookie)",
        "<svg onload=alert(1)>",
    ])
    def test_xss_payloads_stored_safely_without_crash(self, auth_client, gym_instance, xss_payload):
        payload = {
            "gym_id": str(gym_instance.id),
            "first_name": "XSS",
            "last_name": "Tester",
            "email": "xss@test.com",
            "summary": xss_payload,
            "notes": [xss_payload],
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["summary"] == xss_payload

    def test_unicode_and_emojis_in_fields(self, auth_client, gym_instance):
        unicode_summary = "🏋️‍♂️ Fitness inquiry: مرحبا بكم / 健身房咨询 / Z̸a̸l̸g̸o̸"
        payload = {
            "gym_id": str(gym_instance.id),
            "first_name": "Ünïcödë",
            "last_name": "Tëstër",
            "email": "unicode@test.com",
            "summary": unicode_summary,
            "notes": ["🔥 High priority enquiry: 💪"],
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert res.json()["first_name"] == "Ünïcödë"
        assert res.json()["summary"] == unicode_summary


# ══════════════════════════════════════════════════════════════════════════════
# 7. AUTHENTICATION & PERMISSIONS
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthenticationAndPermissions:
    """Verifies that all enquiry endpoints require valid authentication."""

    def test_unauthenticated_requests_return_401(self, sample_enquiry, gym_instance):
        anon_client = APIClient()

        # 1. Unauthenticated users cannot create enquiries
        res_create = anon_client.post(
            "/api/v1/enquiries/",
            data={
                "gym_id": str(gym_instance.id),
                "first_name": "Public",
                "last_name": "Lead",
                "email": "public.lead@example.com",
                "summary": "Public inquiry without auth",
            },
            format="json",
        )
        assert res_create.status_code == status.HTTP_401_UNAUTHORIZED

        # 2. List enquiries requires authentication (staff only)
        res_list = anon_client.get("/api/v1/enquiries/")
        assert res_list.status_code == status.HTTP_401_UNAUTHORIZED

        # 3. View detail requires authentication
        res_detail = anon_client.get(f"/api/v1/enquiries/{sample_enquiry.id}/")
        assert res_detail.status_code == status.HTTP_401_UNAUTHORIZED

        # 4. Update requires authentication
        res_update = anon_client.patch(f"/api/v1/enquiries/{sample_enquiry.id}/", data={"summary": "New"}, format="json")
        assert res_update.status_code == status.HTTP_401_UNAUTHORIZED

        # 5. Delete requires authentication
        res_del = anon_client.delete(f"/api/v1/enquiries/{sample_enquiry.id}/")
        assert res_del.status_code == status.HTTP_401_UNAUTHORIZED

        # 6. Add note requires authentication
        res_note = anon_client.post(f"/api/v1/enquiries/{sample_enquiry.id}/notes/", data={"note_text": "Note"}, format="json")
        assert res_note.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize("bad_header", [
        "Bearer invalid_token_structure",
        "Bearer ",
        "Token 123456",
        "Basic YWxhZGRpbjpvcGVuc2VzYW1l",
    ])
    def test_malformed_auth_headers_rejected(self, bad_header):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=bad_header)
        res = client.get("/api/v1/enquiries/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED


# ══════════════════════════════════════════════════════════════════════════════
# 8. LIFECYCLE & STATE TRANSITIONS
# ══════════════════════════════════════════════════════════════════════════════

class TestBusinessLogicAndStateTransitions:
    """Tests lifecycle transitions, clearing contact info, and idempotent deletions."""

    def test_status_transitions_complete_cycle(self, auth_client, sample_enquiry):
        # 1. NEW -> CONTACTED
        res1 = auth_client.patch(f"/api/v1/enquiries/{sample_enquiry.id}/", data={"status": "CONTACTED"}, format="json")
        assert res1.status_code == status.HTTP_200_OK
        assert res1.json()["status"] == "CONTACTED"

        # 2. CONTACTED -> VISIT
        res2 = auth_client.patch(f"/api/v1/enquiries/{sample_enquiry.id}/", data={"status": "VISIT"}, format="json")
        assert res2.status_code == status.HTTP_200_OK
        assert res2.json()["status"] == "VISIT"

        # 3. VISIT -> BOOKED
        res3 = auth_client.patch(f"/api/v1/enquiries/{sample_enquiry.id}/", data={"status": "BOOKED"}, format="json")
        assert res3.status_code == status.HTTP_200_OK
        assert res3.json()["status"] == "BOOKED"

    def test_invalid_status_transition_rejected(self, auth_client, sample_enquiry):
        res = auth_client.patch(
            f"/api/v1/enquiries/{sample_enquiry.id}/",
            data={"status": "INVALID_STATE_XYZ"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_type_transition_rejected(self, auth_client, sample_enquiry):
        res = auth_client.patch(
            f"/api/v1/enquiries/{sample_enquiry.id}/",
            data={"type": "INVALID_TYPE_XYZ"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_clearing_both_email_and_phone_on_update_rejected(self, auth_client, sample_enquiry):
        # Attempt to wipe both contact fields
        res = auth_client.patch(
            f"/api/v1/enquiries/{sample_enquiry.id}/",
            data={"email": "", "phone": ""},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Either Email or Phone" in str(res.json())

    def test_deleting_already_deleted_enquiry_returns_404(self, auth_client, sample_enquiry):
        # First deletion -> 200
        res1 = auth_client.delete(f"/api/v1/enquiries/{sample_enquiry.id}/")
        assert res1.status_code == status.HTTP_200_OK

        # Second deletion -> 404
        res2 = auth_client.delete(f"/api/v1/enquiries/{sample_enquiry.id}/")
        assert res2.status_code == status.HTTP_404_NOT_FOUND


# ══════════════════════════════════════════════════════════════════════════════
# 9. HTTP METHOD VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

class TestHTTPMethodValidation:
    """Verifies that unsupported HTTP methods return 405 Method Not Allowed."""

    def test_unsupported_methods_on_list_endpoint(self, auth_client):
        # DELETE on collection root
        res_del = auth_client.delete("/api/v1/enquiries/")
        assert res_del.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # PUT on collection root
        res_put = auth_client.put("/api/v1/enquiries/", data={"summary": "New"}, format="json")
        assert res_put.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_unsupported_methods_on_detail_endpoint(self, auth_client, sample_enquiry):
        # POST on individual resource endpoint
        res_post = auth_client.post(f"/api/v1/enquiries/{sample_enquiry.id}/", data={"summary": "New"}, format="json")
        assert res_post.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_unsupported_methods_on_notes_endpoint(self, auth_client, sample_enquiry):
        # GET on notes sub-endpoint
        res_get = auth_client.get(f"/api/v1/enquiries/{sample_enquiry.id}/notes/")
        assert res_get.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # DELETE on notes sub-endpoint
        res_del = auth_client.delete(f"/api/v1/enquiries/{sample_enquiry.id}/notes/")
        assert res_del.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# ══════════════════════════════════════════════════════════════════════════════
# 10. RESPONSE INTEGRITY & NO STACK TRACE LEAKAGE
# ══════════════════════════════════════════════════════════════════════════════

class TestResponseIntegrityAndNoLeakage:
    """Verifies that error responses are strictly formatted without leaking stack traces or internal DB info."""

    def test_no_stack_trace_leakage_on_adversarial_request(self, auth_client):
        res = auth_client.post(
            "/api/v1/enquiries/",
            data={
                "first_name": "Leak",
                "last_name": "Test",
                "email": "invalid_email_format",
                "manygym_user_id": "not-a-uuid",
                "notes": "not-a-list",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        raw_text = res.content.decode("utf-8")
        assert "Traceback" not in raw_text
        assert "psycopg" not in raw_text
        assert "OperationalError" not in raw_text
        assert "ProgrammingError" not in raw_text

