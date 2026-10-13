import uuid
from datetime import timedelta
import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.utils import timezone

from apps.users.models import User, OTPVerification, UserProfile
from apps.gyms.models import Gym
from apps.access_control.models import Role, Permission, GymStaffAssignment
from apps.access_control.services import seed_default_permissions_and_roles
from apps.authentication.services import issue_context_token, authenticate_user
from common.enums import TokenContextType, UserStatus, StaffStatus


@pytest.fixture(autouse=True)
def setup_default_seeds(db):
    seed_default_permissions_and_roles()


# Helper to get authenticated client
def get_auth_client(user, context_type=TokenContextType.PERSONAL, gym=None):
    tokens = issue_context_token(user, context_type=context_type, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client, tokens


# =====================================================================
# 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"email": 12345, "password": "Password123!", "first_name": "Test", "last_name": "User"},
    {"email": ["test@manygym.com"], "password": "Password123!", "first_name": "Test", "last_name": "User"},
    {"email": {"email": "test@manygym.com"}, "password": "Password123!", "first_name": "Test", "last_name": "User"},
    {"email": True, "password": "Password123!", "first_name": "Test", "last_name": "User"},
    {"email": "valid@manygym.com", "password": 12345678, "first_name": "Test", "last_name": "User"},
    {"email": "valid@manygym.com", "password": {"secret": "pass"}, "first_name": "Test", "last_name": "User"},
    {"email": "valid@manygym.com", "password": ["pass1234"], "first_name": "Test", "last_name": "User"},
    {"email": "valid@manygym.com", "password": "Password123!", "first_name": 9999, "last_name": "User"},
    {"email": "valid@manygym.com", "password": "Password123!", "first_name": ["Alice"], "last_name": "User"},
    {"email": "valid@manygym.com", "password": "Password123!", "first_name": "Alice", "last_name": {"nested": "obj"}},
    {"email": "valid@manygym.com", "password": "Password123!", "first_name": "Alice", "last_name": "User", "phone": [1, 2, 3]},
    {"email": "valid@manygym.com", "password": "Password123!", "first_name": "Alice", "last_name": "User", "phone": {"num": 123}},
])
def test_registration_type_juggling(payload):
    client = APIClient()
    res = client.post(reverse("register"), payload, format="json")
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"
    assert "details" in res.json()


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"email": 12345, "password": "Password123!"},
    {"email": ["user@test.com"], "password": "Password123!"},
    {"email": "valid@test.com", "password": 12345678},
    {"email": "valid@test.com", "password": {"secret": "pass"}},
    {"email": "valid@test.com", "password": [1, 2, 3]},
    {"email": None, "password": None},
    {"email": True, "password": False},
])
def test_login_type_juggling(payload):
    client = APIClient()
    res = client.post(reverse("login"), payload, format="json")
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"context_type": 123, "gym_id": str(uuid.uuid4())},
    {"context_type": ["personal"], "gym_id": str(uuid.uuid4())},
    {"context_type": {"type": "gym"}, "gym_id": str(uuid.uuid4())},
    {"context_type": "gym", "gym_id": 12345},
    {"context_type": "gym", "gym_id": [str(uuid.uuid4())]},
    {"context_type": "gym", "gym_id": {"id": str(uuid.uuid4())}},
    {"context_type": "gym", "gym_id": True},
])
def test_switch_context_type_juggling(payload):
    user = User.objects.create_user(email="switcher@manygym.com", password="Password123!", is_verified=True)
    client, _ = get_auth_client(user)
    res = client.post(reverse("switch-context"), payload, format="json")
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"first_name": ["ArrayName"]},
    {"first_name": {"dict": "name"}},
    {"city": [1, 2, 3]},
    {"date_of_birth": 20261012},
    {"date_of_birth": ["2026-10-12"]},
    {"date_of_birth": {"year": 2026, "month": 10, "day": 12}},
    {"avatar_url": [123]},
    {"avatar_url": {"url": "http://img.png"}},
])
def test_profile_update_type_juggling(payload):
    user = User.objects.create_user(email="patcher@manygym.com", password="Password123!", is_verified=True)
    client, _ = get_auth_client(user)
    res = client.patch(reverse("me"), payload, format="json")
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"name": 12345},
    {"name": ["RoleName"]},
    {"name": {"dict": "Role"}},
    {"name": True},
    {"name": "Valid Role", "permission_ids": "not-a-list"},
    {"name": "Valid Role", "permission_ids": 12345},
    {"name": "Valid Role", "permission_ids": [12345]},
    {"name": "Valid Role", "permission_ids": ["not-a-uuid"]},
    {"name": "Valid Role", "permission_ids": [{"uuid": str(uuid.uuid4())}]},
])
def test_create_role_type_juggling(payload):
    owner = User.objects.create_user(email="owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Role Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)
    res = client.post(reverse("roles-list-create"), payload, format="json")
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"email": 12345, "role_id": str(uuid.uuid4())},
    {"email": ["test@manygym.com"], "role_id": str(uuid.uuid4())},
    {"email": "test@manygym.com", "role_id": 12345},
    {"email": "test@manygym.com", "role_id": [str(uuid.uuid4())]},
    {"email": "test@manygym.com", "role_id": {"id": str(uuid.uuid4())}},
    {"email": "test@manygym.com", "role_id": True},
])
def test_invite_staff_type_juggling(payload):
    owner = User.objects.create_user(email="owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Staff Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)
    res = client.post(reverse("staff-list-invite"), payload, format="json")
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"status": 123},
    {"status": ["active"]},
    {"status": {"status": "active"}},
    {"status": True},
    {"status": None},
])
def test_update_staff_status_type_juggling(payload):
    owner = User.objects.create_user(email="owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Staff Gym")
    trainer = Role.objects.get(slug="trainer")
    staff_user = User.objects.create_user(email="staff@manygym.com", password="Password123!", is_verified=True)
    assignment = GymStaffAssignment.objects.create(user=staff_user, gym=gym, role=trainer)

    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)
    res = client.patch(reverse("staff-detail", kwargs={"assignment_id": assignment.id}), payload, format="json")
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


