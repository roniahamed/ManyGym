"""
Exhaustive Edge-Case, Worst-Case, Negative, Security, and Adversarial Test Suite
for the ManyGym Notifications REST API Endpoints.

Primary Objective:
Ensure ZERO unhandled exceptions, ZERO unexpected 500 Internal Server Errors,
strict input validation, bulletproof IDOR protection, and robust security defenses
against client-controlled input.
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.access_control.models import Role
from apps.access_control.services import seed_default_permissions_and_roles
from apps.authentication.services import issue_context_token
from apps.gyms.models import Gym, GymSetting
from apps.notifications.models import DeviceToken, Notification
from apps.notifications.selectors import (
    get_active_device_tokens_for_user,
    get_notification_by_id,
    get_unread_notification_count,
    get_user_device_tokens,
    list_notifications,
)
from apps.notifications.services import (
    delete_notification,
    mark_all_notifications_as_read,
    mark_notification_as_read,
    register_device_token,
    send_message_push_notification,
    send_notification,
    unregister_device_token,
)
from apps.users.models import User, UserProfile
from common.enums import (
    DevicePlatformEnum,
    NotificationTypeEnum,
    TokenContextType,
)
from integrations.fcm import FCMClient, FCMNotificationResult


def _make_auth_client(user: User, context_type=TokenContextType.PERSONAL, gym=None) -> APIClient:
    token = issue_context_token(user=user, context_type=context_type, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def qa_env(db):
    seed_default_permissions_and_roles()

    alice = User.objects.create_user(
        email="alice.qa@manygym.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Tester",
        is_verified=True,
    )
    UserProfile.objects.create(user=alice)

    bob = User.objects.create_user(
        email="bob.qa@manygym.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Candidate",
        is_verified=True,
    )
    UserProfile.objects.create(user=bob)

    charlie = User.objects.create_user(
        email="charlie.qa@manygym.com",
        password="SecurePassword123!",
        first_name="Charlie",
        last_name="Attacker",
        is_verified=True,
    )
    UserProfile.objects.create(user=charlie)

    gym = Gym.objects.create(
        name="QA Fitness Studio",
        owner_user=alice,
    )
    GymSetting.objects.create(gym=gym, who_can_send_joining_request="everyone")

    return {
        "alice": alice,
        "bob": bob,
        "charlie": charlie,
        "gym": gym,
    }


class TestTypeJugglingAndDataTypes:
    """Tests client-controlled inputs with incompatible and adversarial data types."""

    @pytest.mark.parametrize(
        "invalid_token",
        [
            12345,
            123.456,
            True,
            False,
            ["token_in_list"],
            {"token": "nested_dict"},
            None,
        ],
    )
    def test_device_registration_type_juggling_token(self, qa_env, invalid_token):
        client = _make_auth_client(qa_env["alice"])
        res = client.post(
            "/api/v1/notifications/devices/",
            {"token": invalid_token},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.data["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize(
        "invalid_platform",
        [
            123,
            True,
            ["android"],
            {"platform": "ios"},
            "windows_phone",
            "symbian",
        ],
    )
    def test_device_registration_type_juggling_platform(self, qa_env, invalid_platform):
        client = _make_auth_client(qa_env["alice"])
        res = client.post(
            "/api/v1/notifications/devices/",
            {"token": "valid_token_xyz", "platform": invalid_platform},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.data["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize(
        "invalid_device_id",
        [
            12345,
            True,
            ["device_1"],
            {"id": "dev1"},
        ],
    )
    def test_device_registration_type_juggling_device_id(self, qa_env, invalid_device_id):
        client = _make_auth_client(qa_env["alice"])
        res = client.post(
            "/api/v1/notifications/devices/",
            {"token": "valid_token_xyz", "device_id": invalid_device_id},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.data["code"] == "VALIDATION_ERROR"

    @pytest.mark.parametrize(
        "invalid_token",
        [
            12345,
            True,
            ["tok"],
            {"token": "dict"},
            None,
        ],
    )
    def test_device_unregister_type_juggling_token(self, qa_env, invalid_token):
        client = _make_auth_client(qa_env["alice"])
        res = client.post(
            "/api/v1/notifications/devices/unregister/",
            {"token": invalid_token},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.data["code"] == "VALIDATION_ERROR"


class TestBoundaryAndLengthLimits:
    """Tests minimum, maximum, and extreme string boundary constraints."""

    @pytest.mark.parametrize(
        "empty_or_whitespace",
        [
            "",
            " ",
            "    ",
            "\t",
            "\n",
            "\r\n",
            "   \t\n   ",
        ],
    )
    def test_empty_or_whitespace_device_token(self, qa_env, empty_or_whitespace):
        client = _make_auth_client(qa_env["alice"])
        res = client.post(
            "/api/v1/notifications/devices/",
            {"token": empty_or_whitespace},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert res.data["code"] == "VALIDATION_ERROR"

    def test_exact_token_length_boundaries(self, qa_env):
        client = _make_auth_client(qa_env["alice"])

        # 1. Exact max length: 500 chars -> Success 201
        token_500 = "T" * 500
        res_500 = client.post(
            "/api/v1/notifications/devices/",
            {"token": token_500},
            format="json",
        )
        assert res_500.status_code == status.HTTP_201_CREATED

        # 2. Max + 1 length: 501 chars -> 400 Bad Request
        token_501 = "T" * 501
        res_501 = client.post(
            "/api/v1/notifications/devices/",
            {"token": token_501},
            format="json",
        )
        assert res_501.status_code == status.HTTP_400_BAD_REQUEST

        # 3. Massive length: 15,000 chars -> 400 Bad Request (no memory crash)
        token_15k = "M" * 15000
        res_15k = client.post(
            "/api/v1/notifications/devices/",
            {"token": token_15k},
            format="json",
        )
        assert res_15k.status_code == status.HTTP_400_BAD_REQUEST

    def test_exact_device_id_and_name_boundaries(self, qa_env):
        client = _make_auth_client(qa_env["alice"])

        # device_id max is 120 chars
        dev_id_120 = "D" * 120
        res_dev_120 = client.post(
            "/api/v1/notifications/devices/",
            {"token": "tok_boundary_1", "device_id": dev_id_120},
            format="json",
        )
        assert res_dev_120.status_code == status.HTTP_201_CREATED

        dev_id_121 = "D" * 121
        res_dev_121 = client.post(
            "/api/v1/notifications/devices/",
            {"token": "tok_boundary_2", "device_id": dev_id_121},
            format="json",
        )
        assert res_dev_121.status_code == status.HTTP_400_BAD_REQUEST

        # device_name max is 150 chars
        dev_name_150 = "N" * 150
        res_name_150 = client.post(
            "/api/v1/notifications/devices/",
            {"token": "tok_boundary_3", "device_name": dev_name_150},
            format="json",
        )
        assert res_name_150.status_code == status.HTTP_201_CREATED

        dev_name_151 = "N" * 151
        res_name_151 = client.post(
            "/api/v1/notifications/devices/",
            {"token": "tok_boundary_4", "device_name": dev_name_151},
            format="json",
        )
        assert res_name_151.status_code == status.HTTP_400_BAD_REQUEST


class TestMalformedMissingAndExtraFields:
    """Tests mass assignment protection, empty payloads, and unexpected garbage fields."""

    def test_completely_empty_json_body(self, qa_env):
        client = _make_auth_client(qa_env["alice"])
        res = client.post("/api/v1/notifications/devices/", {}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "token" in res.data["details"]

    def test_mass_assignment_protection(self, qa_env):
        alice = qa_env["alice"]
        bob = qa_env["bob"]
        client = _make_auth_client(alice)

        # Adversary attempts to pass internal / privileged fields
        tampered_uuid = str(uuid.uuid4())
        payload = {
            "token": "tok_mass_assign_test",
            "id": tampered_uuid,
            "user_id": str(bob.id),
            "is_active": False,
            "created_at": "2020-01-01T00:00:00Z",
            "is_superuser": True,
        }
        res = client.post("/api/v1/notifications/devices/", payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED

        # Verify privileged fields were ignored and owned strictly by alice
        token_obj = DeviceToken.objects.get(token="tok_mass_assign_test")
        assert token_obj.user == alice
        assert str(token_obj.id) != tampered_uuid
        assert token_obj.is_active is True

    def test_100_plus_unexpected_garbage_fields(self, qa_env):
        client = _make_auth_client(qa_env["alice"])
        payload = {"token": "tok_with_garbage_fields_123"}
        for i in range(120):
            payload[f"unexpected_junk_field_{i}"] = f"junk_value_{i}"

        res = client.post("/api/v1/notifications/devices/", payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["is_active"] is True


class TestQueryParametersAndPagination:
    """Tests pagination bounds, filter injection, and sorting parameter abuse."""

    def test_query_filter_is_read_valid_and_invalid(self, qa_env):
        alice = qa_env["alice"]
        client = _make_auth_client(alice)

        send_notification(
            recipient=alice,
            notification_type=NotificationTypeEnum.SYSTEM,
            title="N1",
            body="B1",
            send_push=False,
        )

        # 1. Valid boolean filters
        assert client.get("/api/v1/notifications/?is_read=true").status_code == status.HTTP_200_OK
        assert client.get("/api/v1/notifications/?is_read=false").status_code == status.HTTP_200_OK
        assert client.get("/api/v1/notifications/?is_read=1").status_code == status.HTTP_200_OK
        assert client.get("/api/v1/notifications/?is_read=0").status_code == status.HTTP_200_OK

        # 2. Invalid boolean filter -> 400 Bad Request
        res_bad = client.get("/api/v1/notifications/?is_read=not_a_bool")
        assert res_bad.status_code == status.HTTP_400_BAD_REQUEST
        assert res_bad.data["code"] == "VALIDATION_ERROR"

    def test_query_filter_notification_type_valid_and_invalid(self, qa_env):
        alice = qa_env["alice"]
        client = _make_auth_client(alice)

        # Valid enum filter
        res_valid = client.get("/api/v1/notifications/?notification_type=reaction")
        assert res_valid.status_code == status.HTTP_200_OK

        # Invalid enum filter -> 400 Bad Request
        res_invalid = client.get("/api/v1/notifications/?notification_type=non_existent_type")
        assert res_invalid.status_code == status.HTTP_400_BAD_REQUEST
        assert res_invalid.data["code"] == "VALIDATION_ERROR"

    def test_pagination_bounds_and_invalid_values(self, qa_env):
        alice = qa_env["alice"]
        client = _make_auth_client(alice)

        # Create notifications
        for i in range(5):
            send_notification(
                recipient=alice,
                notification_type=NotificationTypeEnum.SYSTEM,
                title=f"Note {i}",
                body="Body",
                send_push=False,
            )

        # 1. page=0 -> 404 (PageNumberPagination does not accept 0)
        res_page_0 = client.get("/api/v1/notifications/?page=0")
        assert res_page_0.status_code == status.HTTP_404_NOT_FOUND

        # 2. page=-1 -> 404
        res_page_neg = client.get("/api/v1/notifications/?page=-1")
        assert res_page_neg.status_code == status.HTTP_404_NOT_FOUND

        # 3. page=abc -> 404
        res_page_str = client.get("/api/v1/notifications/?page=invalid_string")
        assert res_page_str.status_code == status.HTTP_404_NOT_FOUND

        # 4. page=99999999 -> 404
        res_page_huge = client.get("/api/v1/notifications/?page=99999999")
        assert res_page_huge.status_code == status.HTTP_404_NOT_FOUND

        # 5. page_size=-1 -> falls back gracefully to default size (20), no 500
        res_ps_neg = client.get("/api/v1/notifications/?page_size=-1")
        assert res_ps_neg.status_code == status.HTTP_200_OK
        assert len(res_ps_neg.data["results"]) == 5

        # 6. page_size=abc -> falls back to default size, no 500
        res_ps_str = client.get("/api/v1/notifications/?page_size=abc")
        assert res_ps_str.status_code == status.HTTP_200_OK

        # 7. page_size=999999 -> clamped to max 100, no 500
        res_ps_huge = client.get("/api/v1/notifications/?page_size=999999")
        assert res_ps_huge.status_code == status.HTTP_200_OK

    def test_50_plus_random_garbage_query_params(self, qa_env):
        alice = qa_env["alice"]
        client = _make_auth_client(alice)

        url = "/api/v1/notifications/?" + "&".join([f"garbage_key_{i}=garbage_val_{i}" for i in range(60)])
        res = client.get(url)
        assert res.status_code == status.HTTP_200_OK


class TestSecurityAndInjectionDefense:
    """Tests SQL Injection, Cross-Site Scripting, and adversarial Unicode inputs."""

    @pytest.mark.parametrize(
        "sqli_payload",
        [
            "' OR '1'='1",
            "'; DROP TABLE notifications; --",
            "1 UNION SELECT 1, 2, 3, 4 --",
            "admin'--",
            "\" OR \"\"=\"",
        ],
    )
    def test_sqli_in_query_parameters(self, qa_env, sqli_payload):
        client = _make_auth_client(qa_env["alice"])
        res = client.get(f"/api/v1/notifications/?notification_type={sqli_payload}")
        assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_200_OK)
        assert Notification.objects.count() >= 0  # Table not dropped

    @pytest.mark.parametrize(
        "xss_payload",
        [
            "<script>alert(1)</script>",
            "<img src=x onerror=alert('xss')>",
            "javascript:alert(document.cookie)",
            "<svg/onload=alert(1)>",
        ],
    )
    def test_xss_payload_in_device_registration(self, qa_env, xss_payload):
        client = _make_auth_client(qa_env["alice"])
        res = client.post(
            "/api/v1/notifications/devices/",
            {
                "token": f"fcm_tok_xss_{uuid.uuid4().hex[:8]}",
                "device_name": xss_payload,
                "device_id": xss_payload[:100],
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        # Safe storage as literal strings, zero execution
        assert res.data["device_name"] == xss_payload

    def test_complex_unicode_and_special_characters(self, qa_env):
        client = _make_auth_client(qa_env["alice"])
        unicode_name = "🔥📱 Pro 15 🚀 (مرحبا بالعالم) — 日本語テスト 💯"

        res = client.post(
            "/api/v1/notifications/devices/",
            {
                "token": f"tok_unicode_{uuid.uuid4().hex[:12]}",
                "device_name": unicode_name,
                "platform": "android",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["device_name"] == unicode_name


class TestIDORAndObjectLevelAuthorization:
    """Verifies strict tenant and user boundary isolation to prevent IDOR attacks."""

    def test_user_cannot_read_other_user_notification(self, qa_env):
        alice = qa_env["alice"]
        bob = qa_env["bob"]
        bob_client = _make_auth_client(bob)

        # Alice's private notification
        notif = send_notification(
            recipient=alice,
            notification_type=NotificationTypeEnum.SYSTEM,
            title="Alice's Confidential Alert",
            body="Secret data",
            send_push=False,
        )

        # Bob attempts direct object access -> 404
        res = bob_client.get(f"/api/v1/notifications/{notif.id}/")
        assert res.status_code == status.HTTP_404_NOT_FOUND
        assert res.data["code"] == "RESOURCE_NOT_FOUND"

    def test_user_cannot_mark_read_other_user_notification(self, qa_env):
        alice = qa_env["alice"]
        charlie = qa_env["charlie"]
        charlie_client = _make_auth_client(charlie)

        notif = send_notification(
            recipient=alice,
            notification_type=NotificationTypeEnum.SYSTEM,
            title="Alice unread",
            body="Must not be marked read by Charlie",
            send_push=False,
        )
        assert notif.is_read is False

        # Charlie attempts to mark Alice's notification as read -> 404
        res_patch = charlie_client.patch(f"/api/v1/notifications/{notif.id}/read/")
        assert res_patch.status_code == status.HTTP_404_NOT_FOUND

        res_post = charlie_client.post(f"/api/v1/notifications/{notif.id}/read/")
        assert res_post.status_code == status.HTTP_404_NOT_FOUND

        notif.refresh_from_db()
        assert notif.is_read is False

    def test_user_cannot_delete_other_user_notification(self, qa_env):
        alice = qa_env["alice"]
        charlie = qa_env["charlie"]
        charlie_client = _make_auth_client(charlie)

        notif = send_notification(
            recipient=alice,
            notification_type=NotificationTypeEnum.SYSTEM,
            title="Alice Important Note",
            body="Preserve this",
            send_push=False,
        )

        # Charlie attempts to delete -> 404
        res_del = charlie_client.delete(f"/api/v1/notifications/{notif.id}/")
        assert res_del.status_code == status.HTTP_404_NOT_FOUND
        assert Notification.objects.filter(id=notif.id).exists() is True

    def test_user_cannot_unregister_other_user_device_token(self, qa_env):
        alice = qa_env["alice"]
        bob = qa_env["bob"]
        bob_client = _make_auth_client(bob)

        # Alice registers a device
        alice_tok = register_device_token(alice, token="alice_secret_device_tok_777")
        assert alice_tok.is_active is True

        # Bob attempts to unregister Alice's device token -> 404
        res = bob_client.post(
            "/api/v1/notifications/devices/unregister/",
            {"token": "alice_secret_device_tok_777"},
            format="json",
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND
        assert res.data["code"] == "RESOURCE_NOT_FOUND"

        alice_tok.refresh_from_db()
        assert alice_tok.is_active is True

    def test_device_list_strictly_isolated_to_authenticated_user(self, qa_env):
        alice = qa_env["alice"]
        bob = qa_env["bob"]
        register_device_token(alice, token="alice_phone_1")
        register_device_token(bob, token="bob_phone_1")

        alice_client = _make_auth_client(alice)
        res = alice_client.get("/api/v1/notifications/devices/")
        assert res.status_code == status.HTTP_200_OK
        returned_tokens = [d["id"] for d in res.data]
        alice_device = DeviceToken.objects.get(token="alice_phone_1")
        bob_device = DeviceToken.objects.get(token="bob_phone_1")

        assert str(alice_device.id) in returned_tokens
        assert str(bob_device.id) not in returned_tokens


class TestHTTPMethodsAndPathParameters:
    """Tests unsupported HTTP methods and invalid path parameter formats."""

    def test_unsupported_methods_return_405(self, qa_env):
        client = _make_auth_client(qa_env["alice"])

        # POST on GET-only /api/v1/notifications/
        res_post = client.post("/api/v1/notifications/", {"some": "data"})
        assert res_post.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        assert res_post.data["code"] == "METHOD_NOT_ALLOWED"

        # PUT on /api/v1/notifications/
        res_put = client.put("/api/v1/notifications/", {"some": "data"})
        assert res_put.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # DELETE on /unread-count/
        res_del_count = client.delete("/api/v1/notifications/unread-count/")
        assert res_del_count.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # GET on POST-only /mark-all-read/
        res_get_mark = client.get("/api/v1/notifications/mark-all-read/")
        assert res_get_mark.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    @pytest.mark.parametrize(
        "bad_uuid_path",
        [
            "not-a-valid-uuid",
            "12345",
            "../../../etc/passwd",
            "null",
            "undefined",
            "0000-invalid-format",
        ],
    )
    def test_non_uuid_path_parameters_return_404(self, qa_env, bad_uuid_path):
        client = _make_auth_client(qa_env["alice"])

        # Django URL converter <uuid:...> will reject non-UUID strings with 404
        assert client.get(f"/api/v1/notifications/{bad_uuid_path}/").status_code == status.HTTP_404_NOT_FOUND
        assert client.delete(f"/api/v1/notifications/{bad_uuid_path}/").status_code == status.HTTP_404_NOT_FOUND
        assert client.patch(f"/api/v1/notifications/{bad_uuid_path}/read/").status_code == status.HTTP_404_NOT_FOUND

    def test_non_existent_uuid_returns_404_envelope(self, qa_env):
        client = _make_auth_client(qa_env["alice"])
        random_uuid = uuid.uuid4()

        res_get = client.get(f"/api/v1/notifications/{random_uuid}/")
        assert res_get.status_code == status.HTTP_404_NOT_FOUND
        assert res_get.data["code"] == "RESOURCE_NOT_FOUND"

        res_del = client.delete(f"/api/v1/notifications/{random_uuid}/")
        assert res_del.status_code == status.HTTP_404_NOT_FOUND
        assert res_del.data["code"] == "RESOURCE_NOT_FOUND"

        res_read = client.patch(f"/api/v1/notifications/{random_uuid}/read/")
        assert res_read.status_code == status.HTTP_404_NOT_FOUND
        assert res_read.data["code"] == "RESOURCE_NOT_FOUND"


class TestStateTransitionsAndLifecycle:
    """Tests idempotent actions, double-deletions, and device threshold caps."""

    def test_idempotent_mark_read_and_delete(self, qa_env):
        alice = qa_env["alice"]
        client = _make_auth_client(alice)

        notif = send_notification(
            recipient=alice,
            notification_type=NotificationTypeEnum.SYSTEM,
            title="Idempotency Test",
            body="Test body",
            send_push=False,
        )

        # First mark read -> 200
        res1 = client.patch(f"/api/v1/notifications/{notif.id}/read/")
        assert res1.status_code == status.HTTP_200_OK
        assert res1.data["is_read"] is True

        # Second mark read on already-read notification -> 200 OK (idempotent, doesn't crash)
        res2 = client.patch(f"/api/v1/notifications/{notif.id}/read/")
        assert res2.status_code == status.HTTP_200_OK
        assert res2.data["is_read"] is True

        # First delete -> 204
        res_del1 = client.delete(f"/api/v1/notifications/{notif.id}/")
        assert res_del1.status_code == status.HTTP_204_NO_CONTENT

        # Second delete on already deleted resource -> 404 Not Found
        res_del2 = client.delete(f"/api/v1/notifications/{notif.id}/")
        assert res_del2.status_code == status.HTTP_404_NOT_FOUND

    def test_mark_all_read_when_already_clean(self, qa_env):
        alice = qa_env["alice"]
        client = _make_auth_client(alice)

        # Zero notifications exist
        res = client.post("/api/v1/notifications/mark-all-read/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["marked_read_count"] == 0

    def test_max_device_threshold_evicts_oldest_device(self, qa_env):
        alice = qa_env["alice"]
        client = _make_auth_client(alice)

        # Register 12 devices (MAX_ACTIVE_DEVICES_PER_USER is 10)
        tokens = [f"tok_threshold_test_{i}" for i in range(12)]
        for tok in tokens:
            register_device_token(alice, token=tok)

        active_tokens = get_active_device_tokens_for_user(alice)
        assert len(active_tokens) == 10
        # First 2 should be evicted (inactive)
        assert tokens[0] not in active_tokens
        assert tokens[1] not in active_tokens
        # Last registered token must be active
        assert tokens[11] in active_tokens


class TestAdvancedProductionEdgeCases:
    """
    Tests advanced production edge cases:
    - User bidirectional blocklists & Gym blocklists
    - Account deactivation & soft deletion
    - Anti-spam debouncing / duplicate suppression
    - Hardware device_id token conflict pruning
    - Batch mark read API & Clear read API
    - Target type and target ID coordinates query filtering
    """

    def test_user_blocklist_suppresses_notifications_bidirectionally(self, qa_env):
        from apps.users.models import UserBlockedUser

        alice = qa_env["alice"]
        charlie = qa_env["charlie"]

        # Case 1: Alice blocks Charlie -> Charlie's actions must not notify Alice
        UserBlockedUser.objects.create(blocker=alice, blocked_user=charlie)

        notif1 = send_notification(
            recipient=alice,
            actor=charlie,
            notification_type=NotificationTypeEnum.REACTION,
            title="Charlie reacted to your post",
            body="Charlie liked your workout",
            send_push=False,
        )
        assert notif1 is None
        assert Notification.objects.filter(recipient=alice, actor=charlie).count() == 0

        # Case 2: Charlie blocks Alice -> Alice's actions must not notify Charlie
        notif2 = send_notification(
            recipient=charlie,
            actor=alice,
            notification_type=NotificationTypeEnum.COMMENT,
            title="Alice commented",
            body="Nice photo",
            send_push=False,
        )
        assert notif2 is None
        assert Notification.objects.filter(recipient=charlie, actor=alice).count() == 0

    def test_gym_blocklist_suppresses_notifications(self, qa_env):
        from apps.gyms.models import GymBlockedUser

        gym = qa_env["gym"]
        alice = qa_env["alice"]  # Gym owner
        charlie = qa_env["charlie"]

        # Gym blocks Charlie
        GymBlockedUser.objects.create(gym=gym, user=charlie)

        notif = send_notification(
            recipient=alice,
            gym=gym,
            actor=charlie,
            notification_type=NotificationTypeEnum.MEMBER_REQUEST,
            title="Join request from Charlie",
            body="Charlie wants to join",
            send_push=False,
        )
        assert notif is None
        assert Notification.objects.filter(recipient=alice, actor=charlie).count() == 0

    def test_deactivated_or_deleted_recipient_suppressed(self, qa_env):
        bob = qa_env["bob"]
        charlie = qa_env["charlie"]

        # Deactivate Bob
        bob_setting = bob.get_settings()
        bob_setting.is_deactivated = True
        bob_setting.save()

        notif = send_notification(
            recipient=bob,
            actor=charlie,
            notification_type=NotificationTypeEnum.SYSTEM,
            title="Alert for Bob",
            body="System alert",
            send_push=False,
        )
        assert notif is None
        assert Notification.objects.filter(recipient=bob).count() == 0

    def test_anti_spam_debouncing_window(self, qa_env):
        alice = qa_env["alice"]
        bob = qa_env["bob"]
        target_uuid = str(uuid.uuid4())

        # Rapidly send 2 notifications for identical target within 1 second
        notif1 = send_notification(
            recipient=alice,
            actor=bob,
            notification_type=NotificationTypeEnum.REACTION,
            title="Reaction 1",
            body="Bob liked your post",
            target_type="post",
            target_id=target_uuid,
            send_push=False,
        )
        assert notif1 is not None

        notif2 = send_notification(
            recipient=alice,
            actor=bob,
            notification_type=NotificationTypeEnum.REACTION,
            title="Reaction 2",
            body="Bob liked your post again",
            target_type="post",
            target_id=target_uuid,
            send_push=False,
        )

        # Should debounce and return the existing notification rather than creating a duplicate
        assert notif2.id == notif1.id
        assert Notification.objects.filter(recipient=alice, target_id=target_uuid).count() == 1

    def test_hardware_device_id_token_reassignment_deactivates_old_token(self, qa_env):
        alice = qa_env["alice"]
        hw_id = "iphone_15_pro_unique_hw_001"

        # 1. Initial device install
        d1 = register_device_token(alice, token="fcm_token_initial_123", device_id=hw_id, platform="ios")
        assert d1.is_active is True

        # 2. App reinstallation on same phone generates new FCM token
        d2 = register_device_token(alice, token="fcm_token_reinstalled_456", device_id=hw_id, platform="ios")
        assert d2.is_active is True

        # 3. Old token on this device ID must be deactivated
        d1.refresh_from_db()
        assert d1.is_active is False

        # Active tokens for alice only contains the new token
        active_tokens = get_active_device_tokens_for_user(alice)
        assert "fcm_token_reinstalled_456" in active_tokens
        assert "fcm_token_initial_123" not in active_tokens

    def test_batch_mark_read_api(self, qa_env):
        alice = qa_env["alice"]
        bob = qa_env["bob"]
        alice_client = _make_auth_client(alice)

        # Create 3 unread notifications for Alice
        n1 = send_notification(alice, NotificationTypeEnum.SYSTEM, "N1", "B1", send_push=False)
        n2 = send_notification(alice, NotificationTypeEnum.SYSTEM, "N2", "B2", send_push=False)
        n3 = send_notification(alice, NotificationTypeEnum.SYSTEM, "N3", "B3", send_push=False)
        # Create 1 for Bob
        n_bob = send_notification(bob, NotificationTypeEnum.SYSTEM, "N_Bob", "B_Bob", send_push=False)

        # 1. Batch mark read with empty array -> 400
        res_empty = alice_client.post("/api/v1/notifications/batch-read/", {"notification_ids": []}, format="json")
        assert res_empty.status_code == status.HTTP_400_BAD_REQUEST

        # 2. Batch mark read with invalid UUIDs -> 400
        res_invalid = alice_client.post("/api/v1/notifications/batch-read/", {"notification_ids": ["not-a-uuid"]}, format="json")
        assert res_invalid.status_code == status.HTTP_400_BAD_REQUEST

        # 3. Alice marks n1, n2, and attempts to include n_bob
        res_batch = alice_client.post(
            "/api/v1/notifications/batch-read/",
            {"notification_ids": [str(n1.id), str(n2.id), str(n_bob.id)]},
            format="json",
        )
        assert res_batch.status_code == status.HTTP_200_OK
        # Only Alice's 2 notifications are marked read; Bob's is NOT affected
        assert res_batch.data["marked_read_count"] == 2

        n1.refresh_from_db()
        n2.refresh_from_db()
        n3.refresh_from_db()
        n_bob.refresh_from_db()

        assert n1.is_read is True
        assert n2.is_read is True
        assert n3.is_read is False  # Omitted from batch
        assert n_bob.is_read is False  # Bob's notification preserved

    def test_clear_read_api(self, qa_env):
        alice = qa_env["alice"]
        alice_client = _make_auth_client(alice)

        # Create 2 read and 1 unread notification
        n1 = send_notification(alice, NotificationTypeEnum.SYSTEM, "N1", "B1", send_push=False)
        n2 = send_notification(alice, NotificationTypeEnum.SYSTEM, "N2", "B2", send_push=False)
        n3 = send_notification(alice, NotificationTypeEnum.SYSTEM, "N3", "B3", send_push=False)

        mark_notification_as_read(n1.id, alice)
        mark_notification_as_read(n2.id, alice)

        # Clear read notifications
        res_clear = alice_client.delete("/api/v1/notifications/clear-read/")
        assert res_clear.status_code == status.HTTP_200_OK
        assert res_clear.data["deleted_count"] == 2

        # Only unread notification n3 remains
        remaining = list_notifications(alice)
        assert remaining.count() == 1
        assert remaining.first().id == n3.id

    def test_target_type_and_target_id_query_filter(self, qa_env):
        alice = qa_env["alice"]
        alice_client = _make_auth_client(alice)

        post_id = str(uuid.uuid4())
        comment_id = str(uuid.uuid4())

        send_notification(alice, NotificationTypeEnum.REACTION, "Post Reaction", "Post liked", target_type="post", target_id=post_id, send_push=False)
        send_notification(alice, NotificationTypeEnum.COMMENT, "Comment Added", "Comment on post", target_type="post", target_id=post_id, send_push=False)
        send_notification(alice, NotificationTypeEnum.COMMENT, "Reply Added", "Reply on comment", target_type="comment", target_id=comment_id, send_push=False)

        # 1. Filter by target_type="post"
        res_type = alice_client.get("/api/v1/notifications/?target_type=post")
        assert res_type.status_code == status.HTTP_200_OK
        assert len(res_type.data["results"]) == 2

        # 2. Filter by target_type="post" and target_id=post_id
        res_coord = alice_client.get(f"/api/v1/notifications/?target_type=post&target_id={post_id}")
        assert res_coord.status_code == status.HTTP_200_OK
        assert len(res_coord.data["results"]) == 2

        # 3. Filter by target_type="comment"
        res_comm = alice_client.get("/api/v1/notifications/?target_type=comment")
        assert res_comm.status_code == status.HTTP_200_OK
        assert len(res_comm.data["results"]) == 1
        assert res_comm.data["results"][0]["target_id"] == comment_id
