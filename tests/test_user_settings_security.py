import uuid
from datetime import timedelta
import pytest
from unittest.mock import patch
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
def test_user(db):
    user = User.objects.create_user(
        email="security.user@example.com",
        password="SecurePassword123!",
        first_name="Security",
        last_name="Tester",
        phone="+14155551234",
        secondary_email="backup.user@example.com",
        is_verified=True,
    )
    user.get_settings()
    return user


@pytest.fixture
def auth_client(test_user):
    client = APIClient()
    from apps.authentication.services import issue_context_token
    tokens = issue_context_token(test_user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


# ==============================================================================
# 1. CONTACT INFO TESTS
# ==============================================================================

@pytest.mark.django_db
class TestContactInfo:
    def test_get_contact_info(self, auth_client, test_user):
        url = reverse("user-settings-security-contact-info")
        res = auth_client.get(url)
        assert res.status_code == status.HTTP_200_OK
        assert res.data["primary_email"] == test_user.email
        assert res.data["secondary_email"] == test_user.secondary_email
        assert res.data["phone"] == test_user.phone

    def test_cannot_update_or_delete_primary_email(self, auth_client, test_user):
        url = reverse("user-settings-security-contact-info")
        # Attempt to modify primary email via 'primary_email'
        res1 = auth_client.patch(url, {"primary_email": "hacked@example.com"}, format="json")
        assert res1.status_code == status.HTTP_400_BAD_REQUEST
        assert "primary email cannot be updated or deleted" in str(res1.data).lower()

        # Attempt to modify primary email via 'email'
        res2 = auth_client.patch(url, {"email": "hacked@example.com"}, format="json")
        assert res2.status_code == status.HTTP_400_BAD_REQUEST
        assert "primary email cannot be updated or deleted" in str(res2.data).lower()

        test_user.refresh_from_db()
        assert test_user.email == "security.user@example.com"

    def test_update_secondary_email_and_phone(self, auth_client, test_user):
        url = reverse("user-settings-security-contact-info")
        res = auth_client.patch(
            url,
            {
                "secondary_email": "new.secondary@example.com",
                "phone": "+14155559999",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["secondary_email"] == "new.secondary@example.com"
        assert res.data["phone"] == "+14155559999"
        assert res.data["primary_email"] == test_user.email

        test_user.refresh_from_db()
        assert test_user.secondary_email == "new.secondary@example.com"
        assert test_user.phone == "+14155559999"

    def test_clear_secondary_email_and_phone(self, auth_client, test_user):
        url = reverse("user-settings-security-contact-info")
        res = auth_client.patch(
            url,
            {
                "secondary_email": None,
                "phone": None,
            },
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["secondary_email"] is None
        assert res.data["phone"] is None

        test_user.refresh_from_db()
        assert test_user.secondary_email is None
        assert test_user.phone is None

    def test_secondary_email_cannot_match_primary_email(self, auth_client, test_user):
        url = reverse("user-settings-security-contact-info")
        res = auth_client.patch(
            url,
            {"secondary_email": test_user.email},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "cannot be the same as primary email" in str(res.data).lower()


# ==============================================================================
# 2. CHANGE PASSWORD TESTS
# ==============================================================================

@pytest.mark.django_db
class TestSecurityChangePassword:
    def test_change_password_success(self, auth_client, test_user):
        url = reverse("user-settings-security-change-password")
        res = auth_client.post(
            url,
            {
                "current_password": "SecurePassword123!",
                "new_password": "BrandNewSecurePassword2026!",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        assert "successfully changed" in str(res.data).lower()

        test_user.refresh_from_db()
        assert test_user.check_password("BrandNewSecurePassword2026!")

    def test_change_password_wrong_current_password(self, auth_client, test_user):
        url = reverse("user-settings-security-change-password")
        res = auth_client.post(
            url,
            {
                "current_password": "WrongPassword!",
                "new_password": "BrandNewSecurePassword2026!",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 3. TWO-FACTOR AUTHENTICATION (2FA) TESTS
# ==============================================================================

@pytest.mark.django_db
class TestTwoFactorAuthentication:
    def test_2fa_toggle_on_off(self, auth_client, test_user):
        url = reverse("user-settings-security-2fa")

        # Check default OFF
        res_get = auth_client.get(url)
        assert res_get.status_code == status.HTTP_200_OK
        assert res_get.data["two_factor_enabled"] is False

        # Toggle ON
        res_on = auth_client.patch(url, {"two_factor_enabled": True}, format="json")
        assert res_on.status_code == status.HTTP_200_OK
        assert res_on.data["two_factor_enabled"] is True

        test_user.refresh_from_db()
        assert test_user.settings.two_factor_enabled is True

        # Toggle OFF
        res_off = auth_client.patch(url, {"two_factor_enabled": False}, format="json")
        assert res_off.status_code == status.HTTP_200_OK
        assert res_off.data["two_factor_enabled"] is False

    def test_login_flow_with_2fa_and_verification(self, test_user):
        test_user.settings.two_factor_enabled = True
        test_user.settings.save()

        anon_client = APIClient()

        with patch("apps.users.services.security_services.generate_six_digit_otp", return_value="654321"):
            login_res = anon_client.post(
                reverse("login"),
                {"email": test_user.email, "password": "SecurePassword123!"},
                format="json",
            )
            assert login_res.status_code == status.HTTP_200_OK
            assert login_res.data["two_factor_required"] is True
            assert login_res.data["channel"] == "primary_email"
            assert login_res.data["email"] == test_user.email

            # Verify with wrong OTP
            verify_fail = anon_client.post(
                reverse("verify-2fa"),
                {"email": test_user.email, "otp_code": "000000"},
                format="json",
            )
            assert verify_fail.status_code == status.HTTP_400_BAD_REQUEST

            # Verify with correct OTP
            verify_success = anon_client.post(
                reverse("verify-2fa"),
                {
                    "email": test_user.email,
                    "otp_code": "654321",
                    "device_id": "phone_device_1",
                    "device_name": "iPhone 15",
                },
                format="json",
            )
            assert verify_success.status_code == status.HTTP_200_OK
            assert "tokens" in verify_success.data
            assert verify_success.data["user"]["email"] == test_user.email

    def test_2fa_fallback_sequence_primary_fails_to_secondary(self, test_user):
        test_user.settings.two_factor_enabled = True
        test_user.settings.save()

        anon_client = APIClient()

        # Mock primary email send failure: when called for primary email, raise Exception
        original_send_mail = __import__("apps.users.services.security_services", fromlist=["send_mail"]).send_mail

        def mock_send_mail(*args, **kwargs):
            recipient_list = kwargs.get("recipient_list", [])
            if test_user.email in recipient_list:
                raise Exception("SMTP connection failure on primary host")
            return original_send_mail(*args, **kwargs)

        with patch("apps.users.services.security_services.send_mail", side_effect=mock_send_mail):
            res = anon_client.post(
                reverse("login"),
                {"email": test_user.email, "password": "SecurePassword123!"},
                format="json",
            )
            assert res.status_code == status.HTTP_200_OK
            assert res.data["two_factor_required"] is True
            assert res.data["channel"] == "secondary_email"

    def test_2fa_fallback_sequence_emails_fail_to_phone_sms(self, test_user):
        test_user.settings.two_factor_enabled = True
        test_user.settings.save()

        anon_client = APIClient()

        # Mock both primary and secondary emails failing
        def mock_send_mail(*args, **kwargs):
            raise Exception("SMTP network unreachable")

        with patch("apps.users.services.security_services.send_mail", side_effect=mock_send_mail):
            res = anon_client.post(
                reverse("login"),
                {"email": test_user.email, "password": "SecurePassword123!"},
                format="json",
            )
            assert res.status_code == status.HTTP_200_OK
            assert res.data["two_factor_required"] is True
            assert res.data["channel"] == "phone_sms"

    def test_resend_2fa_otp_success(self, test_user):
        anon_client = APIClient()
        res = anon_client.post(
            reverse("resend-2fa"),
            {"email": test_user.email, "channel": "secondary_email"},
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["channel"] == "secondary_email"
        assert res.data["email"] == test_user.email


# ==============================================================================
# 4. LOGGED IN DEVICES (MAX 5) TESTS
# ==============================================================================

@pytest.mark.django_db
class TestLoggedInDevices:
    def test_max_5_devices_and_eviction(self, test_user):
        anon_client = APIClient()

        # Log in 5 distinct devices
        for i in range(1, 6):
            cache.clear()
            res = anon_client.post(
                reverse("login"),
                {
                    "email": test_user.email,
                    "password": "SecurePassword123!",
                    "device_id": f"device_{i}",
                    "device_name": f"Device {i}",
                },
                format="json",
            )
            assert res.status_code == status.HTTP_200_OK

        assert UserDevice.objects.filter(user=test_user).count() == 5

        # Also register a device key for device_1 in messaging
        UserDeviceKey.objects.create(
            user=test_user,
            device_id="device_1",
            device_name="Device 1",
            identity_key="id_key_1",
            signed_prekey="signed_prekey_1",
        )
        assert UserDeviceKey.objects.filter(user=test_user, device_id="device_1").exists()

        # Log in 6th device: device_1 (the oldest) should be evicted and its keys cleaned!
        cache.clear()
        res6 = anon_client.post(
            reverse("login"),
            {
                "email": test_user.email,
                "password": "SecurePassword123!",
                "device_id": "device_6",
                "device_name": "Device 6",
            },
            format="json",
        )
        assert res6.status_code == status.HTTP_200_OK

        # Total devices remains max 5
        assert UserDevice.objects.filter(user=test_user).count() == 5
        # device_1 is evicted
        assert not UserDevice.objects.filter(user=test_user, device_id="device_1").exists()
        # device_1 key is cleaned!
        assert not UserDeviceKey.objects.filter(user=test_user, device_id="device_1").exists()
        # device_6 is present
        assert UserDevice.objects.filter(user=test_user, device_id="device_6").exists()

    def test_delete_device_cleans_key_and_tokens(self, auth_client, test_user):
        # Register device in UserDevice
        UserDevice.objects.create(
            user=test_user,
            device_id="laptop_mac_1",
            device_name="MacBook Pro",
        )
        # Register corresponding E2EE key
        UserDeviceKey.objects.create(
            user=test_user,
            device_id="laptop_mac_1",
            device_name="MacBook Pro",
            identity_key="mac_identity_key",
            signed_prekey="mac_signed_prekey",
        )
        # Register token for this device
        AuthToken.objects.create(
            user=test_user,
            token_hash="fake_hash_123",
            device_id="laptop_mac_1",
            expires_at=timezone.now() + timedelta(days=1),
        )

        assert UserDeviceKey.objects.filter(user=test_user, device_id="laptop_mac_1").exists()
        assert AuthToken.objects.filter(user=test_user, device_id="laptop_mac_1").exists()

        # Delete device via endpoint
        url = reverse("user-settings-security-device-detail", kwargs={"device_id": "laptop_mac_1"})
        del_res = auth_client.delete(url)
        assert del_res.status_code == status.HTTP_200_OK
        assert "cleaned" in str(del_res.data).lower()

        # Device record deleted
        assert not UserDevice.objects.filter(user=test_user, device_id="laptop_mac_1").exists()
        # Key cleaned
        assert not UserDeviceKey.objects.filter(user=test_user, device_id="laptop_mac_1").exists()
        # Tokens revoked
        assert not AuthToken.objects.filter(user=test_user, device_id="laptop_mac_1").exists()


# ==============================================================================
# 5. ACCOUNT DEACTIVATE AND DELETE LIFECYCLE TESTS
# ==============================================================================

@pytest.mark.django_db
class TestAccountLifecycleNewRules:
    def test_deactivate_and_login_again_removes_deactivate_status(self, auth_client, test_user):
        # Deactivate account
        ac_url = reverse("user-settings-access-control")
        deact_res = auth_client.post(ac_url, {"action": "deactivate"}, format="json")
        assert deact_res.status_code == status.HTTP_200_OK

        test_user.refresh_from_db()
        assert test_user.status == UserStatus.DEACTIVATED
        assert test_user.settings.is_deactivated is True

        # Login again: deactivate status is automatically removed
        anon_client = APIClient()
        login_res = anon_client.post(
            reverse("login"),
            {"email": test_user.email, "password": "SecurePassword123!"},
            format="json",
        )
        assert login_res.status_code == status.HTTP_200_OK
        assert "tokens" in login_res.data

        test_user.refresh_from_db()
        assert test_user.status == UserStatus.ACTIVE
        assert test_user.is_active is True
        assert test_user.settings.is_deactivated is False

    def test_delete_and_login_within_24_hours_removes_delete_request(self, auth_client, test_user):
        ac_url = reverse("user-settings-access-control")
        del_res = auth_client.post(
            ac_url,
            {"action": "delete", "password": "SecurePassword123!", "confirmation": "delete"},
            format="json",
        )
        assert del_res.status_code == status.HTTP_200_OK

        test_user.refresh_from_db()
        assert test_user.status == UserStatus.DELETED
        assert test_user.settings.is_deleted is True

        # Login within 24 hours: delete request is automatically removed
        anon_client = APIClient()
        login_res = anon_client.post(
            reverse("login"),
            {"email": test_user.email, "password": "SecurePassword123!"},
            format="json",
        )
        assert login_res.status_code == status.HTTP_200_OK
        assert "tokens" in login_res.data

        test_user.refresh_from_db()
        assert test_user.status == UserStatus.ACTIVE
        assert test_user.is_active is True
        assert test_user.settings.is_deleted is False

    def test_delete_and_login_after_24_hours_is_rejected(self, test_user):
        test_user.settings.soft_delete()
        test_user.settings.deleted_at = timezone.now() - timedelta(hours=25)
        test_user.settings.save()
        test_user.status = UserStatus.DELETED
        test_user.is_active = False
        test_user.save()

        anon_client = APIClient()
        login_res = anon_client.post(
            reverse("login"),
            {"email": test_user.email, "password": "SecurePassword123!"},
            format="json",
        )
        assert login_res.status_code == status.HTTP_400_BAD_REQUEST
        assert "permanently deleted" in str(login_res.data).lower()
