import pytest
from rest_framework import status
from rest_framework.test import APIClient
from channels.testing import WebsocketCommunicator

from apps.users.models import User
from apps.gyms.models import Gym, GymBlockedUser, GymSetting
from apps.gyms.services import create_gym
from apps.members.models import Member
from apps.access_control.models import GymStaffAssignment, Role
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    AudienceMessagingEnum,
    StaffStatus,
    ConversationTypeEnum,
    MessageSenderTypeEnum,
    MessageDeliveryStatusEnum,
)
from apps.messaging.crypto import (
    generate_x25519_keypair,
    generate_ed25519_keypair,
    sign_prekey,
    verify_signed_prekey,
    hybrid_encrypt,
    hybrid_decrypt,
    calculate_key_fingerprint,
)
from apps.messaging.models import (
    UserDeviceKey,
    GymDeviceKey,
    Conversation,
    ConversationParticipant,
    EncryptedMessage,
)
from apps.messaging.consumers import ChatConsumer


@pytest.fixture
def alice(db):
    return User.objects.create_user(
        email="alice@example.com",
        password="Password123!",
        first_name="Alice",
        last_name="Smith",
        is_verified=True,
    )


@pytest.fixture
def bob(db):
    return User.objects.create_user(
        email="bob@example.com",
        password="Password123!",
        first_name="Bob",
        last_name="Johnson",
        is_verified=True,
    )


@pytest.fixture
def charlie(db):
    return User.objects.create_user(
        email="charlie@example.com",
        password="Password123!",
        first_name="Charlie",
        last_name="Brown",
        is_verified=True,
    )


@pytest.fixture
def gym_a(alice):
    return create_gym(owner_user=alice, name="Olympus Gym")


@pytest.fixture
def gym_b(bob):
    return create_gym(owner_user=bob, name="Spartan Fitness")


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


@pytest.mark.django_db
class TestE2EECryptography:
    """Tests the mathematical correctness and tamper-resistance of the E2EE crypto module."""

    def test_keypair_generation_and_signatures(self):
        priv_bytes, pub_b64 = generate_x25519_keypair()
        assert len(priv_bytes) == 32
        assert len(pub_b64) > 20

        ed_priv, ed_pub = generate_ed25519_keypair()
        sig = sign_prekey(ed_priv, pub_b64)
        assert verify_signed_prekey(ed_pub, pub_b64, sig) is True
        assert verify_signed_prekey(ed_pub, pub_b64, "invalid_sig==") is False

    def test_hybrid_encryption_decryption_roundtrip(self):
        bob_priv_bytes, bob_pub_b64 = generate_x25519_keypair()

        plaintext = "Hello Bob! Secret workout plan: 5x5 squats @ 140kg."
        encrypted_payload = hybrid_encrypt(
            recipient_public_key_b64=bob_pub_b64,
            plaintext=plaintext,
        )

        assert "ciphertext" in encrypted_payload
        assert "nonce" in encrypted_payload
        assert "ephemeral_public_key" in encrypted_payload

        # Bob decrypts with Bob's private key
        decrypted = hybrid_decrypt(
            recipient_private_bytes=bob_priv_bytes,
            ephemeral_public_key_b64=encrypted_payload["ephemeral_public_key"],
            ciphertext_b64=encrypted_payload["ciphertext"],
            nonce_b64=encrypted_payload["nonce"],
        )
        assert decrypted == plaintext

    def test_decryption_with_wrong_key_fails(self):
        _, bob_pub_b64 = generate_x25519_keypair()
        eve_priv_bytes, _ = generate_x25519_keypair()

        encrypted_payload = hybrid_encrypt(
            recipient_public_key_b64=bob_pub_b64,
            plaintext="Confidential financial report",
        )

        with pytest.raises(Exception):
            hybrid_decrypt(
                recipient_private_bytes=eve_priv_bytes,
                ephemeral_public_key_b64=encrypted_payload["ephemeral_public_key"],
                ciphertext_b64=encrypted_payload["ciphertext"],
                nonce_b64=encrypted_payload["nonce"],
            )


