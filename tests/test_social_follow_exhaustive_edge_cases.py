import uuid
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile, UserFollow
from apps.gyms.models import Gym, GymSetting, GymFollow, GymBlockedUser
from apps.gyms.services import create_gym, block_user_for_gym
from apps.members.models import Member
from apps.members.services import accept_member_invitation
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    AudienceFollowingVisibilityEnum,
    StaffStatus,
)
from apps.access_control.models import GymStaffAssignment, Role


@pytest.fixture
def user_alice(db):
    user = User.objects.create_user(
        email="alice_edge@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Edge",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def user_bob(db):
    user = User.objects.create_user(
        email="bob_edge@example.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Edge",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def user_private(db):
    user = User.objects.create_user(
        email="private_edge@example.com",
        password="SecurePassword123!",
        first_name="Private",
        last_name="User",
        is_verified=True,
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.is_private = True
    profile.save()
    return user


@pytest.fixture
def user_inactive(db):
    user = User.objects.create_user(
        email="inactive_edge@example.com",
        password="SecurePassword123!",
        first_name="Inactive",
        last_name="User",
        is_verified=True,
    )
    user.is_active = False
    user.save()
    return user


@pytest.fixture
def client_alice(user_alice):
    token = issue_context_token(user=user_alice, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def client_bob(user_bob):
    token = issue_context_token(user=user_bob, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def gym_instance(user_alice):
    gym = create_gym(
        owner_user=user_alice,
        name="Edge Test Gym",
        short_description="Top tier strength and conditioning fitness club with luxury sauna and modern facilities." * 2,
    )
    return gym


# =====================================================================
# 1. Data Type Mismatches (Type Juggling)
# =====================================================================

@pytest.mark.django_db
class TestDataTypeMismatches:
    """Verifies that invalid data types in request body or params are rejected with 400 Bad Request."""

    @pytest.mark.parametrize(
        "invalid_target_id",
        [
            12345,
            3.14159,
            True,
            False,
            ["not", "a", "uuid"],
            {"nested": "id"},
            None,
        ],
    )
    def test_target_id_type_mismatches_post(self, client_alice, invalid_target_id):
        payload = {"target_id": invalid_target_id}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize(
        "invalid_action",
        [
            12345,
            True,
            ["follow"],
            {"action": "follow"},
            "invalid_action_name",
            "",
        ],
    )
    def test_action_type_mismatches_post(self, client_alice, user_bob, invalid_action):
        payload = {
            "target_id": str(user_bob.id),
            "action": invalid_action,
        }
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize(
        "invalid_target_type",
        [
            12345,
            True,
            ["gym"],
            {"type": "gym"},
            "spaceship",
            "admin",
        ],
    )
    def test_target_type_type_mismatches_post(self, client_alice, user_bob, invalid_target_type):
        payload = {
            "target_id": str(user_bob.id),
            "target_type": invalid_target_type,
        }
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# =====================================================================
# 2. Boundary & Length Edge Cases
# =====================================================================

@pytest.mark.django_db
class TestBoundaryAndLengthEdgeCases:
    """Verifies empty strings, whitespace, length limits, and boundaries."""

    @pytest.mark.parametrize(
        "boundary_id",
        [
            "",
            " ",
            "   ",
            "\t\n\r",
            "a" * 35,  # 1 char short of UUID (36 chars)
            "a" * 37,  # 1 char too long
            "a" * 1000,
            "a" * 10000,
        ],
    )
    def test_target_id_length_boundaries_post(self, client_alice, boundary_id):
        payload = {"target_id": boundary_id}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_whitespace_padded_uuid(self, client_alice, user_bob):
        # Leading/trailing whitespace around valid UUID should be parsed or gracefully handled
        payload = {"target_id": f"  {user_bob.id}  "}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        # Either DRF strips it and succeeds (201) or returns 400 validation error (never 500)
        assert response.status_code in (status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST)
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# =====================================================================
# 3. Missing, Extra & Malformed Fields
# =====================================================================

@pytest.mark.django_db
class TestMissingAndExtraFields:
    """Verifies behavior with empty bodies, missing required fields, and garbage injection."""

    def test_empty_json_body_post(self, client_alice):
        response = client_alice.post("/api/v1/follows/", data={}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_missing_target_id_post(self, client_alice):
        payload = {"action": "follow"}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_hundred_garbage_fields_injection(self, client_alice, user_alice, user_bob):
        payload = {"target_id": str(user_bob.id)}
        for i in range(100):
            payload[f"garbage_extra_field_{i}"] = f"malicious_value_{i}"

        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        # Should succeed because extra fields are ignored by serializer, or return 400
        assert response.status_code in (status.HTTP_201_CREATED, status.HTTP_200_OK)
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
        assert UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

    def test_server_controlled_fields_mass_assignment(self, client_alice, user_alice, user_bob):
        # Attempt to tamper with server controlled fields
        payload = {
            "target_id": str(user_bob.id),
            "created_at": "1999-01-01T00:00:00Z",
            "is_following": False,
            "id": str(user_bob.id),
        }
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code in (status.HTTP_201_CREATED, status.HTTP_200_OK)
        follow_record = UserFollow.objects.get(follower=user_alice, followed_user=user_bob)
        # Server must control created_at; client input cannot override
        assert follow_record.created_at.year != 1999


# =====================================================================
# 4. Format-Specific Invalid Inputs
# =====================================================================

@pytest.mark.django_db
class TestFormatSpecificInvalidInputs:
    """Verifies non-existent IDs, self-following, and invalid entity states."""

    def test_non_existent_uuid_returns_404(self, client_alice):
        non_existent_id = uuid.uuid4()
        payload = {"target_id": str(non_existent_id)}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_cannot_follow_self(self, client_alice, user_alice):
        payload = {"target_id": str(user_alice.id)}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "cannot follow yourself" in response.json().get("message", "").lower()

    def test_cannot_follow_inactive_user(self, client_alice, user_inactive):
        payload = {"target_id": str(user_inactive.id)}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_cannot_follow_deactivated_gym(self, client_bob, gym_instance):
        settings = gym_instance.settings
        settings.is_deactivated = True
        settings.save()

        payload = {"target_id": str(gym_instance.id)}
        response = client_bob.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "inactive" in response.json().get("message", "").lower()

    def test_cannot_follow_deleted_gym(self, client_bob, gym_instance):
        settings = gym_instance.settings
        settings.is_deleted = True
        settings.save()

        payload = {"target_id": str(gym_instance.id)}
        response = client_bob.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json().get("message", "").lower()


# =====================================================================
# 5. Query Parameters, Filters & Search Edge Cases
# =====================================================================

@pytest.mark.django_db
class TestQueryParamsAndEdgeCases:
    """Verifies query param parsing, adversarial query strings, and conflicting params."""

    @pytest.mark.parametrize(
        "query_val",
        [
            "",
            "null",
            "12345",
            "not-a-uuid",
            "undefined",
            "NaN",
        ],
    )
    def test_invalid_query_param_on_delete(self, client_alice, query_val):
        response = client_alice.delete(f"/api/v1/follows/?target_id={query_val}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_unfollow_not_following_returns_404(self, client_alice, user_bob):
        # User Alice is NOT following user Bob
        payload = {"target_id": str(user_bob.id)}
        response = client_alice.delete("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_conflicting_query_and_body_params(self, client_alice, user_alice, user_bob, gym_instance):
        # Alice follows gym first
        GymFollow.objects.create(user=user_alice, gym=gym_instance)

        # Body contains gym_id, query contains bob.id -> body takes precedence or handled cleanly
        payload = {"target_id": str(gym_instance.id)}
        response = client_alice.delete(f"/api/v1/follows/?target_id={user_bob.id}", data=payload, format="json")
        assert response.status_code in (status.HTTP_200_OK, status.HTTP_404_NOT_FOUND)
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# =====================================================================
# 6. Security & Injection Testing
# =====================================================================

@pytest.mark.django_db
class TestSecurityAndInjection:
    """Verifies SQLi, XSS, Path Traversal, and Unicode safety across all follow endpoints."""

    @pytest.mark.parametrize(
        "sqli_payload",
        [
            "' OR 1=1 --",
            "'; DROP TABLE user_follows; --",
            "' UNION SELECT id, password FROM users --",
            "\" OR \"\"=\"",
            "1' or '1'='1",
        ],
    )
    def test_sqli_payloads_in_target_id(self, client_alice, sqli_payload):
        payload = {"target_id": sqli_payload}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
        # Verify table integrity
        assert User.objects.count() >= 1

    @pytest.mark.parametrize(
        "xss_payload",
        [
            "<script>alert(1)</script>",
            "<img src=x onerror=alert('XSS')>",
            "javascript:alert(document.cookie)",
            "<svg/onload=alert`1`>",
        ],
    )
    def test_xss_payloads_in_target_id_and_action(self, client_alice, xss_payload):
        payload = {"target_id": xss_payload, "action": xss_payload}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize(
        "traversal_payload",
        [
            "../../../../etc/passwd",
            "..%2F..%2F..%2Fetc%2Fpasswd",
            "..\\..\\..\\windows\\system32",
        ],
    )
    def test_path_traversal_payloads(self, client_alice, traversal_payload):
        payload = {"target_id": traversal_payload}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize(
        "unicode_payload",
        [
            "🔥🚀💪🏋️‍♂️",
            "مرحبا بالعالم",
            "你好世界",
            "Z͑ͫ̓ͪ̂ͫ̽͏̴̙̤̞͉͚̯̞aͫͪͧͬͭ̉̋͢͡l̡ͨͥͩ̂̐̍̋͝gͩ̌ͤͥͭ̽͡o",
            "﷽",
        ],
    )
    def test_unicode_and_emoji_payloads(self, client_alice, unicode_payload):
        payload = {"target_id": unicode_payload}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# =====================================================================
# 7. Authentication, Authorization & Permissions
# =====================================================================

@pytest.mark.django_db
class TestAuthenticationAndPermissions:
    """Verifies that all follow endpoints strictly enforce authentication and authorization."""

    def test_unauthenticated_requests_return_401(self, user_bob, gym_instance):
        unauth_client = APIClient()

        # 1. Unified follow endpoints
        assert unauth_client.post("/api/v1/follows/", data={"target_id": str(user_bob.id)}).status_code == status.HTTP_401_UNAUTHORIZED
        assert unauth_client.delete("/api/v1/follows/", data={"target_id": str(user_bob.id)}).status_code == status.HTTP_401_UNAUTHORIZED
        assert unauth_client.get("/api/v1/follows/").status_code == status.HTTP_401_UNAUTHORIZED
        assert unauth_client.get(f"/api/v1/follows/{user_bob.id}/").status_code == status.HTTP_401_UNAUTHORIZED

        # 2. Dedicated user follow endpoints
        assert unauth_client.post(f"/api/v1/users/{user_bob.id}/follow/").status_code == status.HTTP_401_UNAUTHORIZED
        assert unauth_client.delete(f"/api/v1/users/{user_bob.id}/follow/").status_code == status.HTTP_401_UNAUTHORIZED
        assert unauth_client.get(f"/api/v1/users/{user_bob.id}/followers/").status_code == status.HTTP_401_UNAUTHORIZED
        assert unauth_client.get(f"/api/v1/users/{user_bob.id}/following/").status_code == status.HTTP_401_UNAUTHORIZED

        # 3. Dedicated gym follow endpoints
        assert unauth_client.post(f"/api/v1/gyms/{gym_instance.id}/follow/").status_code == status.HTTP_401_UNAUTHORIZED
        assert unauth_client.delete(f"/api/v1/gyms/{gym_instance.id}/follow/").status_code == status.HTTP_401_UNAUTHORIZED
        assert unauth_client.get(f"/api/v1/gyms/{gym_instance.id}/followers/").status_code == status.HTTP_401_UNAUTHORIZED
        assert unauth_client.get(f"/api/v1/gyms/{gym_instance.id}/following/").status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize(
        "bad_token",
        [
            "Bearer invalid_token_structure",
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.garbage",
            "Basic YWxhZGRpbjpvcGVuc2VzYW1l",
            "Token 1234567890",
            "Bearer ",
        ],
    )
    def test_malformed_auth_tokens_rejected(self, bad_token, user_bob):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=bad_token)
        response = client.post("/api/v1/follows/", data={"target_id": str(user_bob.id)}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_blocked_user_cannot_follow_gym(self, client_bob, user_bob, gym_instance):
        block_user_for_gym(gym=gym_instance, user_id=str(user_bob.id), reason="Violated code of conduct.")

        payload = {"target_id": str(gym_instance.id)}
        response = client_bob.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "blocked" in response.json().get("message", "").lower()

    def test_private_user_follow_rejected(self, client_alice, user_private):
        payload = {"target_id": str(user_private.id)}
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "private" in response.json().get("message", "").lower()


# =====================================================================
# 8. IDOR & Object-Level Authorization
# =====================================================================

@pytest.mark.django_db
class TestIDORAndObjectLevelAuthorization:
    """Verifies that private resources and other users' data cannot be accessed or tampered with."""

    def test_cannot_view_private_user_followers_list(self, client_alice, user_alice, user_private):
        # Alice is NOT user_private -> 403 Forbidden
        response = client_alice.get(f"/api/v1/users/{user_private.id}/followers/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

        # Also via unified endpoint
        unified_resp = client_alice.get(f"/api/v1/follows/{user_private.id}/")
        assert unified_resp.status_code == status.HTTP_403_FORBIDDEN

    def test_cannot_view_private_user_following_list(self, client_alice, user_alice, user_private):
        response = client_alice.get(f"/api/v1/users/{user_private.id}/following/")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_owner_can_view_own_private_followers_list(self, user_private):
        token = issue_context_token(user=user_private, context_type=TokenContextType.PERSONAL)
        private_client = APIClient()
        private_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")

        response = private_client.get(f"/api/v1/users/{user_private.id}/followers/")
        assert response.status_code == status.HTTP_200_OK

        response_following = private_client.get(f"/api/v1/users/{user_private.id}/following/")
        assert response_following.status_code == status.HTTP_200_OK


# =====================================================================
# 9. Business Logic & State Transitions
# =====================================================================

@pytest.mark.django_db
class TestBusinessLogicAndStateTransitions:
    """Verifies idempotent following, unfollowing, and re-following cycles."""

    def test_idempotent_follow_user(self, client_alice, user_alice, user_bob):
        # First follow -> 201 Created
        res1 = client_alice.post("/api/v1/follows/", data={"target_id": str(user_bob.id)}, format="json")
        assert res1.status_code == status.HTTP_201_CREATED
        assert res1.json()["is_following"] is True

        # Second follow -> 200 OK (idempotent, no duplicate records)
        res2 = client_alice.post("/api/v1/follows/", data={"target_id": str(user_bob.id)}, format="json")
        assert res2.status_code == status.HTTP_200_OK
        assert res2.json()["is_following"] is True
        assert UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).count() == 1

    def test_idempotent_follow_gym(self, client_bob, user_bob, gym_instance):
        # First follow -> 201 Created
        res1 = client_bob.post("/api/v1/follows/", data={"target_id": str(gym_instance.id)}, format="json")
        assert res1.status_code == status.HTTP_201_CREATED
        assert res1.json()["is_following"] is True

        # Second follow -> 200 OK (idempotent)
        res2 = client_bob.post("/api/v1/follows/", data={"target_id": str(gym_instance.id)}, format="json")
        assert res2.status_code == status.HTTP_200_OK
        assert res2.json()["is_following"] is True
        assert GymFollow.objects.filter(user=user_bob, gym=gym_instance).count() == 1

    def test_follow_unfollow_refollow_cycle(self, client_alice, user_bob):
        for _ in range(3):
            # Follow
            res_follow = client_alice.post("/api/v1/follows/", data={"target_id": str(user_bob.id)}, format="json")
            assert res_follow.status_code in (status.HTTP_201_CREATED, status.HTTP_200_OK)
            assert res_follow.json()["is_following"] is True

            # Unfollow
            res_unfollow = client_alice.delete("/api/v1/follows/", data={"target_id": str(user_bob.id)}, format="json")
            assert res_unfollow.status_code == status.HTTP_200_OK
            assert res_unfollow.json()["is_following"] is False


# =====================================================================
# 10. HTTP Method & Endpoint Validation
# =====================================================================

@pytest.mark.django_db
class TestHTTPMethodValidation:
    """Verifies that unsupported HTTP methods return 405 Method Not Allowed."""

    def test_unsupported_methods_on_follows_endpoint(self, client_alice, user_bob):
        # PUT and PATCH are not supported on /api/v1/follows/
        res_put = client_alice.put("/api/v1/follows/", data={"target_id": str(user_bob.id)}, format="json")
        assert res_put.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        res_patch = client_alice.patch("/api/v1/follows/", data={"target_id": str(user_bob.id)}, format="json")
        assert res_patch.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_unsupported_methods_on_user_follow_detail(self, client_alice, user_bob):
        res_put = client_alice.put(f"/api/v1/users/{user_bob.id}/follow/", data={})
        assert res_put.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        res_patch = client_alice.patch(f"/api/v1/users/{user_bob.id}/follow/", data={})
        assert res_patch.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_unsupported_methods_on_gym_follow_detail(self, client_bob, gym_instance):
        res_put = client_bob.put(f"/api/v1/gyms/{gym_instance.id}/follow/", data={})
        assert res_put.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        res_patch = client_bob.patch(f"/api/v1/gyms/{gym_instance.id}/follow/", data={})
        assert res_patch.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# =====================================================================
# 11. Response Envelope & No Information Leakage
# =====================================================================

@pytest.mark.django_db
class TestResponseEnvelopeAndNoLeakage:
    """Verifies that responses adhere to standard error envelopes and do not leak stack traces."""

    def test_no_stack_trace_leakage_on_adversarial_requests(self, client_alice):
        malicious_payloads = [
            {"target_id": "' OR 1=1 --"},
            {"target_id": "<script>alert(1)</script>"},
            {"target_id": "../../etc/passwd"},
            {"target_id": "00000000-0000-0000-0000-000000000000"},
            {"target_id": "not_a_uuid"},
        ]
        for payload in malicious_payloads:
            res = client_alice.post("/api/v1/follows/", data=payload, format="json")
            assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)
            # Response should NEVER contain traceback, Traceback, or Python exception classes
            text = res.content.decode("utf-8")
            assert "Traceback" not in text
            assert "django.db" not in text
            assert "OperationalError" not in text
            assert "ProgrammingError" not in text
