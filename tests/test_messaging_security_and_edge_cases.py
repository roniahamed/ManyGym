import uuid
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User
from apps.gyms.models import Gym, GymBlockedUser, GymSetting
from apps.gyms.services import create_gym
from apps.members.models import Member
from apps.access_control.models import GymStaffAssignment
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    AudienceMessagingEnum,
    StaffStatus,
    ConversationTypeEnum,
    MessageSenderTypeEnum,
)
from apps.messaging.crypto import (
    generate_x25519_keypair,
    generate_ed25519_keypair,
    sign_prekey,
    hybrid_encrypt,
)
from apps.messaging.services import (
    get_or_create_user_to_user_conversation,
    get_or_create_user_to_gym_conversation,
    send_encrypted_message,
)


@pytest.fixture
def alice(db):
    return User.objects.create_user(
        email="alice_sec@example.com",
        password="Password123!",
        first_name="Alice",
        last_name="Smith",
        is_verified=True,
    )


@pytest.fixture
def bob(db):
    return User.objects.create_user(
        email="bob_sec@example.com",
        password="Password123!",
        first_name="Bob",
        last_name="Johnson",
        is_verified=True,
    )


@pytest.fixture
def charlie(db):
    """Third party / adversarial user for IDOR and privilege testing."""
    return User.objects.create_user(
        email="charlie_sec@example.com",
        password="Password123!",
        first_name="Charlie",
        last_name="Brown",
        is_verified=True,
    )


@pytest.fixture
def gym_a(alice):
    return create_gym(owner_user=alice, name="Olympus Security Gym")


@pytest.fixture
def gym_b(bob):
    return create_gym(owner_user=bob, name="Spartan Defense Fitness")


