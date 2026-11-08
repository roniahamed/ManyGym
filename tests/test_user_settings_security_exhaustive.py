import uuid
from datetime import timedelta
from unittest.mock import patch
import pytest
from django.urls import reverse
from django.utils import timezone
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserSetting, UserDevice, OTPVerification
from apps.messaging.models import UserDeviceKey
from apps.authentication.models import AuthToken
from common.enums import UserStatus


@pytest.fixture(autouse=True)
def clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user_alice(db):
    user = User.objects.create_user(
        email="alice.security@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Smith",
        phone="+14155551111",
        secondary_email="alice.backup@example.com",
        is_verified=True,
    )
    user.get_settings()
    return user


@pytest.fixture
def user_bob(db):
    user = User.objects.create_user(
        email="bob.security@example.com",
        password="SecurePassword456!",
        first_name="Bob",
        last_name="Jones",
        phone="+14155552222",
        secondary_email="bob.backup@example.com",
        is_verified=True,
    )
    user.get_settings()
    return user


@pytest.fixture
def alice_client(user_alice):
    client = APIClient()
    from apps.authentication.services import issue_context_token
    tokens = issue_context_token(user_alice)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    client.token = tokens["access"]
    return client


@pytest.fixture
def bob_client(user_bob):
    client = APIClient()
    from apps.authentication.services import issue_context_token
    tokens = issue_context_token(user_bob)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    client.token = tokens["access"]
    return client


# ==============================================================================
# 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
# ==============================================================================