# =====================================================================
# 2. BOUNDARY & LENGTH EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_registration_boundary_and_length():
    client = APIClient()
    url = reverse("register")

    # 1. Empty string fields
    res = client.post(url, {"email": "", "password": "", "first_name": "", "last_name": ""})
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"

    # 2. Whitespace-only fields
    res = client.post(url, {"email": "   ", "password": "        ", "first_name": "   ", "last_name": "   "})
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"

    # 3. Exactly 7 chars password (min is 8)
    res = client.post(url, {"email": "short@manygym.com", "password": "1234567", "first_name": "A", "last_name": "B"})
    assert res.status_code == 400
    assert "password" in res.json()["details"]

    # 4. Exactly 8 chars password (valid min boundary)
    res = client.post(url, {"email": "min8@manygym.com", "password": "12345678", "first_name": "A", "last_name": "B"})
    assert res.status_code == 201

    # 5. Extremely large input strings (10,000+ characters)
    huge_str = "A" * 10000
    res = client.post(url, {
        "email": f"{huge_str}@manygym.com",
        "password": "Password123!",
        "first_name": huge_str,
        "last_name": huge_str,
    })
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_otp_boundary_lengths():
    client = APIClient()
    url = reverse("verify-signup-otp")

    # OTP code boundaries (expected 6 chars)
    # 5 digits (min - 1)
    res = client.post(url, {"email": "test@manygym.com", "otp_code": "12345"})
    assert res.status_code == 400

    # 7 digits (max + 1)
    res = client.post(url, {"email": "test@manygym.com", "otp_code": "1234567"})
    assert res.status_code == 400

    # 1,000 digits
    res = client.post(url, {"email": "test@manygym.com", "otp_code": "9" * 1000})
    assert res.status_code == 400