@pytest.fixture
def alice_client(alice):
    tokens = issue_context_token(alice, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def bob_client(bob):
    tokens = issue_context_token(bob, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def charlie_client(charlie):
    tokens = issue_context_token(charlie, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def alice_bob_conv(alice, bob):
    return get_or_create_user_to_user_conversation(alice, bob)


# ============================================================================
# 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
# ============================================================================

@pytest.mark.django_db
class TestDataTypeMismatches:
    """Verifies that submitting unexpected types never crashes or produces a 500 response."""

    def test_user_device_key_register_type_mismatches(self, alice_client):
        endpoint = "/api/v1/messaging/keys/register/"

        invalid_cases = [
            ("device_id as integer", {"device_id": 12345, "identity_key": "k", "signed_prekey": "p"}),
            ("device_id as list", {"device_id": ["id"], "identity_key": "k", "signed_prekey": "p"}),
            ("device_id as dict", {"device_id": {"id": "1"}, "identity_key": "k", "signed_prekey": "p"}),
            ("device_id as boolean", {"device_id": True, "identity_key": "k", "signed_prekey": "p"}),
            ("device_id as null", {"device_id": None, "identity_key": "k", "signed_prekey": "p"}),
            ("identity_key as list", {"device_id": "d1", "identity_key": ["key"], "signed_prekey": "p"}),
            ("identity_key as dict", {"device_id": "d1", "identity_key": {"k": "v"}, "signed_prekey": "p"}),
            ("one_time_prekeys as string instead of list", {"device_id": "d1", "identity_key": "k", "signed_prekey": "p", "one_time_prekeys": "single_key"}),
            ("one_time_prekeys as integer", {"device_id": "d1", "identity_key": "k", "signed_prekey": "p", "one_time_prekeys": 12345}),
            ("one_time_prekeys contains integers", {"device_id": "d1", "identity_key": "k", "signed_prekey": "p", "one_time_prekeys": [123, 456]}),
        ]

        for desc, payload in invalid_cases:
            res = alice_client.post(endpoint, payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Failed for {desc}: got {res.status_code}"
            assert "code" in res.data, f"Missing error code in response for {desc}"
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_gym_device_key_register_type_mismatches(self, alice_client):
        endpoint = "/api/v1/messaging/keys/gym/register/"

        invalid_cases = [
            ("gym_id as string", {"gym_id": "not-a-uuid", "device_id": "d1", "identity_key": "k", "signed_prekey": "p"}),
            ("gym_id as integer", {"gym_id": 99999, "device_id": "d1", "identity_key": "k", "signed_prekey": "p"}),
            ("gym_id as list", {"gym_id": ["uuid"], "device_id": "d1", "identity_key": "k", "signed_prekey": "p"}),
            ("gym_id as boolean", {"gym_id": True, "device_id": "d1", "identity_key": "k", "signed_prekey": "p"}),
            ("gym_id as null", {"gym_id": None, "device_id": "d1", "identity_key": "k", "signed_prekey": "p"}),
        ]

        for desc, payload in invalid_cases:
            res = alice_client.post(endpoint, payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Failed for {desc}: got {res.status_code}"
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_conversation_create_type_mismatches(self, alice_client):
        endpoint = "/api/v1/messaging/conversations/"

        invalid_cases = [
            ("target_user_id as integer", {"target_user_id": 12345}),
            ("target_user_id as list", {"target_user_id": ["id"]}),
            ("target_user_id as dict", {"target_user_id": {"id": "val"}}),
            ("target_user_id as boolean", {"target_user_id": False}),
            ("conversation_type as integer", {"conversation_type": 100, "target_user_id": str(uuid.uuid4())}),
            ("conversation_type as list", {"conversation_type": ["user_to_user"]}),
            ("conversation_type as dict", {"conversation_type": {"type": "user_to_user"}}),
        ]

        for desc, payload in invalid_cases:
            res = alice_client.post(endpoint, payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Failed for {desc}: got {res.status_code}"
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_send_message_type_mismatches(self, alice_client, alice_bob_conv):
        endpoint = f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/"

        invalid_cases = [
            ("ciphertext as integer", {"ciphertext": 12345, "nonce": "abc=="}),
            ("ciphertext as list", {"ciphertext": ["payload"], "nonce": "abc=="}),
            ("ciphertext as dict", {"ciphertext": {"nested": "value"}, "nonce": "abc=="}),
            ("ciphertext as boolean", {"ciphertext": True, "nonce": "abc=="}),
            ("nonce as integer", {"ciphertext": "payload==", "nonce": 999}),
            ("nonce as list", {"ciphertext": "payload==", "nonce": ["nonce"]}),
            ("encrypted_keys as string instead of dict", {"ciphertext": "payload==", "nonce": "abc==", "encrypted_keys": "not-a-dict"}),
            ("encrypted_keys as list instead of dict", {"ciphertext": "payload==", "nonce": "abc==", "encrypted_keys": ["k1", "k2"]}),
            ("sender_type as invalid choice integer", {"ciphertext": "payload==", "nonce": "abc==", "sender_type": 42}),
            ("sender_gym_id as string", {"ciphertext": "payload==", "nonce": "abc==", "sender_type": "gym", "sender_gym_id": "not-a-uuid"}),
            ("sender_gym_id as integer", {"ciphertext": "payload==", "nonce": "abc==", "sender_type": "gym", "sender_gym_id": 12345}),
        ]

        for desc, payload in invalid_cases:
            res = alice_client.post(endpoint, payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Failed for {desc}: got {res.status_code}"
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_mark_read_type_mismatches(self, alice_client, alice_bob_conv):
        endpoint = f"/api/v1/messaging/conversations/{alice_bob_conv.id}/read/"

        invalid_cases = [
            ("up_to_message_id as string not-a-uuid", {"up_to_message_id": "not-a-uuid"}),
            ("up_to_message_id as integer", {"up_to_message_id": 12345}),
            ("up_to_message_id as list", {"up_to_message_id": ["id"]}),
            ("up_to_message_id as dict", {"up_to_message_id": {"id": 1}}),
            ("up_to_message_id as boolean", {"up_to_message_id": False}),
            ("gym_id as string not-a-uuid", {"gym_id": "not-a-uuid"}),
            ("gym_id as integer", {"gym_id": 999}),
        ]

        for desc, payload in invalid_cases:
            res = alice_client.post(endpoint, payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Failed for {desc}: got {res.status_code}"
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ============================================================================
# 2. BOUNDARY & LENGTH EDGE CASES
# ============================================================================

@pytest.mark.django_db
class TestBoundaryAndLengthEdgeCases:
    """Tests empty, whitespace-only, and extremely long boundaries."""

    def test_empty_and_whitespace_device_id(self, alice_client):
        endpoint = "/api/v1/messaging/keys/register/"

        cases = [
            ("empty string", {"device_id": "", "identity_key": "k==", "signed_prekey": "p=="}),
            ("single space", {"device_id": " ", "identity_key": "k==", "signed_prekey": "p=="}),
            ("tabs and newlines", {"device_id": "\t\n  \r", "identity_key": "k==", "signed_prekey": "p=="}),
        ]
        for desc, payload in cases:
            res = alice_client.post(endpoint, payload, format="json")
            assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_200_OK)
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_extremely_long_strings_exceeding_boundaries(self, alice_client, alice_bob_conv):
        # device_id max_length is 100
        res = alice_client.post(
            "/api/v1/messaging/keys/register/",
            {
                "device_id": "A" * 101,
                "identity_key": "k==",
                "signed_prekey": "p==",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # device_id 10,000 characters
        res = alice_client.post(
            "/api/v1/messaging/keys/register/",
            {
                "device_id": "A" * 10000,
                "identity_key": "k==",
                "signed_prekey": "p==",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # nonce max_length is 255; test 256 and 10,000 characters
        send_endpoint = f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/"
        res = alice_client.post(
            send_endpoint,
            {
                "ciphertext": "valid_cipher==",
                "nonce": "N" * 256,
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        res = alice_client.post(
            send_endpoint,
            {
                "ciphertext": "valid_cipher==",
                "nonce": "N" * 10000,
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_and_whitespace_message_payloads(self, alice_client, alice_bob_conv):
        send_endpoint = f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/"

        cases = [
            ("empty ciphertext", {"ciphertext": "", "nonce": "abc=="}),
            ("whitespace ciphertext", {"ciphertext": "   ", "nonce": "abc=="}),
            ("empty nonce", {"ciphertext": "payload==", "nonce": ""}),
            ("whitespace nonce", {"ciphertext": "payload==", "nonce": "   "}),
        ]
        for desc, payload in cases:
            res = alice_client.post(send_endpoint, payload, format="json")
            assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_200_OK)
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_extremely_large_ciphertext_payload(self, alice_client, alice_bob_conv):
        """E2EE payloads can be large encrypted strings; verify system handles 50,000+ chars gracefully."""
        send_endpoint = f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/"
        large_ciphertext = "A" * 50000

        res = alice_client.post(
            send_endpoint,
            {
                "ciphertext": large_ciphertext,
                "nonce": "valid_nonce_123==",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        assert len(res.data["ciphertext"]) == 50000


# ============================================================================
# 3. MISSING, EXTRA & MALFORMED FIELDS
# ============================================================================

@pytest.mark.django_db
class TestMissingExtraAndMalformedFields:
    """Tests completely empty bodies, missing required fields, and garbage field injection."""

    def test_empty_json_bodies_on_all_post_endpoints(self, alice_client, alice_bob_conv):
        endpoints = [
            "/api/v1/messaging/keys/register/",
            "/api/v1/messaging/keys/gym/register/",
            "/api/v1/messaging/conversations/",
            f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/",
            f"/api/v1/messaging/conversations/{alice_bob_conv.id}/read/",
        ]
        for ep in endpoints:
            res = alice_client.post(ep, {}, format="json")
            assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_200_OK)
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_hundred_garbage_fields_injection(self, alice_client, alice_bob_conv):
        """Verify that injecting 100+ unmodeled garbage fields does not crash the endpoints."""
        garbage = {f"garbage_field_{i}": f"value_{i}" * 10 for i in range(120)}

        # 1. Key registration with garbage
        payload1 = {
            "device_id": "clean-device-1",
            "identity_key": "idkey==",
            "signed_prekey": "prekey==",
            **garbage,
        }
        res1 = alice_client.post("/api/v1/messaging/keys/register/", payload1, format="json")
        assert res1.status_code == status.HTTP_200_OK
        assert res1.data["device_id"] == "clean-device-1"

        # 2. Send message with garbage
        payload2 = {
            "ciphertext": "cipher==",
            "nonce": "nonce==",
            **garbage,
        }
        res2 = alice_client.post(
            f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/",
            payload2,
            format="json",
        )
        assert res2.status_code == status.HTTP_201_CREATED

    def test_read_only_and_server_controlled_fields_cannot_be_tampered(self, alice_client, alice_bob_conv):
        """Verify client cannot forge delivery_status, id, sent_at, or unread_count."""
        forged_id = str(uuid.uuid4())
        payload = {
            "id": forged_id,
            "ciphertext": "cipher==",
            "nonce": "nonce==",
            "delivery_status": "read",
            "sent_at": "1990-01-01T00:00:00Z",
            "delivered_at": "1990-01-01T00:00:00Z",
            "read_at": "1990-01-01T00:00:00Z",
        }
        res = alice_client.post(
            f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/",
            payload,
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        # Server must generate its own ID and status must default to 'sent'
        assert res.data["id"] != forged_id
        assert res.data["delivery_status"] == "sent"
        assert res.data["read_at"] is None


# ============================================================================
# 4. FORMAT-SPECIFIC INVALID INPUTS
# ============================================================================

@pytest.mark.django_db
class TestFormatSpecificInvalidInputs:
    """Tests non-existent UUIDs, malformed formats, and boundary lookups."""

    def test_non_existent_and_invalid_user_key_bundle(self, alice_client):
        # Invalid UUID format -> 404
        res = alice_client.get("/api/v1/messaging/keys/user/not-a-valid-uuid/")
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # Valid UUID but non-existent user -> 404
        non_existent_uuid = str(uuid.uuid4())
        res = alice_client.get(f"/api/v1/messaging/keys/user/{non_existent_uuid}/")
        assert res.status_code == status.HTTP_404_NOT_FOUND
        assert res.data["code"] in ("RESOURCE_NOT_FOUND", "NOT_FOUND")

    def test_non_existent_and_invalid_gym_key_bundle(self, alice_client):
        # Invalid UUID format -> 404
        res = alice_client.get("/api/v1/messaging/keys/gym/not-a-valid-uuid/")
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # Valid UUID but non-existent gym -> 404
        non_existent_uuid = str(uuid.uuid4())
        res = alice_client.get(f"/api/v1/messaging/keys/gym/{non_existent_uuid}/")
        assert res.status_code == status.HTTP_404_NOT_FOUND
        assert res.data["code"] in ("RESOURCE_NOT_FOUND", "NOT_FOUND")

    def test_non_existent_conversation_endpoints(self, alice_client):
        non_existent_id = str(uuid.uuid4())

        # Detail
        res = alice_client.get(f"/api/v1/messaging/conversations/{non_existent_id}/")
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # Messages list
        res = alice_client.get(f"/api/v1/messaging/conversations/{non_existent_id}/messages/")
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # Send message
        res = alice_client.post(
            f"/api/v1/messaging/conversations/{non_existent_id}/messages/",
            {"ciphertext": "c==", "nonce": "n=="},
            format="json",
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # Mark read
        res = alice_client.post(
            f"/api/v1/messaging/conversations/{non_existent_id}/read/",
            {},
            format="json",
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND


# ============================================================================
# 5. QUERY PARAMETERS, FILTERS & PAGINATION
# ============================================================================

@pytest.mark.django_db
class TestQueryParamsAndPagination:
    """Tests query parameter robustness, invalid pagination limits, and garbage query parameters."""

    def test_messages_limit_query_parameter_edge_cases(self, alice_client, alice_bob_conv):
        endpoint = f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/"

        # Send 3 messages
        for i in range(3):
            alice_client.post(endpoint, {"ciphertext": f"msg_{i}==", "nonce": f"nonce_{i}=="}, format="json")

        cases = [
            ("limit=0", "?limit=0", 3),
            ("negative limit", "?limit=-5", 3),
            ("string limit", "?limit=abc", 3),
            ("float limit", "?limit=2.5", 3),
            ("extremely large limit", "?limit=999999999999999999999", 3),
            ("limit=1", "?limit=1", 1),
            ("limit=2", "?limit=2", 2),
            ("SQLi in limit", "?limit=1;DROP TABLE users--", 3),
            ("XSS in limit", "?limit=<script>alert(1)</script>", 3),
        ]

        for desc, query_str, expected_len in cases:
            res = alice_client.get(f"{endpoint}{query_str}")
            assert res.status_code == status.HTTP_200_OK, f"Failed for {desc}: got {res.status_code}"
            assert len(res.data) == expected_len, f"Wrong count for {desc}"

    def test_conversations_list_gym_id_query_param_edge_cases(self, alice_client):
        endpoint = "/api/v1/messaging/conversations/"

        cases = [
            ("non-existent gym_id", f"?gym_id={uuid.uuid4()}"),
            ("invalid format gym_id", "?gym_id=invalid-uuid-string"),
            ("SQLi in gym_id", "?gym_id=' OR 1=1 --"),
            ("empty gym_id", "?gym_id="),
            ("arbitrary garbage query params", "?page=abc&ordering=-created_at&search=%27%20OR%201%3D1&limit=bad"),
        ]

        for desc, query_str in cases:
            res = alice_client.get(f"{endpoint}{query_str}")
            assert res.status_code == status.HTTP_200_OK, f"Failed for {desc}: got {res.status_code}"
            assert isinstance(res.data, list)


# ============================================================================
# 6. SECURITY & INJECTION TESTING
# ============================================================================

@pytest.mark.django_db
class TestSecurityAndInjection:
    """Tests SQLi, XSS, Path Traversal, and complex Unicode/Emoji resilience."""

    def test_sql_injection_payloads(self, alice_client, alice_bob_conv):
        sqli_payloads = [
            "' OR 1=1 --",
            "\" OR \"\"=\"",
            "'; DROP TABLE messaging_conversations; --",
            "1 UNION SELECT null, null, null--",
            "admin'--",
            "\\x27\\x22",
        ]

        # In key registration
        for payload in sqli_payloads:
            res = alice_client.post(
                "/api/v1/messaging/keys/register/",
                {
                    "device_id": f"dev_{payload[:20]}",
                    "device_name": payload,
                    "identity_key": "idkey==",
                    "signed_prekey": "prekey==",
                },
                format="json",
            )
            assert res.status_code == status.HTTP_200_OK

        # In message dispatch
        for payload in sqli_payloads:
            res = alice_client.post(
                f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/",
                {
                    "ciphertext": payload,
                    "nonce": "valid_nonce_abc==",
                    "ephemeral_public_key": payload,
                },
                format="json",
            )
            assert res.status_code == status.HTTP_201_CREATED
            assert res.data["ciphertext"] == payload

    def test_cross_site_scripting_xss_payloads(self, alice_client, alice_bob_conv):
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert(1)>",
            "javascript:alert(document.cookie)",
            "<svg/onload=alert`1`>",
            "\"><script>alert(1)</script>",
        ]

        for payload in xss_payloads:
            res = alice_client.post(
                f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/",
                {
                    "ciphertext": payload,
                    "nonce": "nonce==",
                },
                format="json",
            )
            assert res.status_code == status.HTTP_201_CREATED
            assert res.data["ciphertext"] == payload

    def test_path_traversal_payloads(self, alice_client, alice_bob_conv):
        path_traversal_payloads = [
            "../../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\cmd.exe",
            "%2e%2e%2f%2e%2e%2fetc%2fshadow",
        ]

        for payload in path_traversal_payloads:
            res = alice_client.post(
                "/api/v1/messaging/keys/register/",
                {
                    "device_id": f"dev_{payload[:15]}",
                    "device_name": payload,
                    "identity_key": "k==",
                    "signed_prekey": "p==",
                },
                format="json",
            )
            assert res.status_code == status.HTTP_200_OK

    def test_unicode_emoji_rtl_and_multilingual_payloads(self, alice_client, alice_bob_conv):
        test_strings = [
            "🔒 Key Exchange: 🔥 🏋️‍♂️ 🚀 💯",
            "العربية / فارسی / עברית (RTL Text)",
            "Z̵̡̧a̷̢l̷̢ģ̶o̷̧ ̸̡T̵̢ȩ̶x̷̢ţ̶",
            "こんにちは世界 (Japanese Kanji & Kana)",
            "Привет мир (Cyrillic)",
            "👨‍👩‍👧‍👦 Complex emoji zero-width joiners",
        ]

        for text in test_strings:
            res = alice_client.post(
                f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/",
                {
                    "ciphertext": text,
                    "nonce": "valid_nonce==",
                    "ephemeral_public_key": "ephemeral==",
                },
                format="json",
            )
            assert res.status_code == status.HTTP_201_CREATED
            assert res.data["ciphertext"] == text


# ============================================================================
# 7. AUTHENTICATION, AUTHORIZATION & PERMISSIONS
# ============================================================================

@pytest.mark.django_db
class TestAuthenticationAndPermissions:
    """Verifies that unauthenticated or unauthorized users are strictly denied."""

    def test_unauthenticated_requests_fail_with_401(self, alice_bob_conv):
        anonymous_client = APIClient()

        endpoints = [
            ("POST", "/api/v1/messaging/keys/register/", {}),
            ("POST", "/api/v1/messaging/keys/gym/register/", {}),
            ("GET", f"/api/v1/messaging/keys/user/{uuid.uuid4()}/", None),
            ("GET", f"/api/v1/messaging/keys/gym/{uuid.uuid4()}/", None),
            ("GET", "/api/v1/messaging/conversations/", None),
            ("POST", "/api/v1/messaging/conversations/", {}),
            ("GET", f"/api/v1/messaging/conversations/{alice_bob_conv.id}/", None),
            ("GET", f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/", None),
            ("POST", f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/", {}),
            ("POST", f"/api/v1/messaging/conversations/{alice_bob_conv.id}/read/", {}),
        ]

        for method, ep, data in endpoints:
            if method == "GET":
                res = anonymous_client.get(ep)
            else:
                res = anonymous_client.post(ep, data, format="json")
            assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Expected 401 for {method} {ep}, got {res.status_code}"
            assert res.data["code"] == "AUTHENTICATION_REQUIRED"

    def test_malformed_and_garbage_auth_tokens(self, alice_bob_conv):
        client = APIClient()
        bad_tokens = [
            "Bearer ",
            "Bearer invalid.jwt.token",
            "Bearer 12345",
            "Basic YWxhZGRpbjpvcGVuc2VzYW1l",
            "Token something",
        ]

        for token in bad_tokens:
            client.credentials(HTTP_AUTHORIZATION=token)
            res = client.get("/api/v1/messaging/conversations/")
            assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unauthorized_user_cannot_register_keys_for_gym(self, charlie_client, gym_a):
        """Charlie (not staff or owner of gym_a) tries to register keys for gym_a -> 403."""
        payload = {
            "gym_id": str(gym_a.id),
            "device_id": "charlie-rogue-device",
            "identity_key": "idkey==",
            "signed_prekey": "prekey==",
        }
        res = charlie_client.post("/api/v1/messaging/keys/gym/register/", payload, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert res.data["code"] == "PERMISSION_DENIED"

    def test_unauthorized_user_cannot_send_messages_as_gym(self, charlie_client, alice, gym_a):
        """Charlie tries to impersonate gym_a in a message dispatch -> 403."""
        conv = get_or_create_user_to_gym_conversation(alice, gym_a)
        payload = {
            "ciphertext": "spoofed_cipher==",
            "nonce": "nonce==",
            "sender_type": "gym",
            "sender_gym_id": str(gym_a.id),
        }
        res = charlie_client.post(
            f"/api/v1/messaging/conversations/{conv.id}/messages/",
            payload,
            format="json",
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN


# ============================================================================
# 8. IDOR & OBJECT-LEVEL AUTHORIZATION
# ============================================================================

@pytest.mark.django_db
class TestIDORAndObjectLevelAuthorization:
    """Actively attempts Insecure Direct Object Reference attacks."""

    def test_third_party_cannot_read_conversation_details(self, charlie_client, alice_bob_conv):
        res = charlie_client.get(f"/api/v1/messaging/conversations/{alice_bob_conv.id}/")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert res.data["code"] == "PERMISSION_DENIED"

    def test_third_party_cannot_read_conversation_messages(self, charlie_client, alice_bob_conv, alice):
        # Alice sends a private message
        send_encrypted_message(
            conversation=alice_bob_conv,
            sender_user=alice,
            sender_type=MessageSenderTypeEnum.USER,
            ciphertext="SuperSecretPayload==",
            nonce="nonce==",
        )

        res = charlie_client.get(f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert res.data["code"] == "PERMISSION_DENIED"

    def test_third_party_cannot_send_message_into_others_conversation(self, charlie_client, alice_bob_conv):
        payload = {
            "ciphertext": "AdversarialInjectedMessage==",
            "nonce": "nonce==",
        }
        res = charlie_client.post(
            f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/",
            payload,
            format="json",
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert res.data["code"] == "PERMISSION_DENIED"

    def test_third_party_cannot_mark_others_conversation_as_read(self, charlie_client, alice_bob_conv):
        res = charlie_client.post(
            f"/api/v1/messaging/conversations/{alice_bob_conv.id}/read/",
            {},
            format="json",
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert res.data["code"] == "PERMISSION_DENIED"


# ============================================================================
# 9. BUSINESS LOGIC & INVALID STATE TRANSITIONS
# ============================================================================

@pytest.mark.django_db
class TestBusinessLogicAndStateTransitions:
    """Tests self-messaging, blocklist rules, and gym audience policies."""

    def test_cannot_create_conversation_with_self(self, alice_client, alice):
        res = alice_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "user_to_user",
                "target_user_id": str(alice.id),
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "yourself" in res.data["message"].lower()

    def test_cannot_create_b2b_conversation_with_same_gym(self, alice_client, gym_a):
        res = alice_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "gym_to_gym",
                "source_gym_id": str(gym_a.id),
                "target_gym_id": str(gym_a.id),
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "same gym" in res.data["message"].lower()

    def test_blocked_user_cannot_initiate_conversation_with_gym(self, bob_client, bob, gym_a):
        GymBlockedUser.objects.create(gym=gym_a, user=bob)

        res = bob_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "user_to_gym",
                "target_gym_id": str(gym_a.id),
            },
            format="json",
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert "blocked" in res.data["message"].lower()

    def test_members_only_policy_enforcement(self, bob_client, bob, gym_a):
        GymSetting.objects.update_or_create(
            gym=gym_a,
            defaults={"who_can_message": AudienceMessagingEnum.MEMBERS_ONLY},
        )

        # Bob is not a member -> rejected with 400
        res = bob_client.post(
            "/api/v1/messaging/conversations/",
            {
                "target_gym_id": str(gym_a.id),
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "members" in res.data["message"].lower()

        # Enroll Bob as active member -> now accepted
        Member.objects.create(gym=gym_a, user=bob, joining_status="active")

        res2 = bob_client.post(
            "/api/v1/messaging/conversations/",
            {
                "target_gym_id": str(gym_a.id),
            },
            format="json",
        )
        assert res2.status_code == status.HTTP_201_CREATED


# ============================================================================
# 10. HTTP METHOD & ENDPOINT VALIDATION
# ============================================================================

@pytest.mark.django_db
class TestHTTPMethodValidation:
    """Tests that calling unpermitted HTTP methods returns 405 Method Not Allowed."""

    def test_unsupported_methods_return_405(self, alice_client, alice_bob_conv, alice, gym_a):
        unsupported_calls = [
            ("POST", f"/api/v1/messaging/keys/user/{alice.id}/"),
            ("DELETE", f"/api/v1/messaging/keys/user/{alice.id}/"),
            ("POST", f"/api/v1/messaging/keys/gym/{gym_a.id}/"),
            ("DELETE", f"/api/v1/messaging/keys/gym/{gym_a.id}/"),
            ("PUT", "/api/v1/messaging/conversations/"),
            ("DELETE", "/api/v1/messaging/conversations/"),
            ("POST", f"/api/v1/messaging/conversations/{alice_bob_conv.id}/"),
            ("DELETE", f"/api/v1/messaging/conversations/{alice_bob_conv.id}/"),
            ("PUT", f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/"),
            ("DELETE", f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/"),
            ("GET", f"/api/v1/messaging/conversations/{alice_bob_conv.id}/read/"),
            ("DELETE", f"/api/v1/messaging/conversations/{alice_bob_conv.id}/read/"),
        ]

        for method, ep in unsupported_calls:
            if method == "POST":
                res = alice_client.post(ep, {}, format="json")
            elif method == "DELETE":
                res = alice_client.delete(ep)
            elif method == "PUT":
                res = alice_client.put(ep, {}, format="json")
            elif method == "GET":
                res = alice_client.get(ep)
            assert res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, f"Expected 405 for {method} {ep}, got {res.status_code}"
            assert res.data["code"] == "METHOD_NOT_ALLOWED"


# ============================================================================
# 11. INDIVIDUAL MISSING FIELDS, EXACT BOUNDARIES & ENVELOPE INTEGRITY
# ============================================================================

@pytest.mark.django_db
class TestMissingFieldsAndExactBoundaries:
    """Verifies that missing each required field individually returns 400 Bad Request."""

    def test_missing_required_fields_individually_on_key_register(self, alice_client):
        full_payload = {
            "device_id": "valid-device-1",
            "identity_key": "idkey==",
            "signed_prekey": "prekey==",
        }
        for field in ("device_id", "identity_key", "signed_prekey"):
            payload = {k: v for k, v in full_payload.items() if k != field}
            res = alice_client.post("/api/v1/messaging/keys/register/", payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400 when missing {field}"
            assert res.data["code"] == "VALIDATION_ERROR"
            assert field in res.data["details"]

    def test_missing_required_fields_individually_on_send_message(self, alice_client, alice_bob_conv):
        ep = f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/"
        full_payload = {
            "ciphertext": "valid_cipher==",
            "nonce": "valid_nonce==",
        }
        for field in ("ciphertext", "nonce"):
            payload = {k: v for k, v in full_payload.items() if k != field}
            res = alice_client.post(ep, payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400 when missing {field}"
            assert res.data["code"] == "VALIDATION_ERROR"

    def test_exact_length_boundaries_min_max(self, alice_client, alice_bob_conv):
        # device_id: max 100
        res_exact_100 = alice_client.post(
            "/api/v1/messaging/keys/register/",
            {"device_id": "D" * 100, "identity_key": "k==", "signed_prekey": "p=="},
            format="json",
        )
        assert res_exact_100.status_code == status.HTTP_200_OK

        res_101 = alice_client.post(
            "/api/v1/messaging/keys/register/",
            {"device_id": "D" * 101, "identity_key": "k==", "signed_prekey": "p=="},
            format="json",
        )
        assert res_101.status_code == status.HTTP_400_BAD_REQUEST

        # nonce: max 255
        ep = f"/api/v1/messaging/conversations/{alice_bob_conv.id}/messages/"
        res_exact_255 = alice_client.post(
            ep,
            {"ciphertext": "cipher==", "nonce": "N" * 255},
            format="json",
        )
        assert res_exact_255.status_code == status.HTTP_201_CREATED

        res_256 = alice_client.post(
            ep,
            {"ciphertext": "cipher==", "nonce": "N" * 256},
            format="json",
        )
        assert res_256.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestResponseEnvelopeAndNoLeakage:
    """Verifies that error responses never leak tracebacks or database errors."""

    def test_no_stack_trace_leakage_on_malformed_requests(self, alice_client):
        # Trigger validation failure
        res = alice_client.post(
            "/api/v1/messaging/keys/register/",
            {"device_id": 9999, "identity_key": ["bad"]},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        body_text = str(res.content)
        assert "Traceback" not in body_text
        assert "psycopg" not in body_text
        assert "OperationalError" not in body_text
        assert "SyntaxError" not in body_text
        assert res.data["code"] == "VALIDATION_ERROR"
        assert "message" in res.data
        assert "details" in res.data

    def test_inactive_staff_member_messaging_denied(self, charlie_client, charlie, gym_a):
        # Assign charlie as INACTIVE staff
        from apps.access_control.models import Role
        role, _ = Role.objects.get_or_create(gym=gym_a, name="Trainer", slug="trainer")
        GymStaffAssignment.objects.create(
            gym=gym_a,
            user=charlie,
            role=role,
            status=StaffStatus.INACTIVE,
        )

        # Inactive staff attempting to register gym keys -> 403
        payload = {
            "gym_id": str(gym_a.id),
            "device_id": "inactive-staff-device",
            "identity_key": "k==",
            "signed_prekey": "p==",
        }
        res = charlie_client.post("/api/v1/messaging/keys/gym/register/", payload, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert res.data["code"] == "PERMISSION_DENIED"

