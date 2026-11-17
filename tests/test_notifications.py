import uuid
from unittest.mock import MagicMock, patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.access_control.models import Role
from apps.access_control.services import (
    invite_staff_member,
    seed_default_permissions_and_roles,
)
from apps.authentication.services import issue_context_token
from apps.gyms.models import Gym, GymSetting
from apps.members.models import MemberRequest
from apps.members.services.request_services import (
    accept_member_request,
    create_member_request,
    reject_member_request,
)
from apps.messaging.services import (
    initiate_conversation,
    send_encrypted_message,
)
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
from apps.posts.models import GymPost
from apps.posts.services import create_comment, create_post
from apps.reactions.models import ReactionItem
from apps.reactions.services import seed_default_reaction_items, toggle_or_set_reaction
from apps.users.models import User
from common.enums import (
    ConversationTypeEnum,
    DevicePlatformEnum,
    MessageSenderTypeEnum,
    NotificationTypeEnum,
    PostOwnerTypeEnum,
    PostPrivacyEnum,
    TokenContextType,
)
from integrations.fcm import FCMClient, FCMNotificationResult


def _auth_client(user: User, context_type=TokenContextType.PERSONAL, gym=None) -> APIClient:
    token = issue_context_token(user=user, context_type=context_type, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def notif_env(db):
    seed_default_permissions_and_roles()
    seed_default_reaction_items()

    alice = User.objects.create_user(
        email="alice_notif@example.com",
        password="Password123!",
        first_name="Alice",
        last_name="Tester",
    )
    bob = User.objects.create_user(
        email="bob_notif@example.com",
        password="Password123!",
        first_name="Bob",
        last_name="Builder",
    )
    gym_owner = User.objects.create_user(
        email="owner_notif@example.com",
        password="Password123!",
        first_name="Gym",
        last_name="Owner",
    )

    gym = Gym.objects.create(
        name="Universal Fitness",
        owner_user=gym_owner,
    )
    GymSetting.objects.create(
        gym=gym,
        who_can_send_joining_request="everyone",
    )

    return {
        "alice": alice,
        "bob": bob,
        "gym_owner": gym_owner,
        "gym": gym,
    }


class TestDeviceTokenManagement:
    """Tests client device token registration, lookup, and unregistration."""

    def test_register_device_token_service_and_api(self, notif_env):
        alice = notif_env["alice"]
        client = _auth_client(alice)

        # 1. API Registration
        res = client.post(
            "/api/v1/notifications/devices/",
            {
                "token": "fcm_token_alice_iphone_123",
                "device_id": "device_ios_01",
                "device_name": "iPhone 15 Pro",
                "platform": "ios",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["device_id"] == "device_ios_01"
        assert res.data["platform"] == "ios"
        assert res.data["is_active"] is True

        # 2. Check selector
        tokens = get_active_device_tokens_for_user(alice)
        assert "fcm_token_alice_iphone_123" in tokens

        # 3. List devices via API
        list_res = client.get("/api/v1/notifications/devices/")
        assert list_res.status_code == status.HTTP_200_OK
        assert len(list_res.data) == 1

        # 4. Re-registering existing token updates last_seen and keeps active
        res2 = client.post(
            "/api/v1/notifications/devices/",
            {
                "token": "fcm_token_alice_iphone_123",
                "device_name": "iPhone 15 Pro Max",
                "platform": "ios",
            },
            format="json",
        )
        assert res2.status_code == status.HTTP_201_CREATED
        assert DeviceToken.objects.filter(user=alice).count() == 1

        # 5. Unregister token
        unreg_res = client.post(
            "/api/v1/notifications/devices/unregister/",
            {"token": "fcm_token_alice_iphone_123"},
            format="json",
        )
        assert unreg_res.status_code == status.HTTP_200_OK
        assert unreg_res.data["unregistered"] is True

        # Ensure token is now deactivated
        active_tokens = get_active_device_tokens_for_user(alice)
        assert "fcm_token_alice_iphone_123" not in active_tokens


class TestUniversalNotificationDispatcher:
    """Tests universal notification sending, reading, filtering, and deletion."""

    def test_send_notification_creates_db_record_and_broadcasts(self, notif_env):
        alice = notif_env["alice"]
        bob = notif_env["bob"]

        notif = send_notification(
            recipient=alice,
            actor=bob,
            notification_type=NotificationTypeEnum.SYSTEM,
            title="Welcome to ManyGym",
            body="Your registration is complete.",
            target_type="system",
            target_id="sys_1",
            send_push=False,
        )

        assert notif is not None
        assert notif.recipient == alice
        assert notif.actor == bob
        assert notif.title == "Welcome to ManyGym"
        assert notif.is_read is False

    def test_self_notification_suppression(self, notif_env):
        alice = notif_env["alice"]

        # Actor == Recipient should be suppressed
        notif = send_notification(
            recipient=alice,
            actor=alice,
            notification_type=NotificationTypeEnum.REACTION,
            title="You reacted to yourself",
            body="Self reaction",
            send_push=False,
        )
        assert notif is None
        assert Notification.objects.filter(recipient=alice).count() == 0

    def test_list_notifications_and_unread_count_api(self, notif_env):
        alice = notif_env["alice"]
        bob = notif_env["bob"]
        client = _auth_client(alice)

        # Create 3 notifications
        for i in range(3):
            send_notification(
                recipient=alice,
                actor=bob,
                notification_type=NotificationTypeEnum.REACTION if i == 0 else NotificationTypeEnum.COMMENT,
                title=f"Notification #{i}",
                body=f"Body #{i}",
                send_push=False,
            )

        # 1. Unread count endpoint
        count_res = client.get("/api/v1/notifications/unread-count/")
        assert count_res.status_code == status.HTTP_200_OK
        assert count_res.data["unread_count"] == 3

        # 2. List notifications endpoint
        list_res = client.get("/api/v1/notifications/")
        assert list_res.status_code == status.HTTP_200_OK
        assert list_res.data["count"] == 3
        first_id = list_res.data["results"][0]["id"]

        # 3. Filter by type
        filter_res = client.get("/api/v1/notifications/?notification_type=reaction")
        assert filter_res.status_code == status.HTTP_200_OK
        assert filter_res.data["count"] == 1

        # 4. Mark single notification as read
        patch_res = client.patch(f"/api/v1/notifications/{first_id}/read/")
        assert patch_res.status_code == status.HTTP_200_OK
        assert patch_res.data["is_read"] is True

        # Unread count should now be 2
        count_res2 = client.get("/api/v1/notifications/unread-count/")
        assert count_res2.data["unread_count"] == 2

        # 5. Mark all as read
        mark_all_res = client.post("/api/v1/notifications/mark-all-read/")
        assert mark_all_res.status_code == status.HTTP_200_OK
        assert mark_all_res.data["marked_read_count"] == 2

        count_res3 = client.get("/api/v1/notifications/unread-count/")
        assert count_res3.data["unread_count"] == 0

        # 6. Delete notification
        del_res = client.delete(f"/api/v1/notifications/{first_id}/")
        assert del_res.status_code == status.HTTP_204_NO_CONTENT
        assert Notification.objects.filter(id=first_id).exists() is False


class TestMessagePushNotificationSeparation:
    """
    CRITICAL REQUIREMENT:
    Message notification does NOT store generic in-app notification rows in DB;
    it ONLY dispatches the realtime FCM push notification.
    """

    def test_message_notification_does_not_create_notification_row(self, notif_env):
        alice = notif_env["alice"]
        bob = notif_env["bob"]

        # Register device for alice
        register_device_token(alice, token="fcm_token_alice_msg_test")

        initial_notif_count = Notification.objects.count()

        # Send message push notification
        with patch.object(FCMClient, "send_multicast", return_value=FCMNotificationResult(success_count=1)) as mock_send:
            send_message_push_notification(
                recipient_user=alice,
                title="Bob Builder",
                body="Sent you an encrypted message.",
                data={
                    "conversation_id": str(uuid.uuid4()),
                    "sender_type": "user",
                },
            )

        # Database record must NOT be created
        assert Notification.objects.count() == initial_notif_count


class TestNotificationIntegrationTriggers:
    """Verifies that reactions, comments, member requests, and gym invites trigger notifications."""

    def test_reaction_triggers_notification_for_post_author(self, notif_env):
        alice = notif_env["alice"]
        bob = notif_env["bob"]

        # Alice creates a post
        post = create_post(
            author_user=alice,
            content_text="My workout progress!",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        # Bob reacts to Alice's post
        reaction_item = ReactionItem.objects.first()
        toggle_or_set_reaction(
            actor_user=bob,
            post_id=post.id,
            reaction_code=reaction_item.code,
        )

        # Verify Alice received notification
        notif = Notification.objects.filter(recipient=alice, notification_type=NotificationTypeEnum.REACTION).first()
        assert notif is not None
        assert notif.actor == bob
        assert notif.target_id == str(post.id)
        assert reaction_item.emoji in notif.body

    def test_comment_and_reply_triggers_notification(self, notif_env):
        alice = notif_env["alice"]
        bob = notif_env["bob"]

        post = create_post(
            author_user=alice,
            content_text="Leg day check in",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        # Bob comments on Alice's post
        comment = create_comment(
            actor_user=bob,
            source_post_id=post.id,
            comment_text="Great form keep it up!",
        )

        # Alice should have received a comment notification
        notif = Notification.objects.filter(recipient=alice, notification_type=NotificationTypeEnum.COMMENT).first()
        assert notif is not None
        assert notif.actor == bob
        assert "commented on your post" in notif.title

        # Alice replies to Bob's comment
        reply = create_comment(
            actor_user=alice,
            source_comment_id=comment.id,
            comment_text="Thank you Bob!",
        )

        # Bob should receive a reply notification
        reply_notif = Notification.objects.filter(recipient=bob, notification_type=NotificationTypeEnum.COMMENT_REPLY).first()
        assert reply_notif is not None
        assert reply_notif.actor == alice
        assert "replied to your comment" in reply_notif.title

    def test_member_request_triggers_notifications(self, notif_env):
        alice = notif_env["alice"]
        gym_owner = notif_env["gym_owner"]
        gym = notif_env["gym"]

        # Alice sends request to join gym
        req_data = create_member_request(user=alice, gym_id=gym.id)
        req_id = req_data["request_id"]

        # Gym owner receives member_request notification
        owner_notif = Notification.objects.filter(
            recipient=gym_owner,
            notification_type=NotificationTypeEnum.MEMBER_REQUEST,
        ).first()
        assert owner_notif is not None
        assert owner_notif.actor == alice
        assert "requested to join" in owner_notif.body

        # Gym owner accepts member request
        accept_member_request(
            request_id=req_id,
            gym=gym,
            reviewer=gym_owner,
        )

        # Alice receives member_request_accepted notification
        alice_notif = Notification.objects.filter(
            recipient=alice,
            notification_type=NotificationTypeEnum.MEMBER_REQUEST_ACCEPTED,
        ).first()
        assert alice_notif is not None
        assert "approved" in alice_notif.body

    def test_gym_staff_invite_triggers_notification(self, notif_env):
        bob = notif_env["bob"]
        gym = notif_env["gym"]
        role = Role.objects.filter(name="Staff").first()
        if not role:
            role = Role.objects.create(name="Staff", is_system_default=True)

        # Invite Bob to gym staff
        invite_staff_member(gym=gym, user_email=bob.email, role_id=str(role.id))

        # Bob receives gym_invite notification
        invite_notif = Notification.objects.filter(
            recipient=bob,
            notification_type=NotificationTypeEnum.GYM_INVITE,
        ).first()
        assert invite_notif is not None
        assert gym.name in invite_notif.body


class TestNotificationSecurityAndEdgeCases:
    """Tests security, permissions, and validation edge cases."""

    def test_unauthenticated_requests_are_rejected(self):
        client = APIClient()
        assert client.get("/api/v1/notifications/").status_code == status.HTTP_401_UNAUTHORIZED
        assert client.get("/api/v1/notifications/unread-count/").status_code == status.HTTP_401_UNAUTHORIZED
        assert client.post("/api/v1/notifications/mark-all-read/").status_code == status.HTTP_401_UNAUTHORIZED
        assert client.get("/api/v1/notifications/devices/").status_code == status.HTTP_401_UNAUTHORIZED
        assert client.post("/api/v1/notifications/devices/", {"token": "xyz"}).status_code == status.HTTP_401_UNAUTHORIZED

    def test_user_cannot_access_or_mutate_other_user_notification(self, notif_env):
        alice = notif_env["alice"]
        bob = notif_env["bob"]
        bob_client = _auth_client(bob)

        # Notification belongs to Alice
        notif = send_notification(
            recipient=alice,
            actor=None,
            notification_type=NotificationTypeEnum.SYSTEM,
            title="Private Alice Alert",
            body="Only Alice should see this",
            send_push=False,
        )

        # Bob attempts to read Alice's notification -> 404
        get_res = bob_client.get(f"/api/v1/notifications/{notif.id}/")
        assert get_res.status_code == status.HTTP_404_NOT_FOUND

        # Bob attempts to mark read Alice's notification -> 404
        read_res = bob_client.patch(f"/api/v1/notifications/{notif.id}/read/")
        assert read_res.status_code == status.HTTP_404_NOT_FOUND

        # Bob attempts to delete Alice's notification -> 404
        del_res = bob_client.delete(f"/api/v1/notifications/{notif.id}/")
        assert del_res.status_code == status.HTTP_404_NOT_FOUND
        assert Notification.objects.filter(id=notif.id).exists() is True

    def test_empty_token_registration_validation(self, notif_env):
        alice = notif_env["alice"]
        client = _auth_client(alice)

        res = client.post(
            "/api/v1/notifications/devices/",
            {"token": ""},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST


class TestNotificationAsyncTasksAndFCM:
    """Tests Celery background task processing and token invalidation."""

    def test_send_push_notification_task_deactivates_stale_tokens(self, notif_env):
        from apps.notifications.tasks import send_push_notification_task

        alice = notif_env["alice"]
        token_obj = register_device_token(alice, token="dead_fcm_token_123")
        assert token_obj.is_active is True

        mock_result = FCMNotificationResult(
            success_count=0,
            failure_count=1,
            failed_tokens=["dead_fcm_token_123"],
            deactivated_tokens=["dead_fcm_token_123"],
        )

        with patch.object(FCMClient, "send_multicast", return_value=mock_result):
            res = send_push_notification_task(
                recipient_id=str(alice.id),
                title="Ping",
                body="Test",
            )

        assert res["deactivated_tokens"] == ["dead_fcm_token_123"]
        token_obj.refresh_from_db()
        assert token_obj.is_active is False