@pytest.mark.django_db
def test_role_name_boundary_lengths():
    owner = User.objects.create_user(email="owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Bound Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)
    url = reverse("roles-list-create")

    # Empty and whitespace-only name
    res = client.post(url, {"name": ""})
    assert res.status_code == 400
    res = client.post(url, {"name": "   "})
    assert res.status_code == 400

    # 101 characters (max is 100)
    res = client.post(url, {"name": "X" * 101})
    assert res.status_code == 400
    assert "name" in res.json()["details"]

    # 10,000 characters
    res = client.post(url, {"name": "X" * 10000})
    assert res.status_code == 400


# =====================================================================
# 3. MISSING, EXTRA, MALFORMED & INJECTED FIELDS
# =====================================================================

@pytest.mark.django_db
def test_completely_empty_json_body_on_all_post_endpoints():
    client = APIClient()
    endpoints = [
        reverse("register"),
        reverse("login"),
        reverse("verify-signup-otp"),
        reverse("resend-otp"),
        reverse("forgot-password"),
        reverse("verify-reset-otp"),
        reverse("reset-password"),
    ]
    for ep in endpoints:
        res = client.post(ep, {}, format="json")
        assert res.status_code == 400, f"Endpoint {ep} failed with status {res.status_code}"
        assert res.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_100_unexpected_garbage_fields_injection():
    client = APIClient()
    garbage_payload = {f"garbage_key_{i}": f"value_{i}" for i in range(100)}
    garbage_payload["email"] = "valid.user@manygym.com"
    garbage_payload["password"] = "SecurePassword2026!"
    garbage_payload["first_name"] = "Garbage"
    garbage_payload["last_name"] = "Tester"

    # Extra fields must be ignored and not crash the system
    res = client.post(reverse("register"), garbage_payload, format="json")
    assert res.status_code == 201


@pytest.mark.django_db
def test_privilege_escalation_and_mass_assignment_injection():
    client = APIClient()
    malicious_payload = {
        "email": "hacker@manygym.com",
        "password": "Password123!",
        "first_name": "Malicious",
        "last_name": "User",
        # Attack vectors attempting privilege escalation
        "is_superuser": True,
        "is_staff": True,
        "is_verified": True,
        "status": "active",
        "id": str(uuid.uuid4()),
        "created_at": "1990-01-01T00:00:00Z",
    }
    res = client.post(reverse("register"), malicious_payload, format="json")
    assert res.status_code == 201

    created_user = User.objects.get(email="hacker@manygym.com")
    assert created_user.is_superuser is False
    assert created_user.is_staff is False
    assert created_user.is_verified is False

    # Attempt mass assignment on PATCH /me/
    auth_client, _ = get_auth_client(created_user)
    patch_attack = {
        "is_superuser": True,
        "is_staff": True,
        "is_verified": True,
        "id": str(uuid.uuid4()),
        "email": "superhacker@admin.com",
    }
    res_patch = auth_client.patch(reverse("me"), patch_attack, format="json")
    assert res_patch.status_code == 200

    created_user.refresh_from_db()
    assert created_user.is_superuser is False
    assert created_user.is_staff is False
    assert created_user.is_verified is False
    assert created_user.email == "hacker@manygym.com"


# =====================================================================
# 4. FORMAT-SPECIFIC INVALID INPUTS
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("bad_email", [
    "plainaddress",
    "#@%^%#$@#$@#.com",
    "@example.com",
    "Joe Smith <email@example.com>",
    "email.example.com",
    "email@example@example.com",
    ".email@example.com",
    "email.@example.com",
    "email..email@example.com",
    "email@example.com (Joe Smith)",
    "email@example",
    "email@-example.com",
    "email@example..com",
    "spaces in@example.com",
])
def test_invalid_email_formats(bad_email):
    client = APIClient()
    res = client.post(reverse("register"), {
        "email": bad_email,
        "password": "ValidPassword123!",
        "first_name": "Invalid",
        "last_name": "Email",
    })
    assert res.status_code == 400
    assert "email" in res.json()["details"]


@pytest.mark.django_db
@pytest.mark.parametrize("bad_date", [
    "2026-13-45",
    "2026-02-31",
    "31-12-2026",
    "12/31/2026",
    "today",
    "yesterday",
    "2026.10.12",
    "1760000000",
    "99999-99-99",
])
def test_invalid_date_formats(bad_date):
    user = User.objects.create_user(email="date.user@manygym.com", password="Password123!", is_verified=True)
    client, _ = get_auth_client(user)
    res = client.patch(reverse("me"), {"date_of_birth": bad_date})
    assert res.status_code == 400
    assert "date_of_birth" in res.json()["details"]


@pytest.mark.django_db
@pytest.mark.parametrize("bad_uuid", [
    "not-a-uuid",
    "12345",
    "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
    "0",
    "-1",
    "null",
])
def test_malformed_uuid_query_params_and_paths(bad_uuid):
    owner = User.objects.create_user(email="owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="UUID Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    # Query param with malformed UUID must return 404 or gracefully handled without 500
    res_staff = client.get(reverse("staff-list-invite"), {"gym_id": bad_uuid})
    assert res_staff.status_code == 404
    assert res_staff.json()["code"] in ("NOT_FOUND", "RESOURCE_NOT_FOUND")

    res_roles = client.get(reverse("roles-list-create"), {"gym_id": bad_uuid})
    assert res_roles.status_code in (200, 404)
    assert res_roles.status_code != 500

    # Path parameter with non-existent valid UUID
    ghost_uuid = str(uuid.uuid4())
    res_role_get = client.get(reverse("role-detail", kwargs={"role_id": ghost_uuid}))
    assert res_role_get.status_code == 404

    res_staff_get = client.patch(reverse("staff-detail", kwargs={"assignment_id": ghost_uuid}), {"status": "active"})
    assert res_staff_get.status_code == 404


# =====================================================================
# 5. QUERY PARAMETERS, FILTERS & PAGINATION EDGE CASES
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("page_param", [
    {"page": 0},
    {"page": -1},
    {"page": -999},
    {"page": "abc"},
    {"page": "null"},
    {"page": " "},
    {"page": 99999999},
])
def test_pagination_page_number_edge_cases(page_param):
    owner = User.objects.create_user(email="owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Page Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    res = client.get(reverse("staff-list-invite"), page_param)
    # Invalid page number should return 404 Not Found as per DRF PageNumberPagination
    assert res.status_code in (400, 404)
    assert res.status_code != 500


@pytest.mark.django_db
@pytest.mark.parametrize("page_size_param", [
    {"page_size": 0},
    {"page_size": -1},
    {"page_size": "abc"},
    {"page_size": 999999},
    {"page_size": "1000000000000000000000000"},
])
def test_pagination_page_size_edge_cases(page_size_param):
    owner = User.objects.create_user(email="owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Size Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    res = client.get(reverse("staff-list-invite"), page_size_param)
    assert res.status_code == 200
    assert res.status_code != 500


@pytest.mark.django_db
def test_arbitrary_garbage_query_parameters():
    owner = User.objects.create_user(email="owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Garbage Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    garbage_params = {
        "__proto__": "polluted",
        "select": "*",
        "drop": "table",
        "x": "y" * 1000,
        "array[]": ["1", "2"],
    }
    res = client.get(reverse("staff-list-invite"), garbage_params)
    assert res.status_code == 200
    assert res.status_code != 500


# =====================================================================
# 6. SECURITY & INJECTION TESTING
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("sqli_payload", [
    "' OR '1'='1",
    "' OR 1=1 --",
    "admin' --",
    "' UNION SELECT NULL, NULL, NULL --",
    "1; DROP TABLE users; --",
    "'; EXEC xp_cmdshell('dir'); --",
    "' OR '' = '",
])
def test_sql_injection_resilience(sqli_payload):
    client = APIClient()

    # SQLi in Login
    res_login = client.post(reverse("login"), {"email": sqli_payload, "password": "password"})
    assert res_login.status_code == 400
    assert res_login.status_code != 500

    # SQLi in Register
    res_reg = client.post(reverse("register"), {
        "email": f"{sqli_payload}@manygym.com",
        "password": "Password123!",
        "first_name": sqli_payload,
        "last_name": "Tester",
    })
    assert res_reg.status_code in (400, 201)
    assert res_reg.status_code != 500

    # SQLi in query param
    owner = User.objects.create_user(email="owner.sqli@manygym.com", password="Password123!", is_verified=True)
    auth_client, _ = get_auth_client(owner)
    res_sqli_param = auth_client.get(reverse("staff-list-invite"), {"gym_id": sqli_payload})
    assert res_sqli_param.status_code == 404
    assert res_sqli_param.status_code != 500


@pytest.mark.django_db
@pytest.mark.parametrize("xss_payload", [
    "<script>alert('XSS')</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(document.cookie)",
    "<svg/onload=alert(1)>",
    "'\"><script src=//evil.com></script>",
])
def test_xss_payload_storage_and_response_safety(xss_payload):
    user = User.objects.create_user(email="xss.user@manygym.com", password="Password123!", is_verified=True)
    client, _ = get_auth_client(user)

    # Update profile with XSS string
    res = client.patch(reverse("me"), {
        "first_name": xss_payload[:100],
        "city": xss_payload[:100],
    })
    assert res.status_code == 200
    data = res.json()
    assert data["user"]["first_name"] == xss_payload[:100]


@pytest.mark.django_db
@pytest.mark.parametrize("path_payload", [
    "../../../../../../etc/passwd",
    "..\\..\\..\\..\\windows\\system32\\cmd.exe",
    "/etc/shadow",
    "http://169.254.169.254/latest/meta-data/",
])
def test_path_traversal_and_ssrf_resilience(path_payload):
    user = User.objects.create_user(email="path.user@manygym.com", password="Password123!", is_verified=True)
    client, _ = get_auth_client(user)

    res = client.patch(reverse("me"), {"avatar_url": path_payload})
    assert res.status_code == 200
    assert res.status_code != 500


@pytest.mark.django_db
@pytest.mark.parametrize("unicode_text", [
    "🏋️‍♂️🔥💪",  # Emojis
    "مرحبا بك في جيم ماني",  # Arabic RTL
    "Z͔̪̯͑ͫ̓a̧̠lͫgͥoͩ",  # Combining Zalgo
    "こんにちは世界",  # Japanese Kanji/Hiragana
    "Ñáéíóú¿¡",  # Accented Latin
])
def test_unicode_and_special_character_resilience(unicode_text):
    client = APIClient()
    res = client.post(reverse("register"), {
        "email": f"unicode_{uuid.uuid4().hex[:6]}@manygym.com",
        "password": "Password123!",
        "first_name": unicode_text[:100],
        "last_name": "Tester",
    })
    assert res.status_code == 201
    assert res.status_code != 500


# =====================================================================
# 7. AUTHENTICATION, AUTHORIZATION & PERMISSIONS
# =====================================================================

@pytest.mark.django_db
def test_unauthenticated_requests_to_all_protected_endpoints():
    client = APIClient()
    dummy_uuid = str(uuid.uuid4())
    protected_urls = [
        ("GET", reverse("me")),
        ("PATCH", reverse("me")),
        ("POST", reverse("change-password")),
        ("POST", reverse("logout")),
        ("POST", reverse("switch-context")),
        ("GET", reverse("permissions-list")),
        ("GET", reverse("roles-list-create")),
        ("POST", reverse("roles-list-create")),
        ("GET", reverse("role-detail", kwargs={"role_id": dummy_uuid})),
        ("PATCH", reverse("role-detail", kwargs={"role_id": dummy_uuid})),
        ("DELETE", reverse("role-detail", kwargs={"role_id": dummy_uuid})),
        ("GET", reverse("staff-list-invite")),
        ("POST", reverse("staff-list-invite")),
        ("PATCH", reverse("staff-detail", kwargs={"assignment_id": dummy_uuid})),
        ("DELETE", reverse("staff-detail", kwargs={"assignment_id": dummy_uuid})),
    ]

    for method, url in protected_urls:
        if method == "GET":
            res = client.get(url)
        elif method == "POST":
            res = client.post(url, {})
        elif method == "PATCH":
            res = client.patch(url, {})
        elif method == "DELETE":
            res = client.delete(url)

        assert res.status_code == 401, f"{method} {url} returned {res.status_code} instead of 401"
        assert res.json()["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.django_db
@pytest.mark.parametrize("header_value", [
    "Bearer ",
    "Bearer",
    "Bearer invalid.jwt.token",
    "Basic YWRtaW46cGFzc3dvcmQ=",
    "Token 123456",
    "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.signature",
])
def test_malformed_and_invalid_auth_headers(header_value):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=header_value)
    res = client.get(reverse("me"))
    assert res.status_code == 401
    assert res.json()["code"] == "AUTHENTICATION_REQUIRED"


@pytest.mark.django_db
def test_inactive_and_suspended_user_rejection():
    # Inactive user
    user = User.objects.create_user(
        email="inactive@manygym.com",
        password="Password123!",
        is_verified=True,
        is_active=False,
    )
    client = APIClient()
    res_login = client.post(reverse("login"), {"email": user.email, "password": "Password123!"})
    assert res_login.status_code == 400
    assert "inactive" in res_login.json()["message"].lower()

    # Suspended user
    user_suspended = User.objects.create_user(
        email="suspended@manygym.com",
        password="Password123!",
        is_verified=True,
        status=UserStatus.SUSPENDED,
    )
    res_susp = client.post(reverse("login"), {"email": user_suspended.email, "password": "Password123!"})
    assert res_susp.status_code == 400
    assert "suspended" in res_susp.json()["message"].lower()


# =====================================================================
# 8. IDOR & OBJECT-LEVEL AUTHORIZATION
# =====================================================================

@pytest.mark.django_db
def test_cross_tenant_idor_role_modification():
    # Setup Gym A with Owner A and Manager A (has people_roles:manage on Gym A)
    owner_a = User.objects.create_user(email="ownerA@manygym.com", password="Password123!", is_verified=True)
    gym_a = Gym.objects.create(owner_user=owner_a, name="Gym A")

    manager_a = User.objects.create_user(email="managerA@manygym.com", password="Password123!", is_verified=True)
    admin_role = Role.objects.get(slug="administrator")
    GymStaffAssignment.objects.create(user=manager_a, gym=gym_a, role=admin_role, status=StaffStatus.ACTIVE)

    # Setup Gym B with Owner B and custom Role B
    owner_b = User.objects.create_user(email="ownerB@manygym.com", password="Password123!", is_verified=True)
    gym_b = Gym.objects.create(owner_user=owner_b, name="Gym B")
    role_b = Role.objects.create(gym=gym_b, name="Gym B Custom Role", slug="gym-b-custom-role", is_custom=True)

    # Manager A logs in under Gym A context
    manager_client, _ = get_auth_client(manager_a, context_type=TokenContextType.GYM, gym=gym_a)

    # IDOR Attack: Manager A attempts to PATCH Role B belonging to Gym B
    res_patch = manager_client.patch(
        reverse("role-detail", kwargs={"role_id": role_b.id}),
        {"name": "Hacked Gym B Role"},
    )
    assert res_patch.status_code in (403, 404)
    assert res_patch.status_code != 500

    # IDOR Attack: Manager A attempts to DELETE Role B
    res_del = manager_client.delete(reverse("role-detail", kwargs={"role_id": role_b.id}))
    assert res_del.status_code in (403, 404)
    assert res_del.status_code != 500

    # Verify Role B was not altered
    role_b.refresh_from_db()
    assert role_b.name == "Gym B Custom Role"


@pytest.mark.django_db
def test_cross_tenant_idor_staff_modification():
    owner_a = User.objects.create_user(email="ownerA@manygym.com", password="Password123!", is_verified=True)
    gym_a = Gym.objects.create(owner_user=owner_a, name="Gym A")

    manager_a = User.objects.create_user(email="managerA@manygym.com", password="Password123!", is_verified=True)
    admin_role = Role.objects.get(slug="administrator")
    GymStaffAssignment.objects.create(user=manager_a, gym=gym_a, role=admin_role, status=StaffStatus.ACTIVE)

    owner_b = User.objects.create_user(email="ownerB@manygym.com", password="Password123!", is_verified=True)
    gym_b = Gym.objects.create(owner_user=owner_b, name="Gym B")
    staff_b = User.objects.create_user(email="staffB@manygym.com", password="Password123!", is_verified=True)
    assignment_b = GymStaffAssignment.objects.create(user=staff_b, gym=gym_b, role=admin_role, status=StaffStatus.ACTIVE)

    manager_client, _ = get_auth_client(manager_a, context_type=TokenContextType.GYM, gym=gym_a)

    # IDOR Attack: Manager A attempts to deactivate Staff B in Gym B
    res_patch = manager_client.patch(
        reverse("staff-detail", kwargs={"assignment_id": assignment_b.id}),
        {"status": "inactive"},
    )
    assert res_patch.status_code in (403, 404)

    # IDOR Attack: Manager A attempts to delete Staff B in Gym B
    res_del = manager_client.delete(reverse("staff-detail", kwargs={"assignment_id": assignment_b.id}))
    assert res_del.status_code in (403, 404)

    # IDOR Attack: Manager A queries Staff directory of Gym B
    res_dir = manager_client.get(reverse("staff-list-invite"), {"gym_id": str(gym_b.id)})
    assert res_dir.status_code in (403, 404)


# =====================================================================
# 9. BUSINESS LOGIC & INVALID STATE TRANSITIONS
# =====================================================================

@pytest.mark.django_db
def test_cannot_delete_global_system_roles():
    owner = User.objects.create_user(email="owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Admin Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    admin_role = Role.objects.get(slug="administrator")
    res = client.delete(reverse("role-detail", kwargs={"role_id": admin_role.id}))
    assert res.status_code == 400
    assert "cannot be deleted" in res.json()["message"]


@pytest.mark.django_db
def test_cannot_delete_role_assigned_to_active_staff():
    owner = User.objects.create_user(email="owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Active Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    custom_role = Role.objects.create(gym=gym, name="Busy Role", slug="busy-role", is_custom=True)
    trainer = User.objects.create_user(email="trainer@manygym.com", password="Password123!", is_verified=True)
    GymStaffAssignment.objects.create(user=trainer, gym=gym, role=custom_role, status=StaffStatus.ACTIVE)

    res = client.delete(reverse("role-detail", kwargs={"role_id": custom_role.id}))
    assert res.status_code == 400
    assert "currently assigned" in res.json()["message"]


@pytest.mark.django_db
def test_foreign_role_assignment_rejection():
    owner_a = User.objects.create_user(email="ownerA@manygym.com", password="Password123!", is_verified=True)
    gym_a = Gym.objects.create(owner_user=owner_a, name="Gym A")

    owner_b = User.objects.create_user(email="ownerB@manygym.com", password="Password123!", is_verified=True)
    gym_b = Gym.objects.create(owner_user=owner_b, name="Gym B")
    role_b = Role.objects.create(gym=gym_b, name="Gym B Role", slug="gym-b-role", is_custom=True)

    client, _ = get_auth_client(owner_a, context_type=TokenContextType.GYM, gym=gym_a)
    user_target = User.objects.create_user(email="target@manygym.com", password="Password123!", is_verified=True)

    # Attempt to assign Gym B's custom role to a staff member in Gym A
    res = client.post(reverse("staff-list-invite"), {
        "email": user_target.email,
        "role_id": str(role_b.id),
    })
    assert res.status_code == 400
    assert "does not belong to this gym" in res.json()["message"]


# =====================================================================
# 10. HTTP METHODS & CONTENT-TYPE VALIDATION
# =====================================================================

@pytest.mark.django_db
def test_unsupported_http_methods():
    client = APIClient()

    # GET on Register (POST-only)
    res = client.get(reverse("register"))
    assert res.status_code == 405
    assert res.json()["code"] == "METHOD_NOT_ALLOWED"

    # GET on Login (POST-only)
    res = client.get(reverse("login"))
    assert res.status_code == 405
    assert res.json()["code"] == "METHOD_NOT_ALLOWED"

    # POST on Health Check (GET-only)
    res = client.post(reverse("common:health-check"), {})
    assert res.status_code == 405
    assert res.json()["code"] == "METHOD_NOT_ALLOWED"

    # DELETE on Me Profile (GET, PATCH only)
    user = User.objects.create_user(email="me.del@manygym.com", password="Password123!", is_verified=True)
    auth_client, _ = get_auth_client(user)
    res_del_me = auth_client.delete(reverse("me"))
    assert res_del_me.status_code == 405
    assert res_del_me.json()["code"] == "METHOD_NOT_ALLOWED"


@pytest.mark.django_db
def test_malformed_json_syntax_returns_400():
    client = APIClient()
    # Malformed unparseable JSON string
    res = client.post(
        reverse("register"),
        data='{"email": "broken@manygym.com", "password": ',
        content_type="application/json",
    )
    assert res.status_code == 400
    assert res.json()["code"] == "VALIDATION_ERROR"
    assert "details" in res.json()


# =====================================================================
# 11. RESPONSE FORMAT & INFORMATION LEAKAGE VALIDATION
# =====================================================================

@pytest.mark.django_db
def test_standardized_error_envelope_structure_on_all_failures():
    client = APIClient()
    res = client.post(reverse("register"), {"email": "invalid"})
    assert res.status_code == 400
    data = res.json()

    # Verify standard envelope keys: code, message, details
    assert "code" in data
    assert "message" in data
    assert "details" in data
    assert isinstance(data["code"], str)
    assert isinstance(data["message"], str)
    assert isinstance(data["details"], (dict, list))

    # Verify NO stack trace or internal database query leakage
    res_text = res.content.decode("utf-8")
    assert "Traceback" not in res_text
    assert "django.db" not in res_text
    assert "psycopg" not in res_text
    assert "SELECT " not in res_text