@pytest.mark.django_db
class TestDeviceKeyRegistryAPI:
    """Tests registration and retrieval of public key bundles for clients."""

    def test_register_and_retrieve_user_device_key(self, alice_client, alice):
        priv_bytes, pub_b64 = generate_x25519_keypair()
        ed_priv, ed_pub = generate_ed25519_keypair()
        sig = sign_prekey(ed_priv, pub_b64)

        payload = {
            "device_id": "alice-iphone-15",
            "device_name": "Alice iPhone",
            "identity_key": ed_pub,
            "signed_prekey": pub_b64,
            "signed_prekey_signature": sig,
            "one_time_prekeys": ["opk1==", "opk2=="],
        }

        res = alice_client.post("/api/v1/messaging/keys/register/", payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["device_id"] == "alice-iphone-15"

        # Lookup by Bob
        bundle_res = alice_client.get(f"/api/v1/messaging/keys/user/{alice.id}/")
        assert bundle_res.status_code == status.HTTP_200_OK
        devices = bundle_res.data["devices"]
        assert len(devices) == 1
        assert devices[0]["device_id"] == "alice-iphone-15"
        assert devices[0]["signed_prekey"] == pub_b64

    def test_register_and_retrieve_gym_device_key(self, alice_client, gym_a):
        priv_bytes, pub_b64 = generate_x25519_keypair()

        payload = {
            "gym_id": str(gym_a.id),
            "device_id": "gym-a-terminal-01",
            "device_name": "Front Desk Reception",
            "identity_key": "gym_identity_key==",
            "signed_prekey": pub_b64,
            "signed_prekey_signature": "sig==",
        }

        res = alice_client.post("/api/v1/messaging/keys/gym/register/", payload, format="json")
        assert res.status_code == status.HTTP_200_OK

        # Retrieve gym key bundle
        get_res = alice_client.get(f"/api/v1/messaging/keys/gym/{gym_a.id}/")
        assert get_res.status_code == status.HTTP_200_OK
        devices = get_res.data["devices"]
        assert len(devices) == 1
        assert devices[0]["device_id"] == "gym-a-terminal-01"


@pytest.mark.django_db
class TestUserToUserMessaging:
    """Tests 1-on-1 Manygym user to Manygym user encrypted messaging flow."""

    def test_user_to_user_conversation_and_message_delivery(self, alice_client, bob_client, alice, bob):
        # 1. Alice creates conversation with Bob
        res = alice_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "user_to_user",
                "target_user_id": str(bob.id),
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        conv_id = res.data["id"]

        # Idempotent re-creation returns same conversation
        re_res = bob_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "user_to_user",
                "target_user_id": str(alice.id),
            },
            format="json",
        )
        assert re_res.status_code == status.HTTP_201_CREATED
        assert re_res.data["id"] == conv_id

        # 2. Alice sends an encrypted message
        msg_res = alice_client.post(
            f"/api/v1/messaging/conversations/{conv_id}/messages/",
            {
                "ciphertext": "aGVsbG8gd29ybGQgZW5jcnlwdGVkIQ==",
                "nonce": "bm9uY2V2YWx1ZQ==",
                "ephemeral_public_key": "ZXBoZW1lcmFsX2tleQ==",
                "recipient_key_fingerprint": "f1a2b3c4d5e6f7a8",
                "sender_device_id": "alice-device-1",
            },
            format="json",
        )
        assert msg_res.status_code == status.HTTP_201_CREATED
        msg_id = msg_res.data["id"]
        assert msg_res.data["delivery_status"] == MessageDeliveryStatusEnum.SENT

        # 3. Bob reads conversation messages
        hist_res = bob_client.get(f"/api/v1/messaging/conversations/{conv_id}/messages/")
        assert hist_res.status_code == status.HTTP_200_OK
        messages = hist_res.data
        assert len(messages) == 1
        assert messages[0]["ciphertext"] == "aGVsbG8gd29ybGQgZW5jcnlwdGVkIQ=="

        # 4. Bob marks conversation as read
        read_res = bob_client.post(f"/api/v1/messaging/conversations/{conv_id}/read/", format="json")
        assert read_res.status_code == status.HTTP_200_OK

        # Verify delivery status updated to READ
        msg_obj = EncryptedMessage.objects.get(id=msg_id)
        assert msg_obj.delivery_status == MessageDeliveryStatusEnum.READ
        assert msg_obj.read_at is not None

    def test_auto_detect_conversation_type_when_omitted(self, alice_client, bob, gym_a):
        # 1. User to User auto-detected
        res_u2u = alice_client.post(
            "/api/v1/messaging/conversations/",
            {"target_user_id": str(bob.id)},
            format="json",
        )
        assert res_u2u.status_code == status.HTTP_201_CREATED
        assert res_u2u.data["conversation_type"] == "user_to_user"

        # 2. User to Gym auto-detected
        res_u2g = alice_client.post(
            "/api/v1/messaging/conversations/",
            {"target_gym_id": str(gym_a.id)},
            format="json",
        )
        assert res_u2g.status_code == status.HTTP_201_CREATED
        assert res_u2g.data["conversation_type"] == "user_to_gym"

    def test_initiate_conversation_using_user_profile_id(self, alice_client, bob):
        from apps.users.models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=bob)

        # Alice sends bob's profile.id instead of user.id
        res = alice_client.post(
            "/api/v1/messaging/conversations/",
            {"target_user_id": str(profile.id)},
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["conversation_type"] == "user_to_user"
        # Verify participants contain bob
        assert any(str(p["user_id"]) == str(bob.id) for p in res.data["participants"])


@pytest.mark.django_db
class TestUserToGymMessaging:
    """Tests Manygym user to Gym messaging and privacy policy enforcement."""

    def test_user_to_gym_messaging_when_policy_is_everyone(self, charlie_client, charlie, gym_a):
        # Gym A settings: who_can_message = EVERYONE (default)
        res = charlie_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "user_to_gym",
                "target_gym_id": str(gym_a.id),
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        conv_id = res.data["id"]

        # Charlie sends message to Gym A
        msg_res = charlie_client.post(
            f"/api/v1/messaging/conversations/{conv_id}/messages/",
            {
                "ciphertext": "VXNlciB0byBHeW0gRW5jcnlwdGVkIQ==",
                "nonce": "bm9uY2VfMTIz",
                "sender_type": "user",
            },
            format="json",
        )
        assert msg_res.status_code == status.HTTP_201_CREATED
        assert msg_res.data["sender_type"] == "user"

    def test_user_to_gym_rejected_when_user_is_blocked(self, charlie_client, charlie, gym_a):
        # Gym A blocks Charlie
        GymBlockedUser.objects.create(gym=gym_a, user=charlie)

        res = charlie_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "user_to_gym",
                "target_gym_id": str(gym_a.id),
            },
            format="json",
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_user_to_gym_policy_members_only(self, charlie_client, charlie, gym_a):
        # Change policy to MEMBERS_ONLY
        setting = gym_a.settings
        setting.who_can_message = AudienceMessagingEnum.MEMBERS_ONLY
        setting.save()

        # Non-member Charlie is rejected
        res = charlie_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "user_to_gym",
                "target_gym_id": str(gym_a.id),
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Add Charlie as accepted member
        Member.objects.create(
            gym=gym_a,
            user=charlie,
            first_name="Charlie",
            last_name="Brown",
            email=charlie.email,
            joining_status="accepted",
        )

        # Now Charlie is permitted
        res2 = charlie_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "user_to_gym",
                "target_gym_id": str(gym_a.id),
            },
            format="json",
        )
        assert res2.status_code == status.HTTP_201_CREATED

    def test_gym_owner_replies_on_behalf_of_gym(self, alice_client, charlie_client, alice, charlie, gym_a):
        # Charlie starts conversation with Gym A
        conv_res = charlie_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "user_to_gym",
                "target_gym_id": str(gym_a.id),
            },
            format="json",
        )
        conv_id = conv_res.data["id"]

        # Alice (owner of Gym A) replies with sender_type="gym"
        reply_res = alice_client.post(
            f"/api/v1/messaging/conversations/{conv_id}/messages/?gym_id={gym_a.id}",
            {
                "ciphertext": "T2x5bXB1cyBHeW0gcmVwbHkgY2lwaGVydGV4dA==",
                "nonce": "bm9uY2VfZ3ltXzEyMw==",
                "sender_type": "gym",
                "sender_gym_id": str(gym_a.id),
            },
            format="json",
        )
        assert reply_res.status_code == status.HTTP_201_CREATED
        assert reply_res.data["sender_type"] == "gym"
        assert reply_res.data["sender_gym_name"] == "Olympus Gym"

    def test_gym_initiates_conversation_with_user(self, alice_client, charlie_client, alice, charlie, gym_a):
        # Gym A (Alice) actively initiates contact with User Charlie
        conv_res = alice_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "gym_to_user",
                "source_gym_id": str(gym_a.id),
                "target_user_id": str(charlie.id),
            },
            format="json",
        )
        assert conv_res.status_code == status.HTTP_201_CREATED
        conv_id = conv_res.data["id"]
        assert conv_res.data["conversation_type"] == "user_to_gym"

        # Gym sends welcome/offer message
        msg_res = alice_client.post(
            f"/api/v1/messaging/conversations/{conv_id}/messages/?gym_id={gym_a.id}",
            {
                "ciphertext": "T2ZmZXIgZnJvbSBHeW0gQSB0byBDaGFybGllIQ==",
                "nonce": "bm9uY2Vfb2ZmZXJfMQ==",
                "sender_type": "gym",
                "sender_gym_id": str(gym_a.id),
            },
            format="json",
        )
        assert msg_res.status_code == status.HTTP_201_CREATED
        assert msg_res.data["sender_type"] == "gym"

        # Charlie sees the conversation and unread message
        charlie_msgs = charlie_client.get(f"/api/v1/messaging/conversations/{conv_id}/messages/")
        assert charlie_msgs.status_code == status.HTTP_200_OK
        assert len(charlie_msgs.data) == 1
        assert charlie_msgs.data[0]["ciphertext"] == "T2ZmZXIgZnJvbSBHeW0gQSB0byBDaGFybGllIQ=="


