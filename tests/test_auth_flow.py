import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from apps.users.models import User, OTPVerification


@pytest.mark.django_db
def test_full_user_registration_and_otp_verification():
    client = APIClient()

    # 1. Register Account
    reg_payload = {
        "email": "trainer.john@manygym.com",
        "password": "Password123!",
        "first_name": "John",
        "last_name": "Doe",
        "phone": "+1234567890",
    }
    reg_res = client.post(reverse("register"), reg_payload)
    assert reg_res.status_code == 201
    assert "verification code has been dispatched" in reg_res.data["message"]

    user = User.objects.get(email="trainer.john@manygym.com")
    assert user.is_verified is False

    # Check OTP record was created
    otp_record = OTPVerification.objects.filter(
        email="trainer.john@manygym.com",
        purpose=OTPVerification.Purpose.SIGNUP_VERIFICATION,
        is_used=False,
    ).first()
    assert otp_record is not None
    otp_code = otp_record.otp_code

    # 2. Try to login before verifying -> Should be rejected
    login_res = client.post(reverse("login"), {
        "email": "trainer.john@manygym.com",
        "password": "Password123!",
    })
    assert login_res.status_code == 400
    assert "not been verified" in login_res.data["message"]

    # 3. Verify with wrong OTP -> Rejected
    bad_verify_res = client.post(reverse("verify-signup-otp"), {
        "email": "trainer.john@manygym.com",
        "otp_code": "000000",
    })
    assert bad_verify_res.status_code == 400

    # 4. Verify with correct OTP -> Succeeds and issues tokens
    verify_res = client.post(reverse("verify-signup-otp"), {
        "email": "trainer.john@manygym.com",
        "otp_code": otp_code,
    })
    assert verify_res.status_code == 200
    assert "tokens" in verify_res.data
    assert verify_res.data["tokens"]["context_type"] == "personal"

    user.refresh_from_db()
    assert user.is_verified is True

    # 5. Login after verification -> Succeeds
    login_success_res = client.post(reverse("login"), {
        "email": "trainer.john@manygym.com",
        "password": "Password123!",
    })
    assert login_success_res.status_code == 200
    access_token = login_success_res.data["tokens"]["access"]

    # 6. Authenticated Profile View (GET /me/)
    auth_client = APIClient()
    auth_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    me_res = auth_client.get(reverse("me"))
    assert me_res.status_code == 200
    assert me_res.data["user"]["email"] == "trainer.john@manygym.com"

    # 7. Update Profile (PATCH /me/)
    update_res = auth_client.patch(reverse("me"), {
        "city": "London",
        "country": "United Kingdom",
        "sex": "male",
    })
    assert update_res.status_code == 200
    assert update_res.data["user"]["profile"]["city"] == "London"

    # 8. Change Password
    change_res = auth_client.post(reverse("change-password"), {
        "current_password": "Password123!",
        "new_password": "NewSecretPassword2026!",
    })
    assert change_res.status_code == 200

    # Check login with new password
    new_login = client.post(reverse("login"), {
        "email": "trainer.john@manygym.com",
        "password": "NewSecretPassword2026!",
    })
    assert new_login.status_code == 200


@pytest.mark.django_db
def test_forgot_password_and_reset_flow():
    client = APIClient()

    # Create an active user
    user = User.objects.create_user(
        email="reset.user@manygym.com",
        password="InitialPassword123!",
        first_name="Reset",
        last_name="Tester",
        is_verified=True,
    )

    # 1. Request Password Reset
    forgot_res = client.post(reverse("forgot-password"), {
        "email": "reset.user@manygym.com",
    })
    assert forgot_res.status_code == 200

    # Retrieve reset OTP
    otp_record = OTPVerification.objects.filter(
        email="reset.user@manygym.com",
        purpose=OTPVerification.Purpose.PASSWORD_RESET,
        is_used=False,
    ).first()
    assert otp_record is not None
    reset_otp = otp_record.otp_code

    # 2. Verify Reset OTP
    verify_otp_res = client.post(reverse("verify-reset-otp"), {
        "email": "reset.user@manygym.com",
        "otp_code": reset_otp,
    })
    assert verify_otp_res.status_code == 200

    # 3. Reset Password
    reset_res = client.post(reverse("reset-password"), {
        "email": "reset.user@manygym.com",
        "otp_code": reset_otp,
        "new_password": "BrandNewPassword2026!",
    })
    assert reset_res.status_code == 200

    # 4. Verify login with reset password
    login_res = client.post(reverse("login"), {
        "email": "reset.user@manygym.com",
        "password": "BrandNewPassword2026!",
    })
    assert login_res.status_code == 200


@pytest.mark.django_db
def test_otp_is_hashed_in_database(client):
    """
    Verifies that OTP verification codes are cryptographically hashed before being stored in PostgreSQL,
    and no plaintext OTP is persisted in database columns.
    """
    from django.db import connection
    from common.security import hash_otp

    reg_payload = {
        "email": "hashed.otp.user@manygym.com",
        "password": "SecurePassword123!",
        "first_name": "Crypto",
        "last_name": "Tester",
    }
    res = client.post(reverse("register"), reg_payload)
    assert res.status_code == 201

    # Raw SQL query to directly inspect the database row in PostgreSQL
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT otp_code FROM otp_verifications WHERE email = %s AND is_used = false",
            ["hashed.otp.user@manygym.com"],
        )
        row = cursor.fetchone()
        assert row is not None
        db_stored_otp = row[0]

    # Verify that what is in the DB is a 64-character hex hash, NOT a 6-digit plain OTP
    assert len(db_stored_otp) == 64
    assert not db_stored_otp.isdigit()
    assert all(c in "0123456789abcdef" for c in db_stored_otp.lower())

    # Verify descriptor provides the raw code in memory and matches hash
    otp_record = OTPVerification.objects.filter(email="hashed.otp.user@manygym.com").first()
    raw_code = otp_record.otp_code
    assert len(raw_code) == 6
    assert raw_code.isdigit()
    assert hash_otp("hashed.otp.user@manygym.com", raw_code) == db_stored_otp
    assert otp_record.check_otp(raw_code) is True
    assert otp_record.check_otp("000000") is False

    # Verify verify_signup_otp succeeds with the raw code
    verify_res = client.post(reverse("verify-signup-otp"), {
        "email": "hashed.otp.user@manygym.com",
        "otp_code": raw_code,
    })
    assert verify_res.status_code == 200
