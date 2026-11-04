import pytest
from rest_framework.test import APIClient
from rest_framework import status
from django.urls import reverse
from django.core.cache import cache
from apps.users.models import User, OTPVerification
from apps.gyms.models import Gym
from apps.authentication.services import issue_context_token, authenticate_user
from common.enums import TokenContextType


@pytest.fixture(autouse=True)
def clear_redis_cache():
    """Ensure a clean cache between tests to avoid bleed-over of rate limit / revocation keys."""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_issue1_logout_revokes_access_and_refresh_tokens():
    """
    Issue 1 Verification:
    POST /api/v1/auth/logout/ must invalidate both the access token and refresh token immediately.
    Subsequent protected requests and logout replays must return 401 Unauthorized.
    """
    user = User.objects.create_user(
        email="logout.victim@manygym.com",
        password="SecurePassword2026!",
        first_name="Logout",
        last_name="Tester",
        is_verified=True,
    )

    client = APIClient()
    login_res = client.post(reverse("login"), {
        "email": "logout.victim@manygym.com",
        "password": "SecurePassword2026!",
    })
    assert login_res.status_code == status.HTTP_200_OK
    access_token = login_res.data["tokens"]["access"]
    refresh_token = login_res.data["tokens"]["refresh"]

    # 1. Verify access token works before logout
    auth_client = APIClient()
    auth_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    me_res = auth_client.get(reverse("me"))
    assert me_res.status_code == status.HTTP_200_OK

    # 2. Perform Logout
    logout_res = auth_client.post(
        reverse("logout"),
        {"refresh": refresh_token},
        format="json",
    )
    assert logout_res.status_code == status.HTTP_200_OK
    assert logout_res.data["message"] == "Logged out successfully."

    # 3. Same access token immediately after logout MUST return 401 Unauthorized
    me_after_logout = auth_client.get(reverse("me"))
    assert me_after_logout.status_code == status.HTTP_401_UNAUTHORIZED
    assert "revoked" in str(me_after_logout.data).lower()

    # 4. Replay of logout with the revoked access token MUST return 401 Unauthorized
    replay_res = auth_client.post(
        reverse("logout"),
        {"refresh": refresh_token},
        format="json",
    )
    assert replay_res.status_code == status.HTTP_401_UNAUTHORIZED

    # 5. Revoked refresh token cannot be refreshed
    refresh_res = client.post(
        reverse("token-refresh"),
        {"refresh": refresh_token},
        format="json",
    )
    assert refresh_res.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_issue2_token_refresh_endpoint_and_context_preservation():
    """
    Issue 2 Verification:
    POST /api/v1/auth/refresh/ must accept a valid refresh token, rotate it,
    preserve contextual claims (personal vs gym), and return fresh tokens.
    """
    from apps.access_control.services import seed_default_permissions_and_roles
    seed_default_permissions_and_roles()

    owner = User.objects.create_user(
        email="refresh.owner@manygym.com",
        password="SecurePassword2026!",
        first_name="Gym",
        last_name="Owner",
        is_verified=True,
    )
    gym = Gym.objects.create(name="Titan Gym", owner_user=owner)

    client = APIClient()

    # 1. Test Refresh with Personal Context
    login_res = client.post(reverse("login"), {
        "email": "refresh.owner@manygym.com",
        "password": "SecurePassword2026!",
    })
    assert login_res.status_code == status.HTTP_200_OK
    p_refresh = login_res.data["tokens"]["refresh"]

    refresh_res = client.post(reverse("token-refresh"), {"refresh": p_refresh}, format="json")
    assert refresh_res.status_code == status.HTTP_200_OK
    assert "tokens" in refresh_res.data
    new_access = refresh_res.data["tokens"]["access"]
    new_refresh = refresh_res.data["tokens"]["refresh"]
    assert refresh_res.data["tokens"]["context_type"] == "personal"

    # New access token is functional
    auth_client = APIClient()
    auth_client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_access}")
    me_res = auth_client.get(reverse("me"))
    assert me_res.status_code == status.HTTP_200_OK

    # Old refresh token has been rotated/revoked
    reused_res = client.post(reverse("token-refresh"), {"refresh": p_refresh}, format="json")
    assert reused_res.status_code == status.HTTP_401_UNAUTHORIZED

    # 2. Test Refresh with Gym Context
    switch_res = auth_client.post(
        reverse("switch-context"),
        {"context_type": "gym", "gym_id": str(gym.id)},
        format="json",
    )
    assert switch_res.status_code == status.HTTP_200_OK
    gym_refresh = switch_res.data["tokens"]["refresh"]
    assert switch_res.data["tokens"]["context_type"] == "gym"

    refresh_gym_res = client.post(
        reverse("token-refresh-alias"),
        {"refresh": gym_refresh},
        format="json",
    )
    assert refresh_gym_res.status_code == status.HTTP_200_OK
    assert refresh_gym_res.data["tokens"]["context_type"] == "gym"
    assert refresh_gym_res.data["tokens"]["gym_id"] == str(gym.id)
    assert len(refresh_gym_res.data["tokens"]["scopes"]) > 0

    # 3. Test direct alias endpoint /api/v1/token/refresh/
    direct_refresh_res = client.post(
        reverse("token-refresh-direct"),
        {"refresh": new_refresh},
        format="json",
    )
    assert direct_refresh_res.status_code == status.HTTP_200_OK
    assert "tokens" in direct_refresh_res.data