@pytest.mark.django_db
class TestSecurityTypeJuggling:
    """Tests all endpoints against unexpected primitive and complex data types."""

    def test_contact_info_type_juggling(self, alice_client):
        url = reverse("user-settings-security-contact-info")

        # secondary_email with invalid types
        assert alice_client.patch(url, {"secondary_email": 12345}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"secondary_email": True}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"secondary_email": ["backup@example.com"]}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"secondary_email": {"email": "backup@example.com"}}, format="json").status_code == status.HTTP_400_BAD_REQUEST

        # phone with invalid types
        assert alice_client.patch(url, {"phone": 123456789}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"phone": True}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"phone": ["+14155551111"]}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"phone": {"number": "+14155551111"}}, format="json").status_code == status.HTTP_400_BAD_REQUEST

    def test_two_factor_toggle_type_juggling(self, alice_client):
        url = reverse("user-settings-security-2fa")

        # two_factor_enabled must be strictly boolean
        assert alice_client.patch(url, {"two_factor_enabled": "true"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"two_factor_enabled": "yes"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"two_factor_enabled": 1}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"two_factor_enabled": 0}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"two_factor_enabled": 1.5}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"two_factor_enabled": [True]}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"two_factor_enabled": {"enabled": True}}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.patch(url, {"two_factor_enabled": None}, format="json").status_code == status.HTTP_400_BAD_REQUEST

    def test_change_password_type_juggling(self, alice_client):
        url = reverse("user-settings-security-change-password")

        # current_password and new_password with invalid types
        assert alice_client.post(url, {"current_password": 12345678, "new_password": "NewPassword123!"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.post(url, {"current_password": "SecurePassword123!", "new_password": 12345678}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.post(url, {"current_password": True, "new_password": "NewPassword123!"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.post(url, {"current_password": ["SecurePassword123!"], "new_password": "NewPassword123!"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.post(url, {"current_password": {"p": "pass"}, "new_password": "NewPassword123!"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert alice_client.post(url, {"current_password": None, "new_password": "NewPassword123!"}, format="json").status_code == status.HTTP_400_BAD_REQUEST

    def test_verify_2fa_type_juggling(self):
        client = APIClient()
        url = reverse("verify-2fa")

        assert client.post(url, {"email": 12345, "otp_code": "123456"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(url, {"email": ["alice@example.com"], "otp_code": "123456"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(url, {"email": "alice@example.com", "otp_code": 123456}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(url, {"email": "alice@example.com", "otp_code": True}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(url, {"email": "alice@example.com", "otp_code": [1, 2, 3]}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(url, {"email": "alice@example.com", "otp_code": {"code": "123456"}}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(url, {"email": "alice@example.com", "otp_code": None}, format="json").status_code == status.HTTP_400_BAD_REQUEST

    def test_resend_2fa_type_juggling(self):
        client = APIClient()
        url = reverse("resend-2fa")

        assert client.post(url, {"email": 12345}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(url, {"email": True}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(url, {"email": ["alice@example.com"]}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(url, {"email": {"email": "alice@example.com"}}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(url, {"email": "alice@example.com", "channel": 123}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(url, {"email": "alice@example.com", "channel": ["primary_email"]}, format="json").status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 2. BOUNDARY & LENGTH EDGE CASES
# ==============================================================================

@pytest.mark.django_db
class TestSecurityBoundaryAndLength:
    """Tests string boundaries, min/max lengths, and extreme character inputs."""

    def test_phone_boundary_lengths(self, alice_client, user_alice):
        url = reverse("user-settings-security-contact-info")

        # Exact 50 chars -> 200 OK
        valid_50 = "+1" + "9" * 48
        res_50 = alice_client.patch(url, {"phone": valid_50}, format="json")
        assert res_50.status_code == status.HTTP_200_OK

        # 51 chars (max + 1) -> 400 Bad Request
        invalid_51 = "+1" + "9" * 49
        res_51 = alice_client.patch(url, {"phone": invalid_51}, format="json")
        assert res_51.status_code == status.HTTP_400_BAD_REQUEST

        # 10,000 characters extreme payload -> 400 Bad Request (no 500 crash)
        extreme_phone = "9" * 10000
        res_extreme = alice_client.patch(url, {"phone": extreme_phone}, format="json")
        assert res_extreme.status_code == status.HTTP_400_BAD_REQUEST

    def test_password_boundary_lengths(self, alice_client, user_alice):
        url = reverse("user-settings-security-change-password")

        # 7 chars (min - 1) -> 400 Bad Request
        res_7 = alice_client.post(
            url,
            {"current_password": "SecurePassword123!", "new_password": "short1!"},
            format="json",
        )
        assert res_7.status_code == status.HTTP_400_BAD_REQUEST

        # 8 chars (exact min) -> 200 OK
        res_8 = alice_client.post(
            url,
            {"current_password": "SecurePassword123!", "new_password": "eight12!"},
            format="json",
        )
        assert res_8.status_code == status.HTTP_200_OK

        # 10,000 chars extreme length -> 200 OK or graceful rejection (no 500 crash)
        extreme_pw = "A1!" + "x" * 9997
        res_extreme = alice_client.post(
            url,
            {"current_password": "eight12!", "new_password": extreme_pw},
            format="json",
        )
        assert res_extreme.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]

    def test_otp_code_boundary_lengths(self, user_alice):
        client = APIClient()
        url = reverse("verify-2fa")

        # 5 digits (min - 1) -> 400
        assert client.post(url, {"email": user_alice.email, "otp_code": "12345"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        # 7 digits (max + 1) -> 400
        assert client.post(url, {"email": user_alice.email, "otp_code": "1234567"}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        # 1,000 digits -> 400
        assert client.post(url, {"email": user_alice.email, "otp_code": "9" * 1000}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        # 6 letters (alphanumeric instead of numeric digits) -> 400
        assert client.post(url, {"email": user_alice.email, "otp_code": "abcdef"}, format="json").status_code == status.HTTP_400_BAD_REQUEST

    def test_device_id_boundary_lengths(self, alice_client, user_alice):
        # 100 chars (max) -> can register and delete
        dev_100 = "d" * 100
        UserDevice.objects.create(user=user_alice, device_id=dev_100)
        del_url = reverse("user-settings-security-device-detail", kwargs={"device_id": dev_100})
        assert alice_client.delete(del_url).status_code == status.HTTP_200_OK


# ==============================================================================
# 3. MISSING, EXTRA & MALFORMED FIELDS
# ==============================================================================

@pytest.mark.django_db
class TestSecurityMissingExtraAndMalformedFields:
    """Tests empty bodies, garbage fields injection, and read-only field tampering."""

    def test_empty_json_bodies(self, alice_client):
        # Empty PATCH on contact-info is valid (no-op)
        res_ci = alice_client.patch(reverse("user-settings-security-contact-info"), {}, format="json")
        assert res_ci.status_code == status.HTTP_200_OK

        # Empty PATCH on 2fa fails (requires two_factor_enabled)
        res_2fa = alice_client.patch(reverse("user-settings-security-2fa"), {}, format="json")
        assert res_2fa.status_code == status.HTTP_400_BAD_REQUEST

        # Empty POST on change-password fails (missing required fields)
        res_pw = alice_client.post(reverse("user-settings-security-change-password"), {}, format="json")
        assert res_pw.status_code == status.HTTP_400_BAD_REQUEST

        # Empty POST on verify-2fa fails
        client = APIClient()
        assert client.post(reverse("verify-2fa"), {}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        # Empty POST on resend-2fa fails
        assert client.post(reverse("resend-2fa"), {}, format="json").status_code == status.HTTP_400_BAD_REQUEST

    def test_100_garbage_fields_injection(self, alice_client, user_alice):
        url = reverse("user-settings-security-contact-info")
        garbage_payload = {f"garbage_key_{i}": f"value_{i}" for i in range(100)}
        garbage_payload["phone"] = "+14155553333"

        res = alice_client.patch(url, garbage_payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        user_alice.refresh_from_db()
        assert user_alice.phone == "+14155553333"

    def test_read_only_and_server_controlled_field_tampering(self, alice_client, user_alice):
        url = reverse("user-settings-security-contact-info")

        # Attempt to inject primary_email -> strictly rejected with 400
        res_primary = alice_client.patch(url, {"primary_email": "attacker@example.com"}, format="json")
        assert res_primary.status_code == status.HTTP_400_BAD_REQUEST
        assert "primary email cannot be updated or deleted" in str(res_primary.data).lower()

        # Attempt to inject email -> strictly rejected with 400
        res_email = alice_client.patch(url, {"email": "attacker@example.com"}, format="json")
        assert res_email.status_code == status.HTTP_400_BAD_REQUEST
        assert "primary email cannot be updated or deleted" in str(res_email.data).lower()

        # Attempt to inject server-controlled status/security flags in contact-info
        res_tamper = alice_client.patch(
            url,
            {
                "is_staff": True,
                "is_superuser": True,
                "status": "active",
                "two_factor_enabled": False,
                "is_deleted": False,
            },
            format="json",
        )
        assert res_tamper.status_code == status.HTTP_200_OK
        user_alice.refresh_from_db()
        assert user_alice.is_staff is False
        assert user_alice.is_superuser is False


# ==============================================================================
# 4. FORMAT-SPECIFIC INVALID INPUTS
# ==============================================================================

@pytest.mark.django_db
class TestSecurityFormatSpecificInvalidInputs:
    """Tests invalid emails, invalid enums, and malformed identifiers."""

    def test_invalid_secondary_email_formats(self, alice_client):
        url = reverse("user-settings-security-contact-info")
        invalid_emails = [
            "plainaddress",
            "@missingusername.com",
            "username@.com",
            "username@domain..com",
            "username@ domain.com",
            "user@domain@another.com",
        ]
        for bad_email in invalid_emails:
            res = alice_client.patch(url, {"secondary_email": bad_email}, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400 for {bad_email}"

    def test_invalid_channel_choices_in_resend_2fa(self, user_alice):
        client = APIClient()
        url = reverse("resend-2fa")
        invalid_channels = ["telegram", "carrier_pigeon", "smoke_signal", "whatsapp", ""]
        for bad_channel in invalid_channels:
            res = client.post(url, {"email": user_alice.email, "channel": bad_channel}, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 5. QUERY PARAMETERS AND SEARCH
# ==============================================================================

@pytest.mark.django_db
class TestSecurityQueryParametersAndSearch:
    """Verifies that unexpected query parameters never cause a 500 error."""

    def test_unexpected_query_params_on_endpoints(self, alice_client):
        endpoints = [
            reverse("user-settings-security"),
            reverse("user-settings-security-contact-info"),
            reverse("user-settings-security-2fa"),
            reverse("user-settings-security-devices"),
        ]
        malicious_queries = [
            "?q=' OR 1=1--",
            "?page=-1&limit=0",
            "?page=abc&limit=99999999",
            "?sort=<script>alert(1)</script>",
            "?filter[user_id]=../../etc/passwd",
        ]
        for ep in endpoints:
            for q in malicious_queries:
                res = alice_client.get(f"{ep}{q}")
                assert res.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]


# ==============================================================================
# 6. SECURITY & INJECTION TESTING
# ==============================================================================

@pytest.mark.django_db
class TestSecurityInjectionAndAdversarialInputs:
    """Tests SQL injection, XSS, Path Traversal, Null Bytes, and Unicode characters."""

    def test_sqli_payloads(self, alice_client, user_alice):
        url = reverse("user-settings-security-contact-info")
        sqli_payloads = [
            "' OR '1'='1",
            "'; DROP TABLE users; --",
            "1; SELECT * FROM auth_tokens",
            "admin'--",
        ]
        for payload in sqli_payloads:
            # Send SQLi in phone (safe rejection or string storage, no SQL execution)
            res = alice_client.patch(url, {"phone": payload}, format="json")
            assert res.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]
            # Ensure DB is intact
            assert User.objects.filter(id=user_alice.id).exists()

    def test_xss_payloads(self, alice_client):
        url = reverse("user-settings-security-contact-info")
        xss_payloads = [
            "<script>alert('xss')</script>",
            "<img src=x onerror=alert(1)>",
            "javascript:alert(1)",
        ]
        for payload in xss_payloads:
            res = alice_client.patch(url, {"phone": payload}, format="json")
            assert res.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]

    def test_path_traversal_on_device_detail(self, alice_client):
        traversal_ids = [
            "../../etc/passwd",
            "..%2F..%2Fetc%2Fpasswd",
            "/var/run/secrets",
            "....//....//etc/passwd",
        ]
        for tid in traversal_ids:
            url = f"/api/v1/users/settings/security/devices/{tid}/"
            res = alice_client.delete(url)
            assert res.status_code in [status.HTTP_404_NOT_FOUND, status.HTTP_400_BAD_REQUEST]

    def test_null_byte_injection(self, alice_client):
        url = reverse("user-settings-security-contact-info")
        # Null byte in phone
        res_phone = alice_client.patch(url, {"phone": "+1415555\x001234"}, format="json")
        assert res_phone.status_code == status.HTTP_400_BAD_REQUEST

        # Null byte in secondary email
        res_email = alice_client.patch(url, {"secondary_email": "user\x00@example.com"}, format="json")
        assert res_email.status_code == status.HTTP_400_BAD_REQUEST

        # Null byte in change password
        pw_url = reverse("user-settings-security-change-password")
        res_pw = alice_client.post(pw_url, {"current_password": "pass\x00word", "new_password": "new\x00password"}, format="json")
        assert res_pw.status_code == status.HTTP_400_BAD_REQUEST

    def test_unicode_and_emojis(self, alice_client, user_alice):
        url = reverse("user-settings-security-contact-info")
        unicode_phone = "📞+1-415-555-🏋️‍♂️"
        res = alice_client.patch(url, {"phone": unicode_phone}, format="json")
        assert res.status_code == status.HTTP_200_OK
        user_alice.refresh_from_db()
        assert user_alice.phone == unicode_phone


# ==============================================================================
# 7. AUTHENTICATION & PERMISSIONS
# ==============================================================================

@pytest.mark.django_db
class TestSecurityAuthenticationAndPermissions:
    """Verifies that unauthenticated or invalid token requests are strictly rejected."""

    def test_unauthenticated_requests(self):
        anon = APIClient()
        endpoints = [
            ("GET", reverse("user-settings-security")),
            ("GET", reverse("user-settings-security-contact-info")),
            ("PATCH", reverse("user-settings-security-contact-info")),
            ("POST", reverse("user-settings-security-change-password")),
            ("GET", reverse("user-settings-security-2fa")),
            ("PATCH", reverse("user-settings-security-2fa")),
            ("GET", reverse("user-settings-security-devices")),
            ("DELETE", reverse("user-settings-security-device-detail", kwargs={"device_id": "dev1"})),
        ]
        for method, ep in endpoints:
            if method == "GET":
                res = anon.get(ep)
            elif method == "PATCH":
                res = anon.patch(ep, {}, format="json")
            elif method == "POST":
                res = anon.post(ep, {}, format="json")
            elif method == "DELETE":
                res = anon.delete(ep)
            assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Expected 401 for {method} {ep}"

    def test_malformed_and_tampered_tokens(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer invalid.token.payload")
        res = client.get(reverse("user-settings-security"))
        assert res.status_code == status.HTTP_401_UNAUTHORIZED


# ==============================================================================
# 8. IDOR & OBJECT-LEVEL AUTHORIZATION
# ==============================================================================

@pytest.mark.django_db
class TestSecurityIDORAndIsolation:
    """Verifies cross-tenant and cross-user isolation: User A cannot affect User B."""

    def test_user_a_cannot_delete_user_b_device(self, alice_client, bob_client, user_bob):
        # Bob creates a device and key
        dev_bob = UserDevice.objects.create(
            user=user_bob,
            device_id="bob_secret_device_1",
            device_name="Bob's iPad",
        )
        UserDeviceKey.objects.create(
            user=user_bob,
            device_id="bob_secret_device_1",
            identity_key="bob_key",
            signed_prekey="bob_prekey",
        )

        # Alice attempts to delete Bob's device
        url = reverse("user-settings-security-device-detail", kwargs={"device_id": "bob_secret_device_1"})
        res = alice_client.delete(url)
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # Bob's device and key must remain completely intact
        assert UserDevice.objects.filter(user=user_bob, device_id="bob_secret_device_1").exists()
        assert UserDeviceKey.objects.filter(user=user_bob, device_id="bob_secret_device_1").exists()

    def test_user_a_cannot_verify_2fa_for_user_b(self, user_alice, user_bob):
        client = APIClient()

        # Generate 2FA OTP for Alice
        user_alice.settings.two_factor_enabled = True
        user_alice.settings.save()
        with patch("apps.users.services.security_services.generate_six_digit_otp", return_value="777888"):
            client.post(reverse("login"), {"email": user_alice.email, "password": "SecurePassword123!"})

        # Bob attempts to use Alice's OTP with Bob's email
        res_bob = client.post(
            reverse("verify-2fa"),
            {"email": user_bob.email, "otp_code": "777888"},
            format="json",
        )
        assert res_bob.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 9. BUSINESS LOGIC & INVALID STATE TRANSITIONS
# ==============================================================================

@pytest.mark.django_db
class TestSecurityBusinessLogicAndStateTransitions:
    """Tests 2FA OTP lifecycle, max device limits, and account lifecycle transitions."""

    def test_2fa_otp_cannot_be_reused(self, user_alice):
        client = APIClient()
        user_alice.settings.two_factor_enabled = True
        user_alice.settings.save()

        with patch("apps.users.services.security_services.generate_six_digit_otp", return_value="555666"):
            client.post(reverse("login"), {"email": user_alice.email, "password": "SecurePassword123!"})

        # First verification succeeds
        res1 = client.post(reverse("verify-2fa"), {"email": user_alice.email, "otp_code": "555666"}, format="json")
        assert res1.status_code == status.HTTP_200_OK

        # Second verification with same code fails immediately
        res2 = client.post(reverse("verify-2fa"), {"email": user_alice.email, "otp_code": "555666"}, format="json")
        assert res2.status_code == status.HTTP_400_BAD_REQUEST

    def test_expired_2fa_otp_is_rejected(self, user_alice):
        client = APIClient()
        user_alice.settings.two_factor_enabled = True
        user_alice.settings.save()

        with patch("apps.users.services.security_services.generate_six_digit_otp", return_value="999111"):
            client.post(reverse("login"), {"email": user_alice.email, "password": "SecurePassword123!"})

        # Expire OTP
        otp_record = OTPVerification.objects.filter(email=user_alice.email, purpose=OTPVerification.Purpose.TWO_FACTOR).first()
        otp_record.expires_at = timezone.now() - timedelta(minutes=1)
        otp_record.save()

        res = client.post(reverse("verify-2fa"), {"email": user_alice.email, "otp_code": "999111"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_rapid_10_devices_login_enforces_strict_max_5(self, user_alice):
        client = APIClient()

        # Log in 10 devices in rapid succession
        for i in range(1, 11):
            cache.clear()
            res = client.post(
                reverse("login"),
                {
                    "email": user_alice.email,
                    "password": "SecurePassword123!",
                    "device_id": f"rapid_dev_{i}",
                    "device_name": f"Device {i}",
                },
                format="json",
            )
            assert res.status_code == status.HTTP_200_OK

        # Verify active devices count is strictly 5
        devices = UserDevice.objects.filter(user=user_alice)
        assert devices.count() == 5

        # Old devices (1 to 5) must be evicted, and recent devices (6 to 10) must be present
        device_ids = set(devices.values_list("device_id", flat=True))
        for old_i in range(1, 6):
            assert f"rapid_dev_{old_i}" not in device_ids
        for new_i in range(6, 11):
            assert f"rapid_dev_{new_i}" in device_ids

    def test_deactivate_and_login_with_wrong_password_does_not_reactivate(self, alice_client, user_alice):
        # Deactivate
        alice_client.post(reverse("user-settings-access-control"), {"action": "deactivate"}, format="json")
        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.DEACTIVATED

        # Login with wrong password
        client = APIClient()
        res = client.post(reverse("login"), {"email": user_alice.email, "password": "WrongPassword!"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.DEACTIVATED
        assert user_alice.settings.is_deactivated is True

    def test_delete_and_login_with_wrong_password_does_not_restore(self, alice_client, user_alice):
        # Delete
        alice_client.post(
            reverse("user-settings-access-control"),
            {"action": "delete", "password": "SecurePassword123!", "confirmation": "delete"},
            format="json",
        )
        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.DELETED

        # Login with wrong password
        client = APIClient()
        res = client.post(reverse("login"), {"email": user_alice.email, "password": "WrongPassword!"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.DELETED
        assert user_alice.settings.is_deleted is True


# ==============================================================================
# 10. HTTP METHOD VALIDATION
# ==============================================================================

@pytest.mark.django_db
class TestSecurityHTTPMethodValidation:
    """Tests unsupported HTTP methods across all Login and Security endpoints."""

    def test_unsupported_http_methods(self, alice_client):
        # Overview endpoint is GET only
        assert alice_client.post(reverse("user-settings-security"), {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert alice_client.put(reverse("user-settings-security"), {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert alice_client.delete(reverse("user-settings-security")).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # Change password is POST only
        assert alice_client.get(reverse("user-settings-security-change-password")).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert alice_client.put(reverse("user-settings-security-change-password"), {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert alice_client.delete(reverse("user-settings-security-change-password")).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # Devices list is GET only
        assert alice_client.post(reverse("user-settings-security-devices"), {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert alice_client.put(reverse("user-settings-security-devices"), {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert alice_client.delete(reverse("user-settings-security-devices")).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # Device detail is DELETE only
        dev_url = reverse("user-settings-security-device-detail", kwargs={"device_id": "test_dev"})
        assert alice_client.get(dev_url).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert alice_client.post(dev_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert alice_client.put(dev_url, {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# ==============================================================================
# 11. RESPONSE ENVELOPE VALIDATION
# ==============================================================================

@pytest.mark.django_db
class TestSecurityResponseEnvelope:
    """Verifies that all error responses follow the standard JSON envelope with ZERO 500 errors."""

    def test_error_envelope_structure(self, alice_client):
        url = reverse("user-settings-security-contact-info")
        res = alice_client.patch(url, {"primary_email": "bad@example.com"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "code" in res.data
        assert "message" in res.data
        assert "details" in res.data
        assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

