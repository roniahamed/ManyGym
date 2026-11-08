import uuid
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile, UserSetting, UserBlockedUser
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    UserAudienceMessagingEnum,
    UserAudienceFollowEnum,
    UserAudienceVisibilityEnum,
    UserStatus,
)


@pytest.fixture
def user_alice(db):
    user = User.objects.create_user(
        email="alice.qa@manygym.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Tester",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, is_private=False)
    return user


@pytest.fixture
def user_bob(db):
    user = User.objects.create_user(
        email="bob.qa@manygym.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Candidate",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, is_private=False, avatar_url="https://cdn.manygym.com/bob.jpg")
    return user


@pytest.fixture
def user_charlie(db):
    user = User.objects.create_user(
        email="charlie.qa@manygym.com",
        password="SecurePassword123!",
        first_name="Charlie",
        last_name="Third",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, is_private=False)
    return user


def make_auth_client(user):
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def alice_client(user_alice):
    return make_auth_client(user_alice)


@pytest.fixture
def bob_client(user_bob):
    return make_auth_client(user_bob)


@pytest.fixture
def charlie_client(user_charlie):
    return make_auth_client(user_charlie)


# ==============================================================================
# 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
# ==============================================================================

@pytest.mark.django_db
class TestUserSettingsTypeJuggling:
    """1. Test all applicable fields with incorrect data types (Type Juggling)."""

    def test_patch_settings_type_mismatches(self, alice_client):
        url = reverse("user-settings")

        invalid_type_payloads = [
            # Integer where string expected
            ({"language": 12345}, 400),
            # Array/list where string expected
            ({"language": ["en"]}, 400),
            # Dict/object where string expected
            ({"language": {"code": "en"}}, 400),
            # Boolean where string expected
            ({"language": True}, 400),
            # String where boolean expected
            ({"dark_mode": "true"}, 400),
            ({"dark_mode": "1"}, 400),
            ({"dark_mode": "yes"}, 400),
            ({"dark_mode": "false"}, 400),
            ({"video_autoplay": "true"}, 400),
            ({"video_autoplay": "1"}, 400),
            ({"video_autoplay": "yes"}, 400),
            ({"video_autoplay": "false"}, 400),
            ({"is_private": "true"}, 400),
            ({"is_private": "yes"}, 400),
            # Integer where boolean expected
            ({"dark_mode": 1}, 400),
            ({"dark_mode": 0}, 400),
            ({"video_autoplay": 1}, 400),
            ({"video_autoplay": 0}, 400),
            ({"is_private": 1}, 400),
            ({"is_private": 0}, 400),
            # Float where boolean expected
            ({"dark_mode": 1.5}, 400),
            ({"video_autoplay": 1.5}, 400),
            ({"is_private": 0.0}, 400),
            # List where boolean expected
            ({"dark_mode": [True]}, 400),
            ({"video_autoplay": [True]}, 400),
            ({"is_private": []}, 400),
            # Dict where boolean expected
            ({"dark_mode": {"enabled": True}}, 400),
            ({"video_autoplay": {"enabled": True}}, 400),
            ({"is_private": {"val": False}}, 400),
            # Integer where enum string expected
            ({"who_can_follow": 999}, 400),
            ({"who_can_follow_me": 999}, 400),
            ({"who_can_message": 999}, 400),
            ({"who_can_see_followers": 1}, 400),
            ({"who_can_see_following": 2}, 400),
            # List where enum string expected
            ({"who_can_follow": ["everyone"]}, 400),
            ({"who_can_follow_me": ["friends_of_friends"]}, 400),
            ({"who_can_message": ["everyone"]}, 400),
            ({"who_can_see_followers": ["everyone"]}, 400),
            ({"who_can_see_following": ["everyone"]}, 400),
            # Dict where enum string expected
            ({"who_can_follow": {"val": "everyone"}}, 400),
            ({"who_can_follow_me": {"val": "friends_of_friends"}}, 400),
            ({"who_can_message": {"val": "everyone"}}, 400),
            ({"who_can_see_followers": {"val": "everyone"}}, 400),
            ({"who_can_see_following": {"val": "everyone"}}, 400),
            # Null where non-null expected
            ({"language": None}, 400),
            ({"video_autoplay": None}, 400),
            ({"dark_mode": None}, 400),
            ({"is_private": None}, 400),
            ({"who_can_follow": None}, 400),
            ({"who_can_follow_me": None}, 400),
            ({"who_can_message": None}, 400),
            ({"who_can_see_followers": None}, 400),
            ({"who_can_see_following": None}, 400),
        ]

        for payload, expected_status in invalid_type_payloads:
            res = alice_client.patch(url, payload, format="json")
            assert res.status_code == expected_status, f"Failed for payload: {payload}, got {res.status_code}: {res.data}"

    def test_block_user_type_mismatches(self, alice_client, user_bob):
        url = reverse("user-settings-blocked-users")

        invalid_payloads = [
            # Integer where UUID expected
            {"user_id": 12345},
            # Boolean where UUID expected
            {"user_id": True},
            # Float where UUID expected
            {"user_id": 3.14},
            # List where UUID expected
            {"user_id": [str(user_bob.id)]},
            # Dict where UUID expected
            {"user_id": {"id": str(user_bob.id)}},
            # Null where UUID expected
            {"user_id": None},
            # Integer where string reason expected
            {"user_id": str(user_bob.id), "reason": 12345},
            # Boolean where string reason expected
            {"user_id": str(user_bob.id), "reason": True},
            # List where string reason expected
            {"user_id": str(user_bob.id), "reason": ["spam"]},
            # Dict where string reason expected
            {"user_id": str(user_bob.id), "reason": {"msg": "spam"}},
            # Null where string reason expected (StrictCharField rejects null)
            {"user_id": str(user_bob.id), "reason": None},
        ]

        for payload in invalid_payloads:
            res = alice_client.post(url, payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Failed for payload: {payload}, got {res.status_code}: {res.data}"

    def test_follower_block_type_mismatches(self, alice_client, user_bob):
        urls = [
            reverse("user-follower-block", kwargs={"user_id": user_bob.id}),
            reverse("user-settings-follower-block", kwargs={"user_id": user_bob.id}),
            reverse("user-settings-blocked-users-follower-block", kwargs={"user_id": user_bob.id}),
        ]

        invalid_payloads = [
            {"reason": 12345},
            {"reason": True},
            {"reason": ["spam"]},
            {"reason": {"msg": "spam"}},
        ]

        for target_url in urls:
            for payload in invalid_payloads:
                res = alice_client.post(target_url, payload, format="json")
                assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Failed for follower block payload: {payload} on {target_url}, got {res.status_code}: {res.data}"

    def test_access_control_action_type_mismatches(self, alice_client):
        url = reverse("user-settings-access-control")

        invalid_payloads = [
            {"action": 12345},
            {"action": True},
            {"action": 3.14},
            {"action": ["deactivate"]},
            {"action": {"action": "deactivate"}},
            {"action": None},
            {"action": "delete", "password": 12345, "confirmation": "delete"},
            {"action": "delete", "password": "SecurePassword123!", "confirmation": 12345},
            {"action": "delete", "password": "SecurePassword123!", "confirmation": ["delete"]},
            {"action": "delete", "password": "SecurePassword123!", "confirmation": {"confirm": "delete"}},
        ]

        for payload in invalid_payloads:
            res = alice_client.post(url, payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Failed for payload: {payload}, got {res.status_code}: {res.data}"


# ==============================================================================
# 2. BOUNDARY & LENGTH EDGE CASES
# ==============================================================================

@pytest.mark.django_db
class TestUserSettingsBoundaryAndLength:
    """2. Boundary & Length Edge Cases."""

    def test_language_length_boundaries(self, alice_client):
        url = reverse("user-settings")

        # 1. Exactly 20 chars (max length boundary) -> Success
        twenty_chars = "a" * 20
        res = alice_client.patch(url, {"language": twenty_chars}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["language"] == twenty_chars

        # 2. 21 chars (max length + 1) -> 400 Bad Request
        twenty_one_chars = "a" * 21
        res = alice_client.patch(url, {"language": twenty_one_chars}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 3. 10,000+ characters -> 400 Bad Request
        huge_str = "x" * 10500
        res = alice_client.patch(url, {"language": huge_str}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 4. Empty string -> 400 Bad Request
        res = alice_client.patch(url, {"language": ""}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 5. Single space & whitespace-only -> 400 Bad Request
        for ws in [" ", "    ", "\t\n\r"]:
            res = alice_client.patch(url, {"language": ws}, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 6. Leading/trailing whitespace -> stripped to valid length
        res = alice_client.patch(url, {"language": "  es  "}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["language"] == "es"

    def test_block_user_reason_boundaries(self, alice_client, user_bob, user_charlie):
        url = reverse("user-settings-blocked-users")

        # 1. Empty string -> 201 Created (allowed blank)
        res = alice_client.post(url, {"user_id": str(user_bob.id), "reason": ""}, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["reason"] == "" or res.data["reason"] is None

        # 2. Exactly 255 chars -> 201 Created
        max_reason = "r" * 255
        res = alice_client.post(url, {"user_id": str(user_charlie.id), "reason": max_reason}, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["reason"] == max_reason

        # 3. 256 chars (max + 1) -> 400 Bad Request
        over_reason = "r" * 256
        res = alice_client.post(url, {"user_id": str(user_bob.id), "reason": over_reason}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 4. 10,000+ chars -> 400 Bad Request
        huge_reason = "m" * 10200
        res = alice_client.post(url, {"user_id": str(user_bob.id), "reason": huge_reason}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_follower_block_reason_boundaries(self, alice_client, user_bob):
        url = reverse("user-follower-block", kwargs={"user_id": user_bob.id})

        # 1. 256 chars -> 400 Bad Request
        res = alice_client.post(url, {"reason": "b" * 256}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 2. 10,000+ chars -> 400 Bad Request
        res = alice_client.post(url, {"reason": "b" * 10500}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 3. Normal 255 chars -> 200 OK
        res = alice_client.post(url, {"reason": "b" * 255}, format="json")
        assert res.status_code == status.HTTP_200_OK

    def test_confirmation_keyword_boundaries(self, alice_client, user_alice):
        url = reverse("user-settings-access-control")

        # Invalid variations
        invalid_confirmations = [
            "",
            " ",
            "   ",
            "delet",
            "deleted",
            "deletee",
            "remove",
            "cancel",
            "d",
            "x" * 10000,
        ]

        for conf in invalid_confirmations:
            res = alice_client.post(
                url,
                {"action": "delete", "password": "SecurePassword123!", "confirmation": conf},
                format="json",
            )
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400 for confirmation: '{conf}'"

        # Valid variations (case-insensitive, whitespace trimmed)
        for valid_conf in ["delete", "DELETE", "Delete", "  delete  "]:
            # Re-activate user first if needed
            user_alice.status = UserStatus.ACTIVE
            user_alice.is_active = True
            user_alice.save()

            res = alice_client.post(
                url,
                {"action": "delete", "password": "SecurePassword123!", "confirmation": valid_conf},
                format="json",
            )
            assert res.status_code == status.HTTP_200_OK
            assert res.data["is_deleted"] is True


# ==============================================================================
# 3. MISSING, EXTRA & MALFORMED FIELDS
# ==============================================================================

@pytest.mark.django_db
class TestUserSettingsMissingExtraFields:
    """3. Missing, Extra & Malformed Fields."""

    def test_patch_settings_empty_body(self, alice_client):
        url = reverse("user-settings")
        res = alice_client.patch(url, {}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["language"] == "en"

    def test_patch_settings_100_garbage_fields(self, alice_client):
        url = reverse("user-settings")
        payload = {f"garbage_field_{i}": f"random_value_{i}" for i in range(120)}
        payload["language"] = "de"

        res = alice_client.patch(url, payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["language"] == "de"
        for k in payload:
            if k != "language":
                assert k not in res.data

    def test_patch_settings_read_only_field_tampering(self, alice_client, user_alice):
        url = reverse("user-settings")

        tamper_payload = {
            "id": str(uuid.uuid4()),
            "user_id": str(uuid.uuid4()),
            "is_deactivated": True,
            "deactivated_at": "2020-01-01T00:00:00Z",
            "is_deleted": True,
            "deleted_at": "2020-01-01T00:00:00Z",
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2020-01-01T00:00:00Z",
            "dark_mode": True,
        }

        res = alice_client.patch(url, tamper_payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["dark_mode"] is True

        # Verify database fields were NOT modified by client
        settings_obj = UserSetting.objects.get(user=user_alice)
        assert settings_obj.is_deactivated is False
        assert settings_obj.deactivated_at is None
        assert settings_obj.is_deleted is False
        assert settings_obj.deleted_at is None
        assert str(settings_obj.user_id) == str(user_alice.id)

    def test_block_user_missing_required_fields(self, alice_client):
        url = reverse("user-settings-blocked-users")

        # Missing user_id
        res = alice_client.post(url, {"reason": "No user ID"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Empty body
        res = alice_client.post(url, {}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_access_control_missing_required_fields(self, alice_client):
        url = reverse("user-settings-access-control")

        # Empty body
        res = alice_client.post(url, {}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Delete without password
        res = alice_client.post(url, {"action": "delete", "confirmation": "delete"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Delete without confirmation
        res = alice_client.post(url, {"action": "delete", "password": "SecurePassword123!"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Restore without password
        res = alice_client.post(url, {"action": "restore"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 4. FORMAT-SPECIFIC INVALID INPUTS
# ==============================================================================

@pytest.mark.django_db
class TestUserSettingsFormatSpecificInvalidInputs:
    """4. Format-Specific Invalid Inputs."""

    def test_invalid_uuid_formats(self, alice_client):
        url_block = reverse("user-settings-blocked-users")

        malformed_uuids = [
            "not-a-uuid",
            "12345",
            "00000000-0000-0000-0000",
            "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
            "g" * 36,
            "12345678-1234-1234-1234-1234567890123",  # 37 chars
            "12345678-1234-1234-1234-12345678901",   # 35 chars
        ]

        for malformed in malformed_uuids:
            # 1. Payload user_id -> 400 Bad Request
            res = alice_client.post(url_block, {"user_id": malformed}, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400 for UUID: {malformed}"

            # 2. Path parameter in unblock -> 404 Not Found (DRF path converter)
            res = alice_client.delete(f"/api/v1/users/settings/blocked-users/{malformed}/")
            assert res.status_code == status.HTTP_404_NOT_FOUND

            # 3. Path parameter in follower block -> 404 Not Found
            res = alice_client.post(f"/api/v1/users/followers/{malformed}/block/", {})
            assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_non_existent_valid_uuid(self, alice_client):
        random_uuid = uuid.uuid4()

        # 1. Block non-existent user -> 404 Not Found
        url_block = reverse("user-settings-blocked-users")
        res = alice_client.post(url_block, {"user_id": str(random_uuid)}, format="json")
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # 2. Unblock non-existent user -> 404 Not Found
        url_unblock = reverse("user-settings-blocked-user-detail", kwargs={"user_id": random_uuid})
        res = alice_client.delete(url_unblock)
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # 3. Follower block non-existent user -> 404 Not Found (across all alias endpoints)
        for url_name in [
            "user-follower-block",
            "user-settings-follower-block",
            "user-settings-blocked-users-follower-block",
        ]:
            res = alice_client.post(reverse(url_name, kwargs={"user_id": random_uuid}), {})
            assert res.status_code == status.HTTP_404_NOT_FOUND, f"Expected 404 on {url_name}"

    def test_invalid_enum_choices(self, alice_client):
        url = reverse("user-settings")

        invalid_enums = [
            ({"who_can_follow": "nobody"}, 400),
            ({"who_can_follow": "friends"}, 400),
            ({"who_can_follow": "PUBLIC"}, 400),
            ({"who_can_follow": ""}, 400),
            ({"who_can_follow_me": "nobody"}, 400),
            ({"who_can_follow_me": "family"}, 400),
            ({"who_can_follow_me": ""}, 400),
            ({"who_can_message": "nobody"}, 400),
            ({"who_can_message": "aliens"}, 400),
            ({"who_can_message": "ADMINS"}, 400),
            ({"who_can_message": ""}, 400),
            ({"who_can_see_followers": "only_me"}, 400),
            ({"who_can_see_followers": "all"}, 400),
            ({"who_can_see_followers": ""}, 400),
            ({"who_can_see_following": "friends"}, 400),
            ({"who_can_see_following": "public"}, 400),
            ({"who_can_see_following": ""}, 400),
        ]

        for payload, expected_status in invalid_enums:
            res = alice_client.patch(url, payload, format="json")
            assert res.status_code == expected_status, f"Failed for invalid enum payload: {payload}"

        # Invalid action enum
        url_action = reverse("user-settings-access-control")
        for bad_act in ["explode", "archive", "suspend", "kill", ""]:
            res = alice_client.post(url_action, {"action": bad_act}, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 5. QUERY PARAMETERS, FILTERS, SEARCH & PAGINATION
# ==============================================================================

@pytest.mark.django_db
class TestUserSettingsQueryParametersAndSearch:
    """5. Query Parameters, Filters, Search & Pagination."""

    def test_search_users_query_params(self, alice_client, user_bob):
        url = reverse("user-settings-blocked-users-search")

        # 1. Empty query -> 200 OK (returns top active candidates)
        res = alice_client.get(f"{url}?q=")
        assert res.status_code == status.HTTP_200_OK
        assert any(u["id"] == str(user_bob.id) for u in res.data)

        # 2. Whitespace-only query -> 200 OK
        res = alice_client.get(f"{url}?q=%20%20%20")
        assert res.status_code == status.HTTP_200_OK

        # 3. 10,000+ characters query -> 200 OK, returns empty list
        long_query = "x" * 10500
        res = alice_client.get(f"{url}?q={long_query}")
        assert res.status_code == status.HTTP_200_OK
        assert res.data == []

        # 4. Non-existent user query -> 200 OK, returns empty list
        res = alice_client.get(f"{url}?q=nonexistent_xyz_9999")
        assert res.status_code == status.HTTP_200_OK
        assert res.data == []

        # 5. Special characters -> 200 OK
        res = alice_client.get(url + "?q=!@#$%^&*()_+{}[]:;\"'<>?,./")
        assert res.status_code == status.HTTP_200_OK

        # 6. Garbage & duplicate query params -> 200 OK
        res = alice_client.get(f"{url}?q=Bob&extra=garbage&foo=bar&q=Bob")
        assert res.status_code == status.HTTP_200_OK
        assert any(u["id"] == str(user_bob.id) for u in res.data)

        # 7. Null byte query -> 400 Bad Request (handled gracefully without PostgreSQL DataError 500)
        res = alice_client.get(f"{url}?q=test%00user")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "null" in str(res.data).lower()


# ==============================================================================
# 6. SECURITY & INJECTION TESTING
# ==============================================================================

@pytest.mark.django_db
class TestUserSettingsSecurityAndInjection:
    """6. Security & Injection Testing (SQLi, XSS, Path Traversal, Unicode)."""

    def test_sqli_payloads(self, alice_client, user_bob):
        # 1. SQLi in search query
        url_search = reverse("user-settings-blocked-users-search")
        sqli_queries = [
            "' OR 1=1 --",
            "\" OR \"\"=\"",
            "'; DROP TABLE users; --",
            "' UNION SELECT 1, 'admin', 'pass' --",
        ]
        for query in sqli_queries:
            res = alice_client.get(f"{url_search}?q={query}")
            assert res.status_code == status.HTTP_200_OK, f"SQLi crashed on query: {query}"

        # 2. SQLi in block reason
        url_block = reverse("user-settings-blocked-users")
        res = alice_client.post(
            url_block,
            {"user_id": str(user_bob.id), "reason": "'); DROP TABLE user_blocked_users; --"},
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["reason"] == "'); DROP TABLE user_blocked_users; --"
        # Database table intact
        assert UserBlockedUser.objects.filter(blocked_user=user_bob).exists()

    def test_xss_payloads(self, alice_client, user_bob):
        url_block = reverse("user-settings-blocked-users")
        url_unblock = reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id})
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert(1)>",
            "javascript:alert(document.cookie)",
            "<svg onload=alert(1)>",
        ]
        for payload in xss_payloads:
            alice_client.delete(url_unblock)
            res = alice_client.post(
                url_block,
                {"user_id": str(user_bob.id), "reason": payload},
                format="json",
            )
            assert res.status_code == status.HTTP_201_CREATED
            assert res.data["reason"] == payload
            assert "<script>" in res.data["reason"] or "onerror" in res.data["reason"] or "javascript:" in res.data["reason"] or "<svg" in res.data["reason"]

    def test_path_traversal_payloads(self, alice_client, user_bob):
        # 1. Path traversal in language
        url_settings = reverse("user-settings")
        res = alice_client.patch(url_settings, {"language": "../../etc/passwd"}, format="json")
        # Length is 17 chars, fits in max 20, stored safely without traversing file system
        assert res.status_code == status.HTTP_200_OK
        assert res.data["language"] == "../../etc/passwd"

        # 2. Path traversal in reason
        url_block = reverse("user-settings-blocked-users")
        url_unblock = reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id})
        alice_client.delete(url_unblock)
        res = alice_client.post(
            url_block,
            {"user_id": str(user_bob.id), "reason": "../../../../etc/shadow"},
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["reason"] == "../../../../etc/shadow"

    def test_unicode_and_emoji_payloads(self, alice_client, user_bob):
        url_block = reverse("user-settings-blocked-users")
        url_unblock = reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id})
        unicode_payloads = [
            "Emoji string: 🏋️‍♂️💪🔥💯",
            "RTL Arabic: مرحبا بك في تطبيق الجيم",
            "Mixed RTL/LTR: Hello مرحبا 123",
            "Zalgo text: Z̸a̷l̶g̷o̶ H̵a̷v̸e̶n̶",
            "Kanji / CJK: 強さ・健康・トレーニング",
        ]
        for txt in unicode_payloads:
            alice_client.delete(url_unblock)
            res = alice_client.post(
                url_block,
                {"user_id": str(user_bob.id), "reason": txt},
                format="json",
            )
            assert res.status_code == status.HTTP_201_CREATED
            assert res.data["reason"] == txt


# ==============================================================================
# 7. AUTHENTICATION, AUTHORIZATION & PERMISSIONS
# ==============================================================================

@pytest.mark.django_db
class TestUserSettingsAuthenticationAndPermissions:
    """7. Authentication, Authorization & Permissions."""

    def test_unauthenticated_requests(self, user_bob):
        client = APIClient()  # No credentials

        urls_and_methods = [
            ("get", reverse("user-settings"), None),
            ("patch", reverse("user-settings"), {"language": "es"}),
            ("post", reverse("user-settings-access-control"), {"action": "deactivate"}),
            ("get", reverse("user-settings-blocked-users"), None),
            ("post", reverse("user-settings-blocked-users"), {"user_id": str(user_bob.id)}),
            ("delete", reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id}), None),
            ("get", reverse("user-settings-blocked-users-search"), None),
            ("post", reverse("user-follower-block", kwargs={"user_id": user_bob.id}), {}),
        ]

        for method, endpoint, payload in urls_and_methods:
            call_fn = getattr(client, method)
            if payload is not None:
                res = call_fn(endpoint, payload, format="json")
            else:
                res = call_fn(endpoint)
            assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Expected 401 on {method.upper()} {endpoint}, got {res.status_code}"

    def test_malformed_and_invalid_tokens(self):
        client = APIClient()

        invalid_headers = [
            "Bearer ",
            "Bearer invalid_token_12345",
            "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.bad.signature",
            "Basic dXNlcjpwYXNz",
            "Token 1234567890",
        ]

        url = reverse("user-settings")
        for header in invalid_headers:
            client.credentials(HTTP_AUTHORIZATION=header)
            res = client.get(url)
            assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Expected 401 for header: {header}"


# ==============================================================================
# 8. IDOR & OBJECT-LEVEL AUTHORIZATION
# ==============================================================================

@pytest.mark.django_db
class TestUserSettingsIDORAndUserIsolation:
    """8. IDOR & User Isolation."""

    def test_cross_user_settings_isolation(self, alice_client, bob_client, user_alice, user_bob):
        # Alice updates settings to dark mode, Spanish, private
        alice_client.patch(
            reverse("user-settings"),
            {
                "language": "es",
                "dark_mode": True,
                "is_private": True,
                "who_can_message": UserAudienceMessagingEnum.NO_ONE,
            },
            format="json",
        )

        # Bob fetches his settings
        res = bob_client.get(reverse("user-settings"))
        assert res.status_code == status.HTTP_200_OK
        # Bob's settings remain untouched defaults
        assert res.data["language"] == "en"
        assert res.data["dark_mode"] is False
        assert res.data["is_private"] is False
        assert res.data["who_can_message"] == UserAudienceMessagingEnum.FOLLOWERS

    def test_cross_user_blocklist_isolation(self, alice_client, bob_client, user_charlie):
        # Alice blocks Charlie
        alice_client.post(
            reverse("user-settings-blocked-users"),
            {"user_id": str(user_charlie.id), "reason": "Harassment"},
            format="json",
        )

        # Bob checks his blocked users
        res = bob_client.get(reverse("user-settings-blocked-users"))
        assert res.status_code == status.HTTP_200_OK
        # Charlie is NOT in Bob's blocklist
        assert len(res.data) == 0

        # Bob attempts to unblock Charlie who was blocked by Alice
        unblock_url = reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_charlie.id})
        res_unblock = bob_client.delete(unblock_url)
        # IDOR prevented: Bob gets 404 because Bob never blocked Charlie
        assert res_unblock.status_code == status.HTTP_404_NOT_FOUND

        # Alice's block on Charlie is still completely intact
        res_alice = alice_client.get(reverse("user-settings-blocked-users"))
        assert len(res_alice.data) == 1
        assert res_alice.data[0]["user_id"] == str(user_charlie.id)

    def test_search_users_to_block_excludes_self_and_already_blocked(self, alice_client, user_alice, user_bob, user_charlie):
        search_url = reverse("user-settings-blocked-users-search")

        # Initial search: Alice sees Bob and Charlie, but not Alice herself
        res = alice_client.get(search_url)
        assert res.status_code == status.HTTP_200_OK
        ids = [u["id"] for u in res.data]
        assert str(user_alice.id) not in ids
        assert str(user_bob.id) in ids
        assert str(user_charlie.id) in ids

        # Alice blocks Bob
        alice_client.post(
            reverse("user-settings-blocked-users"),
            {"user_id": str(user_bob.id)},
            format="json",
        )

        # Next search: Bob is now excluded because he is already blocked
        res2 = alice_client.get(search_url)
        ids2 = [u["id"] for u in res2.data]
        assert str(user_bob.id) not in ids2
        assert str(user_charlie.id) in ids2


# ==============================================================================
# 9. BUSINESS LOGIC & STATE TRANSITIONS
# ==============================================================================

@pytest.mark.django_db
class TestUserSettingsBusinessLogicAndStateTransitions:
    """9. Business Logic & Invalid State Transitions."""

    def test_self_block_prevention(self, alice_client, user_alice):
        # 1. POST /settings/blocked-users/
        url_block = reverse("user-settings-blocked-users")
        res = alice_client.post(url_block, {"user_id": str(user_alice.id)}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "cannot block yourself" in str(res.data).lower()

        # 2. POST /followers/<user_id>/block/
        url_follower_block = reverse("user-follower-block", kwargs={"user_id": user_alice.id})
        res2 = alice_client.post(url_follower_block, {}, format="json")
        assert res2.status_code == status.HTTP_400_BAD_REQUEST
        assert "cannot block yourself" in str(res2.data).lower()

    def test_block_idempotency(self, alice_client, user_bob):
        url = reverse("user-settings-blocked-users")

        # First block call
        res1 = alice_client.post(url, {"user_id": str(user_bob.id), "reason": "First"}, format="json")
        assert res1.status_code == status.HTTP_201_CREATED

        # Duplicate block call
        res2 = alice_client.post(url, {"user_id": str(user_bob.id), "reason": "Second"}, format="json")
        assert res2.status_code == status.HTTP_201_CREATED

        # Exactly 1 record in database
        assert UserBlockedUser.objects.filter(blocked_user=user_bob).count() == 1

    def test_unblock_non_blocked_user(self, alice_client, user_bob):
        url = reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id})
        res = alice_client.delete(url)
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_unblock_twice_returns_404_on_second(self, alice_client, user_bob):
        # Block
        alice_client.post(reverse("user-settings-blocked-users"), {"user_id": str(user_bob.id)})

        # Unblock 1
        url = reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id})
        res1 = alice_client.delete(url)
        assert res1.status_code == status.HTTP_200_OK

        # Unblock 2
        res2 = alice_client.delete(url)
        assert res2.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_account_validation_errors(self, alice_client):
        url = reverse("user-settings-access-control")

        # Wrong password
        res = alice_client.post(
            url,
            {"action": "delete", "password": "WrongPassword!", "confirmation": "delete"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "password" in str(res.data).lower()

        # Valid password, wrong confirmation
        res2 = alice_client.post(
            url,
            {"action": "delete", "password": "SecurePassword123!", "confirmation": "cancel"},
            format="json",
        )
        assert res2.status_code == status.HTTP_400_BAD_REQUEST
        assert "delete" in str(res2.data).lower()

    def test_delete_account_success_and_session_revocation(self, alice_client, user_alice):
        url = reverse("user-settings-access-control")

        # Execute soft-deletion
        res = alice_client.post(
            url,
            {"action": "delete", "password": "SecurePassword123!", "confirmation": "delete"},
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["is_deleted"] is True

        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.DELETED
        assert user_alice.is_active is False

        # Attempting any authenticated action with old token returns 401
        res_after = alice_client.get(reverse("user-settings"))
        assert res_after.status_code == status.HTTP_401_UNAUTHORIZED

    def test_deactivate_and_reactivate_lifecycle(self, alice_client, user_alice):
        url = reverse("user-settings-access-control")

        # Deactivate
        res = alice_client.post(url, {"action": "deactivate"}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["is_deactivated"] is True

        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.DEACTIVATED
        assert user_alice.is_active is False

        # Session revoked
        res_revoked = alice_client.get(reverse("user-settings"))
        assert res_revoked.status_code == status.HTTP_401_UNAUTHORIZED

        # Reactivate using login flow: logging in again automatically removes deactivate status
        client = APIClient()
        login_res = client.post(
            reverse("login"),
            {"email": user_alice.email, "password": "SecurePassword123!"},
            format="json",
        )
        assert login_res.status_code == status.HTTP_200_OK
        assert "tokens" in login_res.data

        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.ACTIVE
        assert user_alice.is_active is True

    def test_restore_deleted_account_via_login(self, alice_client, user_alice):
        # Soft delete account
        alice_client.post(
            reverse("user-settings-access-control"),
            {"action": "delete", "password": "SecurePassword123!", "confirmation": "delete"},
            format="json",
        )

        client = APIClient()
        # Normal login attempt within 24 hours automatically removes delete request and restores account
        login_res = client.post(
            reverse("login"),
            {"email": user_alice.email, "password": "SecurePassword123!"},
            format="json",
        )
        assert login_res.status_code == status.HTTP_200_OK
        assert "tokens" in login_res.data

        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.ACTIVE
        assert user_alice.is_active is True
        assert user_alice.settings.is_deleted is False


# ==============================================================================
# 10. HTTP METHOD VALIDATION
# ==============================================================================

@pytest.mark.django_db
class TestUserSettingsHTTPMethodValidation:
    """10. Unsupported HTTP methods return 405 Method Not Allowed."""

    def test_unsupported_http_methods(self, alice_client, user_bob):
        unsupported_calls = [
            # UserSettingsView only supports GET, PATCH
            ("post", reverse("user-settings"), {}),
            ("put", reverse("user-settings"), {}),
            ("delete", reverse("user-settings"), None),
            # UserAccessControlActionView only supports POST
            ("get", reverse("user-settings-access-control"), None),
            ("put", reverse("user-settings-access-control"), {}),
            ("delete", reverse("user-settings-access-control"), None),
            # UserBlockedUsersListView only supports GET, POST
            ("put", reverse("user-settings-blocked-users"), {}),
            ("delete", reverse("user-settings-blocked-users"), None),
            # UserSearchUsersToBlockView only supports GET
            ("post", reverse("user-settings-blocked-users-search"), {}),
            ("put", reverse("user-settings-blocked-users-search"), {}),
            ("delete", reverse("user-settings-blocked-users-search"), None),
            # UserBlockedUserDetailView only supports DELETE
            ("get", reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id}), None),
            ("post", reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id}), {}),
            ("put", reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id}), {}),
            # UserFollowerBlockView only supports POST (across all route aliases)
            ("get", reverse("user-follower-block", kwargs={"user_id": user_bob.id}), None),
            ("put", reverse("user-follower-block", kwargs={"user_id": user_bob.id}), {}),
            ("delete", reverse("user-follower-block", kwargs={"user_id": user_bob.id}), None),
            ("get", reverse("user-settings-follower-block", kwargs={"user_id": user_bob.id}), None),
            ("put", reverse("user-settings-follower-block", kwargs={"user_id": user_bob.id}), {}),
            ("delete", reverse("user-settings-follower-block", kwargs={"user_id": user_bob.id}), None),
            ("get", reverse("user-settings-blocked-users-follower-block", kwargs={"user_id": user_bob.id}), None),
            ("put", reverse("user-settings-blocked-users-follower-block", kwargs={"user_id": user_bob.id}), {}),
            ("delete", reverse("user-settings-blocked-users-follower-block", kwargs={"user_id": user_bob.id}), None),
        ]

        for method, endpoint, payload in unsupported_calls:
            call_fn = getattr(alice_client, method)
            if payload is not None:
                res = call_fn(endpoint, payload, format="json")
            else:
                res = call_fn(endpoint)
            assert res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, (
                f"Expected 405 on {method.upper()} {endpoint}, got {res.status_code}"
            )


# ==============================================================================
# 11. FULL CRUD & WORST-CASE ADVERSARIAL SCENARIOS
# ==============================================================================

@pytest.mark.django_db
class TestUserSettingsWorstCaseAdversarialScenarios:
    """11. Exhaustive End-to-End CRUD & High-Stress Worst Case Scenarios."""

    def test_full_crud_end_to_end_lifecycle(self, alice_client, bob_client, user_alice, user_bob, user_charlie):
        """
        Executes complete CRUD lifecycle:
        - Read default settings
        - Update settings across all fields
        - Verify persisted changes
        - Create block on User B
        - Read blocked list (User B present with metadata)
        - Search users to block (User B excluded)
        - Delete / Unblock User B
        - Verify User B removed from blocklist and restored to search
        - Create block directly from followers endpoint
        - Access & Control complete lifecycle (deactivate -> reactivate -> delete -> restore)
        """
        # 1. READ default settings
        settings_url = reverse("user-settings")
        res_read = alice_client.get(settings_url)
        assert res_read.status_code == status.HTTP_200_OK
        assert res_read.data["language"] == "en"
        assert res_read.data["dark_mode"] is False
        assert res_read.data["is_private"] is False

        # 2. UPDATE settings across multiple fields
        update_payload = {
            "language": "fr",
            "dark_mode": True,
            "is_private": True,
            "who_can_message": UserAudienceMessagingEnum.FOLLOWERS,
            "who_can_see_followers": UserAudienceVisibilityEnum.FOLLOWERS,
            "who_can_see_following": UserAudienceVisibilityEnum.PRIVATE,
        }
        res_update = alice_client.patch(settings_url, update_payload, format="json")
        assert res_update.status_code == status.HTTP_200_OK
        assert res_update.data["language"] == "fr"
        assert res_update.data["dark_mode"] is True
        assert res_update.data["is_private"] is True
        assert res_update.data["who_can_message"] == UserAudienceMessagingEnum.FOLLOWERS
        assert res_update.data["who_can_see_followers"] == UserAudienceVisibilityEnum.FOLLOWERS
        assert res_update.data["who_can_see_following"] == UserAudienceVisibilityEnum.PRIVATE

        # 3. VERIFY READ reflects updated state
        res_read_after = alice_client.get(settings_url)
        assert res_read_after.status_code == status.HTTP_200_OK
        assert res_read_after.data["language"] == "fr"
        assert res_read_after.data["dark_mode"] is True
        assert res_read_after.data["is_private"] is True

        # 4. CREATE block record
        block_url = reverse("user-settings-blocked-users")
        res_block = alice_client.post(block_url, {"user_id": str(user_bob.id), "reason": "Persistent spam"}, format="json")
        assert res_block.status_code == status.HTTP_201_CREATED
        assert res_block.data["user_id"] == str(user_bob.id)
        assert res_block.data["reason"] == "Persistent spam"
        assert res_block.data["email"] == user_bob.email
        assert res_block.data["first_name"] == user_bob.first_name

        # 5. READ blocked list
        res_list = alice_client.get(block_url)
        assert res_list.status_code == status.HTTP_200_OK
        assert len(res_list.data) == 1
        assert res_list.data[0]["user_id"] == str(user_bob.id)

        # 6. READ search candidates (User B must be excluded)
        search_url = reverse("user-settings-blocked-users-search")
        res_search = alice_client.get(search_url)
        assert res_search.status_code == status.HTTP_200_OK
        candidate_ids = [u["id"] for u in res_search.data]
        assert str(user_bob.id) not in candidate_ids
        assert str(user_charlie.id) in candidate_ids

        # 7. DELETE / Unblock User B
        unblock_url = reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id})
        res_unblock = alice_client.delete(unblock_url)
        assert res_unblock.status_code == status.HTTP_200_OK
        assert "unblocked successfully" in res_unblock.data["message"]

        # 8. VERIFY DELETE
        res_list_empty = alice_client.get(block_url)
        assert res_list_empty.status_code == status.HTTP_200_OK
        assert len(res_list_empty.data) == 0

        # 9. VERIFY SEARCH (User B reappears as candidate)
        res_search_restored = alice_client.get(search_url)
        candidate_ids_restored = [u["id"] for u in res_search_restored.data]
        assert str(user_bob.id) in candidate_ids_restored

        # 10. CREATE block from followers list endpoint
        from apps.users.models import UserFollow
        UserFollow.objects.create(follower=user_bob, followed_user=user_alice)
        assert UserFollow.objects.filter(follower=user_bob, followed_user=user_alice).exists()

        follower_block_url = reverse("user-follower-block", kwargs={"user_id": user_bob.id})
        res_fblock = alice_client.post(follower_block_url, {"reason": "Blocked from followers list"}, format="json")
        assert res_fblock.status_code == status.HTTP_200_OK
        assert not UserFollow.objects.filter(follower=user_bob, followed_user=user_alice).exists()
        assert UserBlockedUser.objects.filter(blocker=user_alice, blocked_user=user_bob).exists()

        # Clean up block for access control tests
        alice_client.delete(unblock_url)

        # 11. ACCESS CONTROL: Full lifecycle
        ac_url = reverse("user-settings-access-control")
        # Deactivate
        res_deact = alice_client.post(ac_url, {"action": "deactivate"}, format="json")
        assert res_deact.status_code == status.HTTP_200_OK
        assert res_deact.data["is_deactivated"] is True

        # Reactivate via login
        anon_client = APIClient()
        res_react = anon_client.post(
            reverse("login"),
            {"email": user_alice.email, "password": "SecurePassword123!", "reactivate": True},
            format="json",
        )
        assert res_react.status_code == status.HTTP_200_OK
        new_token = res_react.data["tokens"]["access"]
        alice_client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_token}")

        # Delete
        res_del = alice_client.post(
            ac_url,
            {"action": "delete", "password": "SecurePassword123!", "confirmation": "delete"},
            format="json",
        )
        assert res_del.status_code == status.HTTP_200_OK
        assert res_del.data["is_deleted"] is True

        # Restore via login
        res_rest = anon_client.post(
            reverse("login"),
            {"email": user_alice.email, "password": "SecurePassword123!", "restore": True},
            format="json",
        )
        assert res_rest.status_code == status.HTTP_200_OK
        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.ACTIVE

    def test_mutual_blocking_and_isolation(self, alice_client, bob_client, user_alice, user_bob):
        """
        Adversarial Scenario: User A blocks User B, and User B also blocks User A.
        Verifies:
        - Both block records coexist peacefully under the composite uniqueness constraint.
        - Neither can view the other's followers or following lists.
        - Neither can initiate messaging.
        - When User A unblocks User B, User B's block on User A remains active and restrictive.
        """
        from apps.messaging.services.conversation_services import get_or_create_user_to_user_conversation
        from common.exceptions import PermissionDeniedError

        # 1. Alice blocks Bob
        res1 = alice_client.post(reverse("user-settings-blocked-users"), {"user_id": str(user_bob.id)}, format="json")
        assert res1.status_code == status.HTTP_201_CREATED

        # 2. Bob blocks Alice
        res2 = bob_client.post(reverse("user-settings-blocked-users"), {"user_id": str(user_alice.id)}, format="json")
        assert res2.status_code == status.HTTP_201_CREATED

        # Both records exist in database
        assert UserBlockedUser.objects.filter(blocker=user_alice, blocked_user=user_bob).exists()
        assert UserBlockedUser.objects.filter(blocker=user_bob, blocked_user=user_alice).exists()

        # 3. Bob tries to view Alice's followers -> 403 Forbidden
        res_bf = bob_client.get(reverse("user-followers-list", kwargs={"user_id": user_alice.id}))
        assert res_bf.status_code == status.HTTP_403_FORBIDDEN

        # 4. Alice tries to view Bob's followers -> 403 Forbidden
        res_af = alice_client.get(reverse("user-followers-list", kwargs={"user_id": user_bob.id}))
        assert res_af.status_code == status.HTTP_403_FORBIDDEN

        # 5. Messaging is forbidden in both directions
        with pytest.raises(PermissionDeniedError, match="blocked from messaging"):
            get_or_create_user_to_user_conversation(user_alice, user_bob)
        with pytest.raises(PermissionDeniedError, match="blocked from messaging"):
            get_or_create_user_to_user_conversation(user_bob, user_alice)

        # 6. Alice unblocks Bob
        unblock_url = reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id})
        res_unblock = alice_client.delete(unblock_url)
        assert res_unblock.status_code == status.HTTP_200_OK

        # 7. Bob's block on Alice is STILL ACTIVE!
        assert not UserBlockedUser.objects.filter(blocker=user_alice, blocked_user=user_bob).exists()
        assert UserBlockedUser.objects.filter(blocker=user_bob, blocked_user=user_alice).exists()

        # Alice STILL cannot view Bob's followers because Bob has Alice blocked!
        res_af2 = alice_client.get(reverse("user-followers-list", kwargs={"user_id": user_bob.id}))
        assert res_af2.status_code == status.HTTP_403_FORBIDDEN

    def test_follow_attempt_while_blocked(self, alice_client, bob_client, user_alice, user_bob):
        """
        Verifies that follow requests are blocked bidirectionally:
        - Blocked target cannot be followed by blocker (must unblock first, 400).
        - Blocker cannot be followed by blocked target (403).
        """
        # Alice blocks Bob
        alice_client.post(reverse("user-settings-blocked-users"), {"user_id": str(user_bob.id)}, format="json")

        follow_url = reverse("user-unified-follow")

        # Bob attempts to follow Alice -> 403 Forbidden
        res_bob = bob_client.post(follow_url, {"target_id": str(user_alice.id), "target_type": "user"}, format="json")
        assert res_bob.status_code == status.HTTP_403_FORBIDDEN
        assert "blocked" in str(res_bob.data).lower()

        # Alice attempts to follow Bob -> 400 Bad Request
        res_alice = alice_client.post(follow_url, {"target_id": str(user_bob.id), "target_type": "user"}, format="json")
        assert res_alice.status_code == status.HTTP_400_BAD_REQUEST
        assert "cannot follow a user you have blocked" in str(res_alice.data).lower()

    def test_malformed_json_and_unsupported_media_types(self, alice_client):
        """
        Sends raw malformed JSON syntax and unsupported media types to verify
        that no 500 Internal Server Errors occur.
        """
        settings_url = reverse("user-settings")

        # 1. Broken JSON syntax -> 400 Bad Request (ParseError)
        res_broken = alice_client.patch(
            settings_url,
            data='{"language": "fr", "dark_mode": ',
            content_type="application/json",
        )
        assert res_broken.status_code == status.HTTP_400_BAD_REQUEST

        # 2. Unsupported Content-Type -> 415 Unsupported Media Type
        res_xml = alice_client.patch(
            settings_url,
            data="<settings><language>fr</language></settings>",
            content_type="application/xml",
        )
        assert res_xml.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

    def test_null_byte_rejections_prevent_data_error(self, alice_client, user_bob):
        """
        Adversarial: Injects null bytes (\\x00) into string fields to verify
        that DRF and services reject them with 400 rather than throwing a
        PostgreSQL DataError 500.
        """
        # 1. Null byte in language
        res_lang = alice_client.patch(
            reverse("user-settings"),
            {"language": "en\x00fr"},
            format="json",
        )
        assert res_lang.status_code == status.HTTP_400_BAD_REQUEST

        # 2. Null byte in block reason
        res_reason = alice_client.post(
            reverse("user-settings-blocked-users"),
            {"user_id": str(user_bob.id), "reason": "spam\x00bot"},
            format="json",
        )
        assert res_reason.status_code == status.HTTP_400_BAD_REQUEST

        # 3. Null byte in follower block reason
        res_fblock = alice_client.post(
            reverse("user-follower-block", kwargs={"user_id": user_bob.id}),
            {"reason": "spam\x00bot"},
            format="json",
        )
        assert res_fblock.status_code == status.HTTP_400_BAD_REQUEST

    def test_idempotent_and_rapid_access_control_actions(self, alice_client, user_alice):
        """
        Worst-Case State Machine & Inactive Account Enforcement:
        - Reactivate an already active account (idempotent, 200).
        - Restore an already active account (idempotent, 200).
        - Deactivate an active account (200).
        - Verify session token is invalidated and inactive user cannot access endpoints (401).
        - Attempt login while deactivated -> prompts to reactivate (400).
        - Reactivate via login parameter -> returns fresh tokens and restores ACTIVE state (200).
        - Soft-delete account -> revokes session tokens and marks DELETED (200).
        - Attempt login while deleted -> prompts to restore (400).
        - Restore via login parameter with valid password -> restores account and issues fresh tokens (200).
        """
        ac_url = reverse("user-settings-access-control")

        # 1. Reactivate while already active -> 200 OK
        res1 = alice_client.post(ac_url, {"action": "reactivate"}, format="json")
        assert res1.status_code == status.HTTP_200_OK
        assert res1.data["is_deactivated"] is False

        # 2. Restore while already active -> 200 OK
        res2 = alice_client.post(ac_url, {"action": "restore", "password": "SecurePassword123!"}, format="json")
        assert res2.status_code == status.HTTP_200_OK
        assert res2.data["is_deleted"] is False

        # 3. Deactivate account
        res3 = alice_client.post(ac_url, {"action": "deactivate"}, format="json")
        assert res3.status_code == status.HTTP_200_OK
        assert res3.data["is_deactivated"] is True

        # 4. Bearer token is immediately rejected because user is deactivated/inactive -> 401
        res4 = alice_client.get(reverse("user-settings"))
        assert res4.status_code == status.HTTP_401_UNAUTHORIZED

        # 5. Login while deactivated automatically removes deactivation -> 200 OK
        anon_client = APIClient()
        res5 = anon_client.post(
            reverse("login"),
            {"email": user_alice.email, "password": "SecurePassword123!"},
            format="json",
        )
        assert res5.status_code == status.HTTP_200_OK
        assert "tokens" in res5.data
        new_token = res5.data["tokens"]["access"]
        alice_client.credentials(HTTP_AUTHORIZATION=f"Bearer {new_token}")

        # 7. Delete account
        res7 = alice_client.post(
            ac_url,
            {"action": "delete", "password": "SecurePassword123!", "confirmation": "delete"},
            format="json",
        )
        assert res7.status_code == status.HTTP_200_OK
        assert res7.data["is_deleted"] is True

        # 8. Token rejected after deletion -> 401
        res8 = alice_client.get(reverse("user-settings"))
        assert res8.status_code == status.HTTP_401_UNAUTHORIZED

        # 9. Login while deleted within 24 hours automatically removes delete request -> 200 OK
        res9 = anon_client.post(
            reverse("login"),
            {"email": user_alice.email, "password": "SecurePassword123!"},
            format="json",
        )
        assert res9.status_code == status.HTTP_200_OK
        assert "tokens" in res9.data
        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.ACTIVE
        assert user_alice.is_active is True

    def test_who_can_follow_deep_social_graph_scenarios(self, alice_client, bob_client, charlie_client, user_alice, user_bob, user_charlie):
        """
        Deep social graph edge cases for 'friends_of_friends' audience follow rule:
        - Alice has who_can_follow='friends_of_friends'.
        - 1-way follow is NOT a friend: Alice follows Bob, Bob does not follow Alice.
          Bob & Charlie are mutual friends. Charlie tries to follow Alice -> 403 Forbidden.
        - Mutual friends: Alice & Bob follow each other. Now Charlie IS a friend of friend -> 201 Created.
        - 3-hop graph (Alice <-> Bob <-> Charlie <-> Dave):
          Dave follows Charlie, Charlie follows Dave. Dave tries to follow Alice -> 403 Forbidden.
        - Inactive/deleted bridge: If Bob deactivates or is deleted, Bob cannot serve as bridge -> 403.
        """
        from apps.users.models import User, UserFollow, UserProfile

        # User Dave
        user_dave = User.objects.create_user(
            email="dave.qa@manygym.com",
            password="SecurePassword123!",
            first_name="Dave",
            last_name="FarAway",
            is_verified=True,
        )
        UserProfile.objects.create(user=user_dave, is_private=False)
        dave_client = APIClient()
        token_dave = issue_context_token(user_dave, TokenContextType.PERSONAL)["access"]
        dave_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token_dave}")

        # Alice sets who_can_follow = 'friends_of_friends'
        alice_client.patch(reverse("user-settings"), {"who_can_follow": "friends_of_friends"}, format="json")

        follow_url = reverse("user-unified-follow")

        # 1. 1-way follow is NOT a friendship bridge
        # Alice follows Bob, but Bob does NOT follow Alice back
        UserFollow.objects.create(follower=user_alice, followed_user=user_bob)
        # Charlie & Bob are mutual friends
        UserFollow.objects.create(follower=user_bob, followed_user=user_charlie)
        UserFollow.objects.create(follower=user_charlie, followed_user=user_bob)

        # Charlie tries to follow Alice -> 403 Forbidden (Bob is not Alice's mutual friend!)
        res_charlie = charlie_client.post(follow_url, {"target_id": str(user_alice.id), "target_type": "user"}, format="json")
        assert res_charlie.status_code == status.HTTP_403_FORBIDDEN
        assert "friends of friends" in res_charlie.data["message"].lower()

        # 2. Make Alice & Bob mutual friends
        UserFollow.objects.create(follower=user_bob, followed_user=user_alice)

        # Now Charlie IS a friend of friend -> 201 Created!
        res_charlie_success = charlie_client.post(follow_url, {"target_id": str(user_alice.id), "target_type": "user"}, format="json")
        assert res_charlie_success.status_code == status.HTTP_201_CREATED
        assert UserFollow.objects.filter(follower=user_charlie, followed_user=user_alice).exists()

        # 3. 3-hop distance (Alice <-> Bob <-> Charlie <-> Dave)
        # Dave is Charlie's friend, but NOT Bob's friend
        UserFollow.objects.create(follower=user_charlie, followed_user=user_dave)
        UserFollow.objects.create(follower=user_dave, followed_user=user_charlie)

        # Dave tries to follow Alice -> 403 Forbidden! (3 hops away)
        res_dave = dave_client.post(follow_url, {"target_id": str(user_alice.id), "target_type": "user"}, format="json")
        assert res_dave.status_code == status.HTTP_403_FORBIDDEN
        assert "friends of friends" in res_dave.data["message"].lower()

        # 4. Deactivated / deleted intermediary cannot serve as bridge
        # Clean up Charlie's follow
        UserFollow.objects.filter(follower=user_charlie, followed_user=user_alice).delete()

        # User Eve is Charlie's friend
        user_eve = User.objects.create_user(
            email="eve.bridge@manygym.com",
            password="SecurePassword123!",
            first_name="Eve",
            last_name="Bridge",
            is_verified=True,
        )
        UserProfile.objects.create(user=user_eve, is_private=False)
        # Alice <-> Eve are mutual
        UserFollow.objects.create(follower=user_alice, followed_user=user_eve)
        UserFollow.objects.create(follower=user_eve, followed_user=user_alice)
        # Dave <-> Eve are mutual
        UserFollow.objects.create(follower=user_dave, followed_user=user_eve)
        UserFollow.objects.create(follower=user_eve, followed_user=user_dave)

        # Deactivate Eve
        user_eve.is_active = False
        user_eve.status = UserStatus.DEACTIVATED
        user_eve.save()
        eve_setting = user_eve.get_settings()
        eve_setting.is_deactivated = True
        eve_setting.save()

        # Dave tries to follow Alice using deactivated Eve as bridge -> 403 Forbidden!
        res_dave_via_inactive = dave_client.post(follow_url, {"target_id": str(user_alice.id), "target_type": "user"}, format="json")
        assert res_dave_via_inactive.status_code == status.HTTP_403_FORBIDDEN

    def test_who_can_follow_with_approval_workflow(self, alice_client, bob_client, charlie_client, user_alice, user_bob, user_charlie):
        """
        Tests interaction between who_can_follow='friends_of_friends' and require_follow_approval=True:
        - Stranger cannot follow -> 403 Forbidden (no pending request created).
        - Friend of friend follows -> 201 Created (pending UserFollowRequest created).
        - Confirmation workflow succeeds.
        """
        from apps.users.models import UserFollow, UserFollowRequest, FollowRequestStatus

        # Alice requires approval AND restricts to friends_of_friends
        alice_client.patch(
            reverse("user-settings"),
            {"who_can_follow": "friends_of_friends", "require_follow_approval": True},
            format="json",
        )

        follow_url = reverse("user-unified-follow")

        # 1. Bob (stranger) attempts to follow Alice -> 403 Forbidden
        res_bob = bob_client.post(follow_url, {"target_id": str(user_alice.id), "target_type": "user"}, format="json")
        assert res_bob.status_code == status.HTTP_403_FORBIDDEN
        assert not UserFollowRequest.objects.filter(requester=user_bob, target_user=user_alice).exists()

        # 2. Set up Charlie as friend of friend (Alice <-> Bob mutual, Bob <-> Charlie mutual)
        UserFollow.objects.create(follower=user_alice, followed_user=user_bob)
        UserFollow.objects.create(follower=user_bob, followed_user=user_alice)
        UserFollow.objects.create(follower=user_bob, followed_user=user_charlie)
        UserFollow.objects.create(follower=user_charlie, followed_user=user_bob)

        # 3. Charlie attempts to follow Alice -> 201 Created with follow request
        res_charlie = charlie_client.post(follow_url, {"target_id": str(user_alice.id), "target_type": "user"}, format="json")
        assert res_charlie.status_code == status.HTTP_201_CREATED
        assert res_charlie.data.get("is_pending_request") is True or res_charlie.data.get("status") == "pending"

        # Verify request exists in DB
        pending_req = UserFollowRequest.objects.filter(requester=user_charlie, target_user=user_alice).first()
        assert pending_req is not None
        assert pending_req.status == FollowRequestStatus.PENDING

        # 4. Alice accepts Charlie's follow request
        accept_url = reverse("user-follow-request-accept", kwargs={"request_id": pending_req.id})
        res_accept = alice_client.post(accept_url, format="json")
        assert res_accept.status_code == status.HTTP_200_OK
        assert UserFollow.objects.filter(follower=user_charlie, followed_user=user_alice).exists()

    def test_who_can_message_followers_default_enforcement(self, user_alice, user_bob, user_charlie):
        """
        Tests who_can_message policy:
        - Default is FOLLOWERS.
        - Stranger cannot initiate messaging -> DomainValidationError (400).
        - Follower can initiate messaging -> 201.
        - Setting to EVERYONE allows strangers.
        - Setting to NO_ONE rejects everyone.
        """
        from apps.messaging.services.conversation_services import get_or_create_user_to_user_conversation
        from apps.users.models import UserFollow
        from common.exceptions import DomainValidationError

        # Alice has default settings: who_can_message == FOLLOWERS
        assert user_alice.get_settings().who_can_message == UserAudienceMessagingEnum.FOLLOWERS

        # Bob (not following) tries to message Alice -> DomainValidationError
        with pytest.raises(DomainValidationError, match="only accepts direct messages from their followers"):
            get_or_create_user_to_user_conversation(user_bob, user_alice)

        # Bob follows Alice -> now allowed!
        UserFollow.objects.create(follower=user_bob, followed_user=user_alice)
        conv = get_or_create_user_to_user_conversation(user_bob, user_alice)
        assert conv is not None

        # Charlie (not following) tries to message Alice while policy is EVERYONE
        user_alice.settings.who_can_message = UserAudienceMessagingEnum.EVERYONE
        user_alice.settings.save()
        conv_charlie = get_or_create_user_to_user_conversation(user_charlie, user_alice)
        assert conv_charlie is not None

        # Alice sets who_can_message to NO_ONE -> even follower Bob is rejected
        user_alice.settings.who_can_message = UserAudienceMessagingEnum.NO_ONE
        user_alice.settings.save()
        with pytest.raises(DomainValidationError, match="does not accept direct messages"):
            get_or_create_user_to_user_conversation(user_bob, user_alice)

    def test_follower_block_alias_endpoints_exhaustive(self, alice_client, user_alice, user_bob):
        """
        Tests follower blocking across all alias endpoints:
        - /api/v1/users/followers/<uuid>/block/
        - /api/v1/users/settings/followers/<uuid>/block/
        - /api/v1/users/settings/blocked-users/followers/<uuid>/block/
        """
        from apps.users.models import UserFollow, UserBlockedUser

        alias_url_names = [
            "user-follower-block",
            "user-settings-follower-block",
            "user-settings-blocked-users-follower-block",
        ]

        for idx, url_name in enumerate(alias_url_names):
            # Clean up prior state
            UserBlockedUser.objects.filter(blocker=user_alice).delete()
            UserFollow.objects.filter(follower=user_bob, followed_user=user_alice).delete()

            # 1. Self-block attempt -> 400 Bad Request
            self_url = reverse(url_name, kwargs={"user_id": user_alice.id})
            res_self = alice_client.post(self_url, {"reason": "self block"}, format="json")
            assert res_self.status_code == status.HTTP_400_BAD_REQUEST
            assert "cannot block yourself" in str(res_self.data).lower()

            # 2. Block follower
            UserFollow.objects.create(follower=user_bob, followed_user=user_alice)
            assert UserFollow.objects.filter(follower=user_bob, followed_user=user_alice).exists()

            target_url = reverse(url_name, kwargs={"user_id": user_bob.id})
            res_block = alice_client.post(target_url, {"reason": f"Block reason {idx}"}, format="json")
            assert res_block.status_code == status.HTTP_200_OK

            # Follow is deleted and block record created
            assert not UserFollow.objects.filter(follower=user_bob, followed_user=user_alice).exists()
            assert UserBlockedUser.objects.filter(blocker=user_alice, blocked_user=user_bob).exists()

    def test_all_settings_endpoints_unauthenticated_and_token_tampering(self, user_bob):
        """
        Security: Verifies that every single settings and blocking endpoint
        strictly rejects unauthenticated and malformed requests with 401 Unauthorized.
        """
        anon_client = APIClient()
        dummy_uuid = user_bob.id

        endpoints = [
            ("get", reverse("user-settings")),
            ("patch", reverse("user-settings")),
            ("get", reverse("user-settings-blocked-users")),
            ("post", reverse("user-settings-blocked-users")),
            ("get", reverse("user-settings-blocked-users-search")),
            ("delete", reverse("user-settings-blocked-user-detail", kwargs={"user_id": dummy_uuid})),
            ("post", reverse("user-follower-block", kwargs={"user_id": dummy_uuid})),
            ("post", reverse("user-settings-follower-block", kwargs={"user_id": dummy_uuid})),
            ("post", reverse("user-settings-blocked-users-follower-block", kwargs={"user_id": dummy_uuid})),
            ("post", reverse("user-settings-access-control")),
        ]

        # 1. No token provided
        for method, url in endpoints:
            call_fn = getattr(anon_client, method)
            res = call_fn(url, {}) if method in ("post", "patch") else call_fn(url)
            assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Expected 401 on unauthenticated {method.upper()} {url}"

        # 2. Invalid / forged token
        for method, url in endpoints:
            anon_client.credentials(HTTP_AUTHORIZATION="Bearer invalid.forged.jwt")
            call_fn = getattr(anon_client, method)
            res = call_fn(url, {}) if method in ("post", "patch") else call_fn(url)
            assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Expected 401 on invalid token {method.upper()} {url}"

        # 3. Empty / malformed Authorization header
        for method, url in endpoints:
            anon_client.credentials(HTTP_AUTHORIZATION="Bearer ")
            call_fn = getattr(anon_client, method)
            res = call_fn(url, {}) if method in ("post", "patch") else call_fn(url)
            assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Expected 401 on empty Bearer token {method.upper()} {url}"

    def test_video_autoplay_toggle_and_persistence(self, alice_client, user_alice):
        """
        Verifies video_autoplay toggle, idempotency, and database persistence.
        """
        url = reverse("user-settings")

        # 1. Initial state is True (default)
        res_initial = alice_client.get(url)
        assert res_initial.data["video_autoplay"] is True

        # 2. Toggle to False
        res_off = alice_client.patch(url, {"video_autoplay": False}, format="json")
        assert res_off.status_code == status.HTTP_200_OK
        assert res_off.data["video_autoplay"] is False
        user_alice.refresh_from_db()
        assert user_alice.settings.video_autoplay is False

        # 3. Toggle back to True
        res_on = alice_client.patch(url, {"video_autoplay": True}, format="json")
        assert res_on.status_code == status.HTTP_200_OK
        assert res_on.data["video_autoplay"] is True
        user_alice.refresh_from_db()
        assert user_alice.settings.video_autoplay is True