@pytest.mark.django_db
def test_issue3_login_lockout_after_consecutive_failed_attempts():
    """
    Issue 3 Verification (Part A):
    12 consecutive wrong passwords for the same account must trigger 429 Too Many Requests
    with a Retry-After header and THROTTLED error envelope.
    """
    User.objects.create_user(
        email="lockout.target@manygym.com",
        password="CorrectPassword123!",
        first_name="Lockout",
        last_name="Target",
        is_verified=True,
    )

    client = APIClient()
    status_codes = []
    retry_after_seen = False

    for _ in range(12):
        res = client.post(
            reverse("login"),
            {"email": "lockout.target@manygym.com", "password": "WrongPassword!"},
            format="json",
        )
        status_codes.append(res.status_code)
        if res.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            assert "Retry-After" in res.headers or "retry-after" in res.headers
            assert res.data["code"] == "THROTTLED"
            retry_after_seen = True

    # First attempts return 400 Bad Request
    assert status_codes[0] == status.HTTP_400_BAD_REQUEST
    # Later attempts MUST be throttled with 429
    assert status.HTTP_429_TOO_MANY_REQUESTS in status_codes
    assert retry_after_seen is True


@pytest.mark.django_db
def test_issue3_otp_brute_force_lockout():
    """
    Issue 3 Verification (Part B):
    Entering 5 wrong OTPs must permanently invalidate the OTP code.
    Any subsequent attempt (even if correct) must be rejected.
    """
    client = APIClient()
    reg_payload = {
        "email": "otp.target@manygym.com",
        "password": "Password123!",
        "first_name": "OTP",
        "last_name": "Target",
    }
    reg_res = client.post(reverse("register"), reg_payload)
    assert reg_res.status_code == status.HTTP_201_CREATED

    otp_record = OTPVerification.objects.filter(
        email="otp.target@manygym.com",
        purpose=OTPVerification.Purpose.SIGNUP_VERIFICATION,
        is_used=False,
    ).first()
    assert otp_record is not None
    real_otp = otp_record.otp_code

    # Submit 5 wrong OTP attempts
    for attempt in range(5):
        bad_res = client.post(reverse("verify-signup-otp"), {
            "email": "otp.target@manygym.com",
            "otp_code": f"99999{attempt}",
        })
        assert bad_res.status_code == status.HTTP_400_BAD_REQUEST

    # The 6th attempt with the REAL, CORRECT OTP must be REJECTED because it was invalidated
    correct_attempt_res = client.post(reverse("verify-signup-otp"), {
        "email": "otp.target@manygym.com",
        "otp_code": real_otp,
    })
    assert correct_attempt_res.status_code == status.HTTP_400_BAD_REQUEST
    assert "invalid" in str(correct_attempt_res.data).lower() or "expired" in str(correct_attempt_res.data).lower()

    # User remains unverified
    user = User.objects.get(email="otp.target@manygym.com")
    assert user.is_verified is False
