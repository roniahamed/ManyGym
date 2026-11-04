import uuid
from datetime import timedelta
import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.urls import reverse
from django.utils import timezone
from django.core.cache import cache

from apps.users.models import User, OTPVerification, UserProfile
from apps.gyms.models import Gym, GymSetting
from apps.access_control.models import GymStaffAssignment
from apps.access_control.services import seed_default_permissions_and_roles
from apps.authentication.services import issue_context_token, authenticate_user
from apps.users.services.settings_services import apply_user_access_control_action
from common.enums import TokenContextType, UserStatus


@pytest.fixture(autouse=True)
def clean_environment(db):
    """Seed permissions and clean Redis cache before and after every test."""
    seed_default_permissions_and_roles()
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def verified_user(db):
    user = User.objects.create_user(
        email="alice.verified@manygym.com",
        password="SecurePassword2026!",
        first_name="Alice",
        last_name="Tester",
        phone="+14155551111",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def unverified_user(db):
    user = User.objects.create_user(
        email="bob.unverified@manygym.com",
        password="SecurePassword2026!",
        first_name="Bob",
        last_name="Pending",
        phone="+14155552222",
        is_verified=False,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def gym_owner_user(db):
    user = User.objects.create_user(
        email="charlie.owner@manygym.com",
        password="SecurePassword2026!",
        first_name="Charlie",
        last_name="Owner",
        phone="+14155553333",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def owner_gym(gym_owner_user):
    gym = Gym.objects.create(name="Apex Fitness Club", owner_user=gym_owner_user)
    GymSetting.objects.get_or_create(gym=gym)
    return gym


def get_auth_client(user, context_type=TokenContextType.PERSONAL, gym=None):
    tokens = issue_context_token(user, context_type=context_type, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client, tokens


# ==============================================================================
# 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
# ==============================================================================

@pytest.mark.django_db
class TestAuthTypeJuggling:
    """Tests all endpoints for type juggling: int, float, bool, list, dict, null."""

    @pytest.mark.parametrize("payload", [
        {"email": 12345, "password": "SecurePassword2026!"},
        {"email": ["alice@manygym.com"], "password": "SecurePassword2026!"},
        {"email": {"addr": "alice@manygym.com"}, "password": "SecurePassword2026!"},
        {"email": True, "password": "SecurePassword2026!"},
        {"email": None, "password": "SecurePassword2026!"},
        {"email": "alice.verified@manygym.com", "password": 12345678},
        {"email": "alice.verified@manygym.com", "password": 45.67},
        {"email": "alice.verified@manygym.com", "password": True},
        {"email": "alice.verified@manygym.com", "password": ["array_pass"]},
        {"email": "alice.verified@manygym.com", "password": {"secret": "pass"}},
        {"email": "alice.verified@manygym.com", "password": None},
        {"email": "alice.verified@manygym.com", "password": "SecurePassword2026!", "reactivate": "not_a_bool"},
        {"email": "alice.verified@manygym.com", "password": "SecurePassword2026!", "restore": ["invalid"]},
    ])
    def test_login_type_juggling(self, payload):
        client = APIClient()
        res = client.post(reverse("login"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"
        assert "details" in res.json()

    @pytest.mark.parametrize("payload", [
        {"refresh": 12345},
        {"refresh": 99.99},
        {"refresh": True},
        {"refresh": ["token_in_array"]},
        {"refresh": {"token": "secret"}},
    ])
    def test_logout_type_juggling(self, verified_user, payload):
        client, _ = get_auth_client(verified_user)
        res = client.post(reverse("logout"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("payload", [
        {"refresh": 12345},
        {"refresh": 88.88},
        {"refresh": True},
        {"refresh": ["token_array"]},
        {"refresh": {"key": "token"}},
        {"refresh": None},
    ])
    def test_refresh_type_juggling(self, payload):
        client = APIClient()
        res = client.post(reverse("token-refresh"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("payload", [
        {"context_type": 12345},
        {"context_type": 12.34},
        {"context_type": True},
        {"context_type": ["personal"]},
        {"context_type": {"type": "personal"}},
        {"context_type": None},
        {"context_type": "gym", "gym_id": 12345},
        {"context_type": "gym", "gym_id": 55.55},
        {"context_type": "gym", "gym_id": True},
        {"context_type": "gym", "gym_id": [str(uuid.uuid4())]},
        {"context_type": "gym", "gym_id": {"id": str(uuid.uuid4())}},
    ])
    def test_switch_context_type_juggling(self, verified_user, payload):
        client, _ = get_auth_client(verified_user)
        res = client.post(reverse("switch-context"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("payload", [
        {"email": 12345, "password": "SecurePassword2026!", "first_name": "Test", "last_name": "User"},
        {"email": "valid@manygym.com", "password": 12345678, "first_name": "Test", "last_name": "User"},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": 12345, "last_name": "User"},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": "Test", "last_name": 12345},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": "Test", "last_name": "User", "phone": 12345},
        {"email": ["valid@manygym.com"], "password": "SecurePassword2026!", "first_name": "Test", "last_name": "User"},
        {"email": "valid@manygym.com", "password": ["array_pass"], "first_name": "Test", "last_name": "User"},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": ["Test"], "last_name": "User"},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": "Test", "last_name": ["User"]},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": "Test", "last_name": "User", "phone": ["phone"]},
        {"email": {"email": "v@m.com"}, "password": "SecurePassword2026!", "first_name": "Test", "last_name": "User"},
        {"email": "valid@manygym.com", "password": {"secret": "pass"}, "first_name": "Test", "last_name": "User"},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": {"name": "Test"}, "last_name": "User"},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": "Test", "last_name": {"name": "User"}},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": "Test", "last_name": "User", "phone": {"num": 1}},
        {"email": None, "password": "SecurePassword2026!", "first_name": "Test", "last_name": "User"},
        {"email": "valid@manygym.com", "password": None, "first_name": "Test", "last_name": "User"},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": None, "last_name": "User"},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": "Test", "last_name": None},
        {"email": True, "password": "SecurePassword2026!", "first_name": "Test", "last_name": "User"},
        {"email": "valid@manygym.com", "password": True, "first_name": "Test", "last_name": "User"},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": True, "last_name": "User"},
        {"email": "valid@manygym.com", "password": "SecurePassword2026!", "first_name": "Test", "last_name": True},
    ])
    def test_register_type_juggling(self, payload):
        client = APIClient()
        res = client.post(reverse("register"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("payload", [
        {"email": 12345, "otp_code": "123456"},
        {"email": ["user@manygym.com"], "otp_code": "123456"},
        {"email": {"e": "user@manygym.com"}, "otp_code": "123456"},
        {"email": True, "otp_code": "123456"},
        {"email": None, "otp_code": "123456"},
        {"email": "user@manygym.com", "otp_code": 123456},
        {"email": "user@manygym.com", "otp_code": 12.34},
        {"email": "user@manygym.com", "otp_code": True},
        {"email": "user@manygym.com", "otp_code": ["123456"]},
        {"email": "user@manygym.com", "otp_code": {"code": "123456"}},
        {"email": "user@manygym.com", "otp_code": None},
    ])
    def test_verify_signup_otp_type_juggling(self, payload):
        client = APIClient()
        res = client.post(reverse("verify-signup-otp"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("payload", [
        {"email": 12345},
        {"email": 12.34},
        {"email": True},
        {"email": ["user@manygym.com"]},
        {"email": {"email": "user@manygym.com"}},
        {"email": None},
    ])
    def test_resend_otp_type_juggling(self, payload):
        client = APIClient()
        res = client.post(reverse("resend-otp"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("payload", [
        {"email": 12345},
        {"email": 12.34},
        {"email": True},
        {"email": ["user@manygym.com"]},
        {"email": {"email": "user@manygym.com"}},
        {"email": None},
    ])
    def test_forgot_password_type_juggling(self, payload):
        client = APIClient()
        res = client.post(reverse("forgot-password"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("payload", [
        {"email": 12345, "otp_code": "123456"},
        {"email": "user@manygym.com", "otp_code": 123456},
        {"email": "user@manygym.com", "otp_code": True},
        {"email": "user@manygym.com", "otp_code": ["123456"]},
        {"email": "user@manygym.com", "otp_code": {"code": "123456"}},
        {"email": "user@manygym.com", "otp_code": None},
    ])
    def test_verify_reset_otp_type_juggling(self, payload):
        client = APIClient()
        res = client.post(reverse("verify-reset-otp"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("payload", [
        {"email": 12345, "otp_code": "123456", "new_password": "NewSecurePassword2026!"},
        {"email": "user@manygym.com", "otp_code": 123456, "new_password": "NewSecurePassword2026!"},
        {"email": "user@manygym.com", "otp_code": "123456", "new_password": 12345678},
        {"email": "user@manygym.com", "otp_code": "123456", "new_password": True},
        {"email": "user@manygym.com", "otp_code": "123456", "new_password": ["pass1234"]},
        {"email": "user@manygym.com", "otp_code": "123456", "new_password": {"p": "pass1234"}},
        {"email": "user@manygym.com", "otp_code": "123456", "new_password": None},
    ])
    def test_reset_password_type_juggling(self, payload):
        client = APIClient()
        res = client.post(reverse("reset-password"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("payload", [
        {"current_password": 12345678, "new_password": "NewSecurePassword2026!"},
        {"current_password": "SecurePassword2026!", "new_password": 12345678},
        {"current_password": True, "new_password": "NewSecurePassword2026!"},
        {"current_password": "SecurePassword2026!", "new_password": True},
        {"current_password": ["curr_pass"], "new_password": "NewSecurePassword2026!"},
        {"current_password": "SecurePassword2026!", "new_password": ["new_pass"]},
        {"current_password": {"p": "curr"}, "new_password": "NewSecurePassword2026!"},
        {"current_password": "SecurePassword2026!", "new_password": {"p": "new"}},
        {"current_password": None, "new_password": "NewSecurePassword2026!"},
        {"current_password": "SecurePassword2026!", "new_password": None},
    ])
    def test_change_password_type_juggling(self, verified_user, payload):
        client, _ = get_auth_client(verified_user)
        res = client.post(reverse("change-password"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize("payload", [
        {"first_name": 12345},
        {"first_name": ["Alice"]},
        {"first_name": {"name": "Alice"}},
        {"last_name": 12345},
        {"last_name": ["Tester"]},
        {"phone": 12345},
        {"phone": ["+14155551111"]},
        {"date_of_birth": 20261012},
        {"date_of_birth": ["2026-10-12"]},
        {"date_of_birth": {"year": 2026}},
        {"address": 12345},
        {"address": ["Street 123"]},
        {"city": 12345},
        {"city": ["San Francisco"]},
        {"country": 12345},
        {"sex": 12345},
        {"nationality": 12345},
    ])
    def test_patch_me_type_juggling(self, verified_user, payload):
        client, _ = get_auth_client(verified_user)
        res = client.patch(reverse("me"), payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"


# ==============================================================================
# 2. BOUNDARY & LENGTH EDGE CASES
# ==============================================================================

@pytest.mark.django_db
class TestAuthBoundaryAndLengthEdgeCases:
    """Tests empty strings, whitespace, min/max bounds, and extreme lengths."""

    def test_empty_strings_on_required_fields(self, verified_user):
        client = APIClient()
        auth_client, _ = get_auth_client(verified_user)

        # Login empty fields
        res = client.post(reverse("login"), {"email": "", "password": ""}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Refresh empty
        res = client.post(reverse("token-refresh"), {"refresh": ""}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Switch context empty
        res = auth_client.post(reverse("switch-context"), {"context_type": ""}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Register empty
        res = client.post(
            reverse("register"),
            {"email": "", "password": "", "first_name": "", "last_name": ""},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Verify signup OTP empty
        res = client.post(reverse("verify-signup-otp"), {"email": "", "otp_code": ""}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Resend OTP empty
        res = client.post(reverse("resend-otp"), {"email": ""}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Forgot password empty
        res = client.post(reverse("forgot-password"), {"email": ""}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Verify reset OTP empty
        res = client.post(reverse("verify-reset-otp"), {"email": "", "otp_code": ""}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Reset password empty
        res = client.post(
            reverse("reset-password"),
            {"email": "", "otp_code": "", "new_password": ""},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Change password empty
        res = auth_client.post(
            reverse("change-password"),
            {"current_password": "", "new_password": ""},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_whitespace_only_values(self, verified_user):
        client = APIClient()
        auth_client, _ = get_auth_client(verified_user)

        res = client.post(reverse("login"), {"email": "   ", "password": "   "}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        res = client.post(reverse("token-refresh"), {"refresh": "   "}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        res = client.post(
            reverse("register"),
            {"email": "   ", "password": "        ", "first_name": "   ", "last_name": "   "},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        res = client.post(
            reverse("verify-signup-otp"),
            {"email": "  alice@manygym.com  ", "otp_code": "      "},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_otp_length_boundaries(self):
        client = APIClient()

        # OTP < 6 chars (min - 1)
        res = client.post(
            reverse("verify-signup-otp"),
            {"email": "user@manygym.com", "otp_code": "12345"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "details" in res.json()

        # OTP > 6 chars (max + 1)
        res = client.post(
            reverse("verify-signup-otp"),
            {"email": "user@manygym.com", "otp_code": "1234567"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_password_length_boundaries(self, verified_user):
        client = APIClient()
        auth_client, _ = get_auth_client(verified_user)

        # 7-char password in registration (min - 1) -> rejected
        res = client.post(
            reverse("register"),
            {
                "email": "shortpass@manygym.com",
                "password": "Pass12!",
                "first_name": "Short",
                "last_name": "Pass",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 7-char password in change password (min - 1) -> rejected
        res = auth_client.post(
            reverse("change-password"),
            {"current_password": "SecurePassword2026!", "new_password": "Pass12!"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 8-char password in change password (exact min) -> accepted
        res = auth_client.post(
            reverse("change-password"),
            {"current_password": "SecurePassword2026!", "new_password": "Pass1234"},
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK

    def test_name_max_length_boundaries(self):
        client = APIClient()

        # 100-char name (exact max) -> valid
        max_name = "A" * 100
        res = client.post(
            reverse("register"),
            {
                "email": "boundary.name@manygym.com",
                "password": "SecurePassword2026!",
                "first_name": max_name,
                "last_name": max_name,
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED

        # 101-char name (max + 1) -> rejected
        overflow_name = "A" * 101
        res = client.post(
            reverse("register"),
            {
                "email": "overflow.name@manygym.com",
                "password": "SecurePassword2026!",
                "first_name": overflow_name,
                "last_name": "Normal",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_extremely_long_strings_zero_500(self, verified_user):
        client = APIClient()
        auth_client, _ = get_auth_client(verified_user)
        extreme_str = "X" * 15000

        # Extreme password on login -> 400, no 500
        res = client.post(
            reverse("login"),
            {"email": "alice.verified@manygym.com", "password": extreme_str},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Extreme refresh token on refresh endpoint -> 400 or 401, no 500
        res = client.post(reverse("token-refresh"), {"refresh": extreme_str}, format="json")
        assert res.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED]

        # Extreme address and city in profile PATCH -> 400, no 500
        res = auth_client.patch(
            reverse("me"),
            {"address": extreme_str, "city": extreme_str},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 3. MISSING, EXTRA & MALFORMED FIELDS
# ==============================================================================

@pytest.mark.django_db
class TestAuthMissingExtraMalformedFields:
    """Tests empty bodies, missing individual fields, garbage fields, and read-only protection."""

    def test_empty_json_body_on_all_endpoints(self, verified_user):
        client = APIClient()
        auth_client, _ = get_auth_client(verified_user)

        # Public endpoints
        assert client.post(reverse("login"), {}, format="json").status_code == 400
        assert client.post(reverse("token-refresh"), {}, format="json").status_code == 400
        assert client.post(reverse("register"), {}, format="json").status_code == 400
        assert client.post(reverse("verify-signup-otp"), {}, format="json").status_code == 400
        assert client.post(reverse("resend-otp"), {}, format="json").status_code == 400
        assert client.post(reverse("forgot-password"), {}, format="json").status_code == 400
        assert client.post(reverse("verify-reset-otp"), {}, format="json").status_code == 400
        assert client.post(reverse("reset-password"), {}, format="json").status_code == 400

        # Protected endpoints
        assert auth_client.post(reverse("switch-context"), {}, format="json").status_code == 400
        assert auth_client.post(reverse("change-password"), {}, format="json").status_code == 400
        # Me PATCH with empty payload is valid (no-op profile update)
        assert auth_client.patch(reverse("me"), {}, format="json").status_code == 200

        # Logout with empty payload is valid because refresh is optional (use separate client to avoid revoking auth_client)
        logout_client, _ = get_auth_client(verified_user)
        assert logout_client.post(reverse("logout"), {}, format="json").status_code == 200

    def test_missing_required_fields_individually_in_registration(self):
        client = APIClient()
        valid = {
            "email": "new.member@manygym.com",
            "password": "SecurePassword2026!",
            "first_name": "New",
            "last_name": "Member",
        }
        for field in ["email", "password", "first_name", "last_name"]:
            payload = {k: v for k, v in valid.items() if k != field}
            res = client.post(reverse("register"), payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST
            assert field in res.json().get("details", {})

    def test_unexpected_garbage_fields_are_ignored_or_handled_gracefully(self, verified_user):
        client = APIClient()
        garbage = {f"garbage_key_{i}": f"value_{i}" for i in range(100)}

        # Login with valid credentials + 100 garbage fields
        payload = {
            "email": "alice.verified@manygym.com",
            "password": "SecurePassword2026!",
            **garbage,
        }
        res = client.post(reverse("login"), payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert "tokens" in res.json()

    def test_mass_assignment_protection_during_registration(self):
        client = APIClient()
        malicious_id = str(uuid.uuid4())
        payload = {
            "email": "mass.assignment@manygym.com",
            "password": "SecurePassword2026!",
            "first_name": "Attacker",
            "last_name": "User",
            "id": malicious_id,
            "is_verified": True,
            "is_staff": True,
            "is_superuser": True,
            "status": "active",
        }
        res = client.post(reverse("register"), payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED

        # Verify user record was NOT compromised by client-supplied privilege fields
        created_user = User.objects.get(email="mass.assignment@manygym.com")
        assert str(created_user.id) != malicious_id
        assert created_user.is_verified is False
        assert created_user.is_staff is False
        assert created_user.is_superuser is False

    def test_mass_assignment_protection_in_profile_patch(self, verified_user):
        auth_client, _ = get_auth_client(verified_user)
        malicious_id = str(uuid.uuid4())
        payload = {
            "id": malicious_id,
            "email": "tampered@manygym.com",
            "is_verified": False,
            "status": "deactivated",
            "is_staff": True,
            "first_name": "UpdatedAlice",
        }
        res = auth_client.patch(reverse("me"), payload, format="json")
        assert res.status_code == status.HTTP_200_OK

        verified_user.refresh_from_db()
        assert str(verified_user.id) != malicious_id
        assert verified_user.email == "alice.verified@manygym.com"
        assert verified_user.is_verified is True
        assert verified_user.status == UserStatus.ACTIVE
        assert verified_user.first_name == "UpdatedAlice"


# ==============================================================================
# 4. FORMAT-SPECIFIC INVALID INPUTS
# ==============================================================================

@pytest.mark.django_db
class TestAuthFormatSpecificInvalidInputs:
    """Tests malformed emails, UUIDs, non-numeric OTP codes, and dates."""

    @pytest.mark.parametrize("bad_email", [
        "notanemail",
        "missingatsign.com",
        "@nodomain.com",
        "user@",
        "user@.com",
        "user@domain..com",
        "user name@domain.com",
        "user@@domain.com",
        ("a" * 250) + "@domain.com",
    ])
    def test_malformed_emails_rejected(self, bad_email):
        client = APIClient()
        res = client.post(
            reverse("register"),
            {
                "email": bad_email,
                "password": "SecurePassword2026!",
                "first_name": "Test",
                "last_name": "User",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_uuid", [
        "not-a-uuid",
        "12345",
        "00000000-0000-0000-0000",
        "g" * 36,
    ])
    def test_malformed_uuid_in_switch_context(self, verified_user, bad_uuid):
        auth_client, _ = get_auth_client(verified_user)
        res = auth_client.post(
            reverse("switch-context"),
            {"context_type": "gym", "gym_id": bad_uuid},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.json()["code"] == "VALIDATION_ERROR"

    def test_nonexistent_gym_uuid_returns_404(self, verified_user):
        auth_client, _ = get_auth_client(verified_user)
        non_existent_uuid = str(uuid.uuid4())
        res = auth_client.post(
            reverse("switch-context"),
            {"context_type": "gym", "gym_id": non_existent_uuid},
            format="json",
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND
        assert res.json()["code"] == "RESOURCE_NOT_FOUND"

    @pytest.mark.parametrize("bad_otp", [
        "abcdef",
        "12345a",
        "!@#$%^",
        "12 456",
        "-12345",
        "12.345",
    ])
    def test_malformed_otp_codes_rejected(self, bad_otp):
        client = APIClient()
        res = client.post(
            reverse("verify-signup-otp"),
            {"email": "user@manygym.com", "otp_code": bad_otp},
            format="json",
        )
        assert res.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]

    @pytest.mark.parametrize("bad_date", [
        "2026-13-45",
        "31/12/2026",
        "today",
        "yesterday",
        "2026-02-30",
        "1700000000",
    ])
    def test_invalid_dates_in_profile_patch(self, verified_user, bad_date):
        auth_client, _ = get_auth_client(verified_user)
        res = auth_client.patch(
            reverse("me"),
            {"date_of_birth": bad_date},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 5. QUERY PARAMETERS, FILTERS & PAGINATION
# ==============================================================================

@pytest.mark.django_db
class TestAuthQueryParamsAndFilters:
    """Ensures query params on auth endpoints never cause 500 or alter operations."""

    def test_get_me_handles_unexpected_query_params_and_sqli(self, verified_user):
        auth_client, _ = get_auth_client(verified_user)

        res = auth_client.get(
            reverse("me") + "?foo=bar&unknown=123&search=' OR 1=1 --&page=abc&page_size=-10"
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert "user" in data
        assert data["user"]["email"] == "alice.verified@manygym.com"

    def test_post_endpoints_ignore_query_strings(self, verified_user):
        client = APIClient()
        res = client.post(
            reverse("login") + "?action=delete&admin=true",
            {"email": "alice.verified@manygym.com", "password": "SecurePassword2026!"},
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        assert "tokens" in res.json()


# ==============================================================================
# 6. SECURITY & INJECTION TESTING
# ==============================================================================

@pytest.mark.django_db
class TestAuthSecurityAndInjection:
    """Tests SQL injection, XSS payloads, path traversal, and complex Unicode."""

    @pytest.mark.parametrize("sqli_payload", [
        "' OR '1'='1",
        "' OR 1=1 --",
        "admin'--",
        "'; DROP TABLE users CASCADE; --",
        "' UNION SELECT NULL, NULL, NULL --",
        "\" OR \"\"=\"",
    ])
    def test_sql_injection_in_login_email(self, verified_user, sqli_payload):
        client = APIClient()
        res = client.post(
            reverse("login"),
            {"email": sqli_payload, "password": "RandomPassword123!"},
            format="json",
        )
        # Email validator will reject malformed emails with 400
        assert res.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_401_UNAUTHORIZED]
        assert User.objects.filter(id=verified_user.id).exists()  # DB intact

    @pytest.mark.parametrize("sqli_payload", [
        "' OR '1'='1",
        "' OR 1=1 --",
        "admin'--",
        "'; DROP TABLE users CASCADE; --",
    ])
    def test_sql_injection_in_login_password(self, verified_user, sqli_payload):
        client = APIClient()
        res = client.post(
            reverse("login"),
            {"email": "alice.verified@manygym.com", "password": sqli_payload},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert User.objects.filter(id=verified_user.id).exists()

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(document.cookie)",
        "<svg/onload=alert(1)>",
    ])
    def test_xss_payload_in_user_profile(self, verified_user, xss_payload):
        auth_client, _ = get_auth_client(verified_user)
        res = auth_client.patch(
            reverse("me"),
            {
                "first_name": xss_payload,
                "city": xss_payload,
                "address": xss_payload,
            },
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()["user"]
        # Stored safely without crashing serializer or DB
        assert data["first_name"] == xss_payload

    @pytest.mark.parametrize("path_traversal", [
        "../../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\cmd.exe",
        "..%2F..%2Fetc%2Fpasswd",
    ])
    def test_path_traversal_in_avatar_url(self, verified_user, path_traversal):
        auth_client, _ = get_auth_client(verified_user)
        res = auth_client.patch(
            reverse("me"),
            {"avatar_url": path_traversal},
            format="json",
        )
        # Should either be accepted as a text string or rejected, but never 500
        assert res.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]

    def test_complex_unicode_and_emojis(self, verified_user):
        auth_client, _ = get_auth_client(verified_user)
        unicode_payload = {
            "first_name": "🏋️‍♂️ Alex 🚀",
            "last_name": "مرحبا שלום",
            "city": "東京都",
            "country": "Россия",
            "address": "Z̷a̷l̷g̷o̷ text",
        }
        res = auth_client.patch(reverse("me"), unicode_payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()["user"]
        assert data["first_name"] == "🏋️‍♂️ Alex 🚀"
        assert data["last_name"] == "مرحبا שלום"


# ==============================================================================
# 7. AUTHENTICATION, AUTHORIZATION & PERMISSIONS
# ==============================================================================

@pytest.mark.django_db
class TestAuthAuthenticationAndPermissions:
    """Tests missing, empty, malformed, tampered, expired, and revoked tokens."""

    def test_protected_endpoints_require_authentication(self):
        client = APIClient()

        assert client.get(reverse("me")).status_code == status.HTTP_401_UNAUTHORIZED
        assert client.patch(reverse("me"), {"first_name": "Test"}).status_code == status.HTTP_401_UNAUTHORIZED
        assert client.post(reverse("logout"), {}).status_code == status.HTTP_401_UNAUTHORIZED
        assert client.post(reverse("switch-context"), {"context_type": "personal"}).status_code == status.HTTP_401_UNAUTHORIZED
        assert client.post(reverse("change-password"), {"current_password": "a", "new_password": "b"}).status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize("bad_header", [
        "",
        "Bearer",
        "Bearer ",
        "Bearer invalid.jwt.token",
        "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.signature",
        "Basic dXNlcjpwYXNz",
    ])
    def test_malformed_auth_headers_return_401(self, bad_header):
        client = APIClient()
        if bad_header:
            client.credentials(HTTP_AUTHORIZATION=bad_header)
        res = client.get(reverse("me"))
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_revoked_token_cannot_access_protected_endpoint(self, verified_user):
        client, tokens = get_auth_client(verified_user)

        # Logout revokes token
        logout_res = client.post(reverse("logout"), {"refresh": tokens["refresh"]}, format="json")
        assert logout_res.status_code == status.HTTP_200_OK

        # Revoked access token fails immediately
        me_res = client.get(reverse("me"))
        assert me_res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_inactive_suspended_user_token_is_rejected(self, verified_user):
        client, _ = get_auth_client(verified_user)

        # Deactivate user
        verified_user.is_active = False
        verified_user.status = UserStatus.DEACTIVATED
        verified_user.save()

        res = client.get(reverse("me"))
        assert res.status_code == status.HTTP_401_UNAUTHORIZED


# ==============================================================================
# 8. IDOR & OBJECT-LEVEL AUTHORIZATION
# ==============================================================================

@pytest.mark.django_db
class TestAuthIDORAndObjectLevelAuthorization:
    """Tests switching to unauthorized gyms, cross-tenant token tampering, and profile isolation."""

    def test_user_cannot_switch_to_gym_they_do_not_own_or_work_at(self, verified_user, owner_gym):
        client, _ = get_auth_client(verified_user)

        # Alice attempts to switch context to Charlie's gym
        res = client.post(
            reverse("switch-context"),
            {"context_type": "gym", "gym_id": str(owner_gym.id)},
            format="json",
        )
        assert res.status_code == status.HTTP_401_UNAUTHORIZED
        assert res.json()["code"] == "UNAUTHORIZED_CONTEXT"

    def test_user_cannot_switch_to_deleted_gym(self, gym_owner_user, owner_gym):
        client, _ = get_auth_client(gym_owner_user)

        # Soft-delete gym settings
        owner_gym.settings.is_deleted = True
        owner_gym.settings.save()

        res = client.post(
            reverse("switch-context"),
            {"context_type": "gym", "gym_id": str(owner_gym.id)},
            format="json",
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND
        assert res.json()["code"] == "RESOURCE_NOT_FOUND"

    def test_profile_update_idor_isolation(self, verified_user, gym_owner_user):
        alice_client, _ = get_auth_client(verified_user)

        # Alice attempts to submit Charlie's user ID or target fields
        res = alice_client.patch(
            reverse("me"),
            {
                "user_id": str(gym_owner_user.id),
                "first_name": "AliceUpdated",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK

        # Charlie's profile must be unchanged
        gym_owner_user.refresh_from_db()
        assert gym_owner_user.first_name == "Charlie"


# ==============================================================================
# 9. BUSINESS LOGIC & INVALID STATE TRANSITIONS
# ==============================================================================

@pytest.mark.django_db
class TestAuthBusinessLogicAndStateTransitions:
    """Tests invalid state transitions: unverified login, deleted/deactivated recovery, and OTP burn."""

    def test_unverified_user_cannot_login(self, unverified_user):
        client = APIClient()
        res = client.post(
            reverse("login"),
            {"email": "bob.unverified@manygym.com", "password": "SecurePassword2026!"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "not been verified" in res.json()["message"]

    def test_deactivated_user_login_without_flag_rejected(self, verified_user):
        apply_user_access_control_action(verified_user, action="deactivate")

        client = APIClient()
        # Login without reactivate flag
        res = client.post(
            reverse("login"),
            {"email": "alice.verified@manygym.com", "password": "SecurePassword2026!"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "deactivated" in res.json()["message"]

        # Login with reactivate flag succeeds
        res_reactivate = client.post(
            reverse("login"),
            {
                "email": "alice.verified@manygym.com",
                "password": "SecurePassword2026!",
                "reactivate": True,
            },
            format="json",
        )
        assert res_reactivate.status_code == status.HTTP_200_OK
        assert "reactivated" in res_reactivate.json()["message"]

    def test_deleted_user_login_without_flag_rejected(self, verified_user):
        apply_user_access_control_action(
            verified_user, action="delete", password="SecurePassword2026!", confirmation="delete"
        )

        client = APIClient()
        # Login without restore flag
        res = client.post(
            reverse("login"),
            {"email": "alice.verified@manygym.com", "password": "SecurePassword2026!"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "deleted" in res.json()["message"]

        # Login with restore flag succeeds
        res_restore = client.post(
            reverse("login"),
            {
                "email": "alice.verified@manygym.com",
                "password": "SecurePassword2026!",
                "restore": True,
            },
            format="json",
        )
        assert res_restore.status_code == status.HTTP_200_OK
        assert "restored" in res_restore.json()["message"]

    def test_cannot_verify_already_verified_user(self, verified_user):
        client = APIClient()
        otp = OTPVerification.objects.create(
            email=verified_user.email,
            otp_code="112233",
            purpose="signup_verification",
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        res = client.post(
            reverse("verify-signup-otp"),
            {"email": verified_user.email, "otp_code": "112233"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "already verified" in res.json()["message"]

    def test_cannot_resend_otp_to_already_verified_user(self, verified_user):
        client = APIClient()
        res = client.post(
            reverse("resend-otp"),
            {"email": verified_user.email},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "already verified" in res.json()["message"]

    def test_expired_otp_is_rejected(self, unverified_user):
        client = APIClient()
        OTPVerification.objects.create(
            email=unverified_user.email,
            otp_code="998877",
            purpose="signup_verification",
            expires_at=timezone.now() - timedelta(minutes=5),  # expired
        )
        res = client.post(
            reverse("verify-signup-otp"),
            {"email": unverified_user.email, "otp_code": "998877"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "expired" in res.json()["message"]

    def test_used_otp_is_rejected(self, unverified_user):
        client = APIClient()
        OTPVerification.objects.create(
            email=unverified_user.email,
            otp_code="554433",
            purpose="signup_verification",
            is_used=True,
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        res = client.post(
            reverse("verify-signup-otp"),
            {"email": unverified_user.email, "otp_code": "554433"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_otp_brute_force_5_attempt_burn_lockout(self, unverified_user):
        client = APIClient()
        otp = OTPVerification.objects.create(
            email=unverified_user.email,
            otp_code="654321",
            purpose="signup_verification",
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        # 4 failed attempts show countdown
        for attempt in range(1, 5):
            res = client.post(
                reverse("verify-signup-otp"),
                {"email": unverified_user.email, "otp_code": f"00000{attempt}"},
                format="json",
            )
            assert res.status_code == status.HTTP_400_BAD_REQUEST
            assert f"{5 - attempt} attempt(s) remaining" in res.json()["message"]

        # 5th failed attempt burns the code
        res5 = client.post(
            reverse("verify-signup-otp"),
            {"email": unverified_user.email, "otp_code": "000005"},
            format="json",
        )
        assert res5.status_code == status.HTTP_400_BAD_REQUEST
        assert "invalidated" in res5.json()["message"]

        # 6th attempt with CORRECT code is now rejected because it was burned/marked used
        res6 = client.post(
            reverse("verify-signup-otp"),
            {"email": unverified_user.email, "otp_code": "654321"},
            format="json",
        )
        assert res6.status_code == status.HTTP_400_BAD_REQUEST
        assert any(
            phrase in res6.json()["message"].lower()
            for phrase in ["invalid", "expired", "invalidated"]
        )

    def test_login_brute_force_lockout_after_5_wrong_passwords(self, verified_user):
        client = APIClient()

        # 4 wrong password attempts
        for _ in range(4):
            res = client.post(
                reverse("login"),
                {"email": "alice.verified@manygym.com", "password": "WrongPassword!"},
                format="json",
            )
            assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 5th wrong password attempt locks the account with 429
        res5 = client.post(
            reverse("login"),
            {"email": "alice.verified@manygym.com", "password": "WrongPassword!"},
            format="json",
        )
        assert res5.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "locked" in str(res5.json()).lower()

    def test_change_password_with_incorrect_current_password(self, verified_user):
        auth_client, _ = get_auth_client(verified_user)
        res = auth_client.post(
            reverse("change-password"),
            {
                "current_password": "WrongCurrentPassword123!",
                "new_password": "NewBrandNewPassword2026!",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "current password" in res.json()["message"].lower()


# ==============================================================================
# 10. HTTP METHOD & ENDPOINT VALIDATION
# ==============================================================================

@pytest.mark.django_db
class TestAuthHTTPMethodValidation:
    """Verifies that unsupported HTTP methods return 405 Method Not Allowed."""

    @pytest.mark.parametrize("endpoint_name,allowed_methods", [
        ("login", ["POST"]),
        ("logout", ["POST"]),
        ("token-refresh", ["POST"]),
        ("switch-context", ["POST"]),
        ("register", ["POST"]),
        ("verify-signup-otp", ["POST"]),
        ("resend-otp", ["POST"]),
        ("forgot-password", ["POST"]),
        ("verify-reset-otp", ["POST"]),
        ("reset-password", ["POST"]),
        ("change-password", ["POST"]),
    ])
    def test_post_endpoints_reject_get_put_patch_delete(self, verified_user, endpoint_name, allowed_methods):
        auth_client, _ = get_auth_client(verified_user)
        url = reverse(endpoint_name)

        if "GET" not in allowed_methods:
            assert auth_client.get(url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        if "PUT" not in allowed_methods:
            assert auth_client.put(url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        if "PATCH" not in allowed_methods:
            assert auth_client.patch(url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        if "DELETE" not in allowed_methods:
            assert auth_client.delete(url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_get_me_rejects_post_put_delete(self, verified_user):
        auth_client, _ = get_auth_client(verified_user)
        url = reverse("me")

        assert auth_client.post(url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert auth_client.put(url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert auth_client.delete(url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# ==============================================================================
# 11. RESPONSE VALIDATION & ZERO 500S
# ==============================================================================

@pytest.mark.django_db
class TestAuthResponseValidation:
    """Verifies standard error response envelopes and zero sensitive data leaks."""

    def test_standard_error_envelope_structure(self):
        client = APIClient()
        res = client.post(reverse("login"), {}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        data = res.json()
        assert "code" in data
        assert "message" in data
        assert "details" in data
        assert isinstance(data["details"], dict)

    def test_no_stack_traces_or_database_leaks(self):
        client = APIClient()
        res = client.post(
            reverse("login"),
            {"email": "nonexistent@manygym.com", "password": "WrongPassword!"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        content = str(res.content)
        # Ensure no SQL queries, traceback tokens, or server internals leak
        assert "Traceback (most recent call last)" not in content
        assert "psycopg2" not in content
        assert "SELECT" not in content
        assert "django.db" not in content