@pytest.mark.django_db
class TestGymToGymB2BMessaging:
    """Tests B2B inter-gym messaging between Gym A and Gym B."""

    def test_gym_to_gym_messaging_flow(self, alice_client, bob_client, alice, bob, gym_a, gym_b):
        # Alice initiates Gym A to Gym B conversation
        res = alice_client.post(
            "/api/v1/messaging/conversations/",
            {
                "conversation_type": "gym_to_gym",
                "source_gym_id": str(gym_a.id),
                "target_gym_id": str(gym_b.id),
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        conv_id = res.data["id"]
        assert res.data["conversation_type"] == "gym_to_gym"

        # Gym A sends B2B encrypted proposal to Gym B
        msg_res = alice_client.post(
            f"/api/v1/messaging/conversations/{conv_id}/messages/?gym_id={gym_a.id}",
            {
                "ciphertext": "QjJCIHBhcnRuZXJzaGlwIHByb3Bvc2FsIGNpcGhlcg==",
                "nonce": "YjJiX25vbmNl",
                "sender_type": "gym",
                "sender_gym_id": str(gym_a.id),
            },
            format="json",
        )
        assert msg_res.status_code == status.HTTP_201_CREATED
        assert msg_res.data["sender_type"] == "gym"

        # Bob (owner of Gym B) reads messages
        bob_hist = bob_client.get(f"/api/v1/messaging/conversations/{conv_id}/messages/?gym_id={gym_b.id}")
        assert bob_hist.status_code == status.HTTP_200_OK
        assert len(bob_hist.data) == 1


@pytest.mark.django_db(transaction=True)
class TestRealtimeWebSocketChatConsumer:
    """Tests real-time WebSocket connection, joining conversations, and live message receiving."""

    def test_websocket_connection_and_ping_pong(self, alice):
        from asgiref.sync import async_to_sync

        tokens = issue_context_token(alice, context_type=TokenContextType.PERSONAL)
        access_token = tokens["access"]

        @async_to_sync
        async def run_ws():
            communicator = WebsocketCommunicator(
                ChatConsumer.as_asgi(),
                f"/ws/chat/?token={access_token}",
            )
            connected, subprotocol = await communicator.connect()
            assert connected is True

            init_event = await communicator.receive_json_from()
            assert init_event["type"] == "connection_established"
            assert init_event["user_id"] == str(alice.id)

            # Test ping-pong
            await communicator.send_json_to({"action": "ping"})
            pong_event = await communicator.receive_json_from()
            assert pong_event["type"] == "pong"

            await communicator.disconnect()

        run_ws()
