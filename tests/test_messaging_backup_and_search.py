import os
import uuid
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserFollow, UserBlockedUser, UserProfile
from apps.authentication.services import issue_context_token
from apps.messaging.crypto import (
    generate_x25519_keypair,
    hybrid_encrypt,
    hybrid_decrypt,
    derive_backup_keys,
    encrypt_backup_bundle,
    decrypt_backup_bundle,
    compute_search_token,
    compute_search_tokens,
    b64_encode,
    b64_decode,
)
from apps.messaging.models import UserDeviceKey, UserE2EEBackup, MessageSearchToken
from apps.messaging.services import get_or_create_user_to_user_conversation, send_encrypted_message
from common.enums import TokenContextType, MessageSenderTypeEnum, UserAudienceMessagingEnum


@pytest.fixture
def alice(db):
    user = User.objects.create_user(
        email="alice_e2ee@example.com",
        password="Password123!",
        first_name="Alice",
        last_name="Walker",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def bob(db):
    user = User.objects.create_user(
        email="bob_e2ee@example.com",
        password="Password123!",
        first_name="Bob",
        last_name="Builder",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def charlie(db):
    user = User.objects.create_user(
        email="charlie_e2ee@example.com",
        password="Password123!",
        first_name="Charlie",
        last_name="Chaplin",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def diana(db):
    user = User.objects.create_user(
        email="diana_e2ee@example.com",
        password="Password123!",
        first_name="Diana",
        last_name="Prince",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


def _auth_client(user):
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def alice_client(alice):
    return _auth_client(alice)


@pytest.fixture
def bob_client(bob):
    return _auth_client(bob)


@pytest.fixture
def charlie_client(charlie):
    return _auth_client(charlie)


class TestBackupAndSearchCrypto:
    """Verifies Messenger-style PIN/password backup encryption and HMAC search tokenization."""

    def test_backup_bundle_encrypt_and_decrypt_roundtrip(self):
        master_priv, master_pub = generate_x25519_keypair()
        search_key = os.urandom(32)
        bundle = {
            "master_private_key": b64_encode(master_priv),
            "master_public_key": master_pub,
            "search_key": b64_encode(search_key),
        }

        encrypted = encrypt_backup_bundle(bundle, secret="482910", iterations=10000)
        assert encrypted["encrypted_key_bundle"]
        assert encrypted["auth_proof"]

        # Verify auth_proof matches deterministic derivation from same salt + secret
        _, expected_proof = derive_backup_keys("482910", b64_decode(encrypted["salt"]), iterations=10000)
        assert encrypted["auth_proof"] == expected_proof

        decrypted = decrypt_backup_bundle(
            encrypted_bundle_b64=encrypted["encrypted_key_bundle"],
            nonce_b64=encrypted["nonce"],
            salt_b64=encrypted["salt"],
            secret="482910",
            iterations=10000,
        )
        assert decrypted == bundle

        # Wrong PIN fails AEAD authentication
        with pytest.raises(Exception):
            decrypt_backup_bundle(
                encrypted_bundle_b64=encrypted["encrypted_key_bundle"],
                nonce_b64=encrypted["nonce"],
                salt_b64=encrypted["salt"],
                secret="000000",
                iterations=10000,
            )

    def test_search_token_determinism_and_normalization(self):
        key = os.urandom(32)
        tokens = compute_search_tokens(key, "Leg Day squats Squats workout!")
        assert len(tokens) == 4  # deduplicated case-insensitively
        assert compute_search_token(key, "  SQUATS ") in tokens


@pytest.mark.django_db
class TestFindPeopleToMessageSearch:
    """Tests Follows + Followers scoped people search for the modal/offcanvas."""

    def test_search_only_includes_follows_and_followers(self, alice, bob, charlie, diana, alice_client):
        # Alice follows Bob (following), Charlie follows Alice (follower), Diana is unrelated
        UserFollow.objects.create(follower=alice, followed_user=bob)
        UserFollow.objects.create(follower=charlie, followed_user=alice)

        # Even if Bob also follows Diana, Diana is NOT in Alice's follows or followers
        UserFollow.objects.create(follower=bob, followed_user=diana)

        res = alice_client.get("/api/v1/messaging/people/search/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["count"] == 2
        returned_ids = {item["user_id"] for item in res.data["results"]}
        assert returned_ids == {str(bob.id), str(charlie.id)}
        assert str(diana.id) not in returned_ids

        by_id = {item["user_id"]: item for item in res.data["results"]}
        assert by_id[str(bob.id)]["relationship"] == "following"
        assert by_id[str(bob.id)]["can_message"] is True
        assert by_id[str(charlie.id)]["relationship"] == "follower"
        # Charlie has default FOLLOWERS policy and Alice does not follow Charlie yet
        assert by_id[str(charlie.id)]["can_message"] is False

    def test_mutual_follow_deduplication_and_keyword_filter(self, alice, bob, charlie, alice_client):
        # Mutual follow with Bob
        UserFollow.objects.create(follower=alice, followed_user=bob)
        UserFollow.objects.create(follower=bob, followed_user=alice)
        UserFollow.objects.create(follower=charlie, followed_user=alice)

        # Create existing conversation with Bob
        conv = get_or_create_user_to_user_conversation(alice, bob)

        res = alice_client.get("/api/v1/messaging/people/search/?q=Bob Builder")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["count"] == 1
        item = res.data["results"][0]
        assert item["user_id"] == str(bob.id)
        assert item["relationship"] == "mutual"
        assert item["conversation_id"] == str(conv.id)

    def test_excludes_blocked_and_deactivated_users(self, alice, bob, charlie, alice_client):
        UserFollow.objects.create(follower=alice, followed_user=bob)
        UserFollow.objects.create(follower=charlie, followed_user=alice)

        UserBlockedUser.objects.create(blocker=alice, blocked_user=bob)
        charlie_settings = charlie.get_settings()
        charlie_settings.is_deactivated = True
        charlie_settings.save()

        res = alice_client.get("/api/v1/messaging/people/search/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["count"] == 0

    def test_people_search_query_count_and_null_byte_rejection(self, alice, alice_client):
        for i in range(15):
            u = User.objects.create_user(
                email=f"follow_perf_{i}@example.com",
                password="Password123!",
                first_name=f"Member{i}",
                last_name="Fit",
                is_verified=True,
            )
            UserFollow.objects.create(follower=alice, followed_user=u)

        alice_client.get("/api/v1/messaging/people/search/")  # warmup
        with CaptureQueriesContext(connection) as ctx:
            res = alice_client.get("/api/v1/messaging/people/search/?q=Member")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["count"] == 15
        assert len(ctx) <= 7

        bad_res = alice_client.get("/api/v1/messaging/people/search/?q=bad%00query")
        assert bad_res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestMessengerStyleE2EEBackupAndRestore:
    """Tests setting PIN/password backup, brute-force lockout, new-device restore, and decrypting old history."""

    def test_full_pin_backup_and_new_device_history_restore(self, alice, bob, alice_client, bob_client):
        UserFollow.objects.create(follower=alice, followed_user=bob)
        UserFollow.objects.create(follower=bob, followed_user=alice)

        # 1. Bob has no backup initially
        status_res = bob_client.get("/api/v1/messaging/keys/backup/status/")
        assert status_res.status_code == status.HTTP_200_OK
        assert status_res.data["has_backup"] is False

        # 2. Bob sets up Messenger-style 5-digit recovery code backup on Device 1
        bob_master_priv, bob_master_pub = generate_x25519_keypair()
        bob_search_key = os.urandom(32)
        bundle = {
            "master_private_key": b64_encode(bob_master_priv),
            "master_public_key": bob_master_pub,
            "search_key": b64_encode(bob_search_key),
        }
        encrypted = encrypt_backup_bundle(bundle, secret="19482", iterations=10000)

        set_res = bob_client.post(
            "/api/v1/messaging/keys/backup/",
            {
                "backup_public_key": bob_master_pub,
                "encrypted_key_bundle": encrypted["encrypted_key_bundle"],
                "nonce": encrypted["nonce"],
                "salt": encrypted["salt"],
                "kdf_algorithm": "pbkdf2_sha256",
                "kdf_iterations": 10000,
                "cipher_algorithm": "chacha20_poly1305",
                "secret_type": "pin",
                "auth_proof": encrypted["auth_proof"],
                "max_attempts": 3,
            },
            format="json",
        )
        assert set_res.status_code == status.HTTP_200_OK
        assert set_res.data["key_version"] == 1
        assert set_res.data["pin_length"] == 5
        assert set_res.data["requires_auth_proof"] is True

        # 3. Alice fetches Bob's public key bundle and sees Bob's backup_key
        key_bundle_res = alice_client.get(f"/api/v1/messaging/keys/user/{bob.id}/")
        assert key_bundle_res.status_code == status.HTTP_200_OK
        assert key_bundle_res.data["backup_key"]["backup_public_key"] == bob_master_pub

        # 4. Alice sends a message encrypted so Bob's backup key can decrypt it on any future device
        conv_res = alice_client.post(
            "/api/v1/messaging/conversations/",
            {"target_user_id": str(bob.id)},
            format="json",
        )
        conv_id = conv_res.data["id"]

        plaintext_secret = "Hey Bob! Remember our 100kg deadlift PR!"
        wrapped_for_bob_backup = hybrid_encrypt(
            recipient_public_key_b64=key_bundle_res.data["backup_key"]["backup_public_key"],
            plaintext=plaintext_secret,
        )
        send_res = alice_client.post(
            f"/api/v1/messaging/conversations/{conv_id}/messages/",
            {
                "ciphertext": wrapped_for_bob_backup["ciphertext"],
                "nonce": wrapped_for_bob_backup["nonce"],
                "ephemeral_public_key": wrapped_for_bob_backup["ephemeral_public_key"],
                "recipient_key_fingerprint": wrapped_for_bob_backup["recipient_key_fingerprint"],
                "encrypted_keys": {
                    f"backup:{bob.id}": {
                        "ciphertext": wrapped_for_bob_backup["ciphertext"],
                        "nonce": wrapped_for_bob_backup["nonce"],
                        "ephemeral_public_key": wrapped_for_bob_backup["ephemeral_public_key"],
                    }
                },
            },
            format="json",
        )
        assert send_res.status_code == status.HTTP_201_CREATED

        # 5. Bob logs in on a BRAND NEW device (bob-pixel-9):
        # GET /backup/ must NOT leak encrypted_key_bundle before PIN verification
        fetch_res = bob_client.get("/api/v1/messaging/keys/backup/")
        assert fetch_res.status_code == status.HTTP_200_OK
        assert "encrypted_key_bundle" not in fetch_res.data
        assert fetch_res.data["salt"] == encrypted["salt"]

        # 6. Wrong 5-digit PIN attempt is rejected and tracked
        _, wrong_proof = derive_backup_keys("99999", b64_decode(encrypted["salt"]), iterations=10000)
        bad_restore = bob_client.post(
            "/api/v1/messaging/keys/backup/restore/",
            {"auth_proof": wrong_proof},
            format="json",
        )
        assert bad_restore.status_code == status.HTTP_403_FORBIDDEN
        assert bad_restore.data["details"]["remaining_attempts"] == 2

        # 7. Correct 5-digit PIN restores bundle AND registers the new device
        _, new_dev_pub = generate_x25519_keypair()
        _, good_proof = derive_backup_keys("19482", b64_decode(encrypted["salt"]), iterations=10000)
        restore_res = bob_client.post(
            "/api/v1/messaging/keys/backup/restore/",
            {
                "auth_proof": good_proof,
                "device_id": "bob-pixel-9",
                "device_name": "Bob Pixel 9",
                "identity_key": new_dev_pub,
                "signed_prekey": new_dev_pub,
            },
            format="json",
        )
        assert restore_res.status_code == status.HTTP_200_OK
        assert restore_res.data["registered_device"]["device_id"] == "bob-pixel-9"

        # 8. Bob's new device decrypts the backup bundle locally, recovers master_private_key,
        # and decrypts Alice's historical message!
        restored_bundle = decrypt_backup_bundle(
            encrypted_bundle_b64=restore_res.data["encrypted_key_bundle"],
            nonce_b64=restore_res.data["nonce"],
            salt_b64=restore_res.data["salt"],
            secret="19482",
            iterations=restore_res.data["kdf_iterations"],
        )
        recovered_master_priv = b64_decode(restored_bundle["master_private_key"])

        hist_res = bob_client.get(f"/api/v1/messaging/conversations/{conv_id}/messages/?order=desc&limit=50")
        assert hist_res.status_code == status.HTTP_200_OK
        assert len(hist_res.data) == 1
        msg = hist_res.data[0]
        decrypted_msg = hybrid_decrypt(
            recipient_private_bytes=recovered_master_priv,
            ephemeral_public_key_b64=msg["ephemeral_public_key"],
            ciphertext_b64=msg["ciphertext"],
            nonce_b64=msg["nonce"],
        )
        assert decrypted_msg == plaintext_secret

    def test_lockout_after_max_attempts_and_change_code_and_delete(self, alice, alice_client):
        priv, pub = generate_x25519_keypair()
        encrypted = encrypt_backup_bundle({"k": b64_encode(priv)}, secret="MyStrongPass!", iterations=10000)

        alice_client.post(
            "/api/v1/messaging/keys/backup/",
            {
                "backup_public_key": pub,
                "encrypted_key_bundle": encrypted["encrypted_key_bundle"],
                "nonce": encrypted["nonce"],
                "salt": encrypted["salt"],
                "kdf_iterations": 10000,
                "secret_type": "passphrase",
                "auth_proof": encrypted["auth_proof"],
                "max_attempts": 3,
            },
            format="json",
        )

        # Change PIN/password
        new_enc = encrypt_backup_bundle({"k": b64_encode(priv)}, secret="NewCode999", iterations=10000)
        chg_res = alice_client.post(
            "/api/v1/messaging/keys/backup/change-code/",
            {
                "current_auth_proof": encrypted["auth_proof"],
                "new_auth_proof": new_enc["auth_proof"],
                "encrypted_key_bundle": new_enc["encrypted_key_bundle"],
                "nonce": new_enc["nonce"],
                "salt": new_enc["salt"],
                "kdf_iterations": 10000,
                "secret_type": "pin",
            },
            format="json",
        )
        assert chg_res.status_code == status.HTTP_200_OK
        assert chg_res.data["key_version"] == 2

        # Trigger 3 failed attempts -> lockout
        for i in range(3):
            fail_res = alice_client.post(
                "/api/v1/messaging/keys/backup/restore/",
                {"auth_proof": "wrong-proof"},
                format="json",
            )
            assert fail_res.status_code == status.HTTP_403_FORBIDDEN

        # Even valid proof is now locked out
        locked_res = alice_client.post(
            "/api/v1/messaging/keys/backup/restore/",
            {"auth_proof": new_enc["auth_proof"]},
            format="json",
        )
        assert locked_res.status_code == status.HTTP_403_FORBIDDEN
        assert locked_res.data["details"]["is_locked"] is True

        # Delete backup
        del_res = alice_client.delete("/api/v1/messaging/keys/backup/")
        assert del_res.status_code == status.HTTP_200_OK
        assert not UserE2EEBackup.objects.filter(user=alice).exists()

    def test_five_digit_recovery_code_flow_and_validation(self, alice, bob, alice_client, bob_client):
        UserFollow.objects.create(follower=alice, followed_user=bob)

        # Reject non-5-digit recovery codes
        for invalid_code in ("1234", "123456", "abcde", "12 45"):
            bad_res = bob_client.post(
                "/api/v1/messaging/keys/backup/",
                {"recovery_code": invalid_code},
                format="json",
            )
            assert bad_res.status_code == status.HTTP_400_BAD_REQUEST

        # Set 5-digit recovery code directly
        set_res = bob_client.post(
            "/api/v1/messaging/keys/backup/",
            {"recovery_code": "58294", "kdf_iterations": 10000},
            format="json",
        )
        assert set_res.status_code == status.HTTP_200_OK
        assert set_res.data["pin_length"] == 5
        backup_pub = set_res.data["backup_public_key"]

        # Alice sends encrypted message to Bob using Bob's backup_public_key
        conv_res = alice_client.post(
            "/api/v1/messaging/conversations/",
            {"target_user_id": str(bob.id)},
            format="json",
        )
        conv_id = conv_res.data["id"]
        enc_msg = hybrid_encrypt(backup_pub, "New device recovery test message!")
        alice_client.post(
            f"/api/v1/messaging/conversations/{conv_id}/messages/",
            {
                "ciphertext": enc_msg["ciphertext"],
                "nonce": enc_msg["nonce"],
                "ephemeral_public_key": enc_msg["ephemeral_public_key"],
            },
            format="json",
        )

        # Change 5-digit code from 58294 -> 73915 while keeping the same master keypair
        chg_res = bob_client.post(
            "/api/v1/messaging/keys/backup/change-code/",
            {
                "current_recovery_code": "58294",
                "new_recovery_code": "73915",
                "kdf_iterations": 10000,
            },
            format="json",
        )
        assert chg_res.status_code == status.HTTP_200_OK
        assert chg_res.data["key_version"] == 2

        # Old code fails, new 5-digit code restores keys on a new device and decrypts stored message
        old_fail = bob_client.post(
            "/api/v1/messaging/keys/backup/restore/",
            {"recovery_code": "58294"},
            format="json",
        )
        assert old_fail.status_code == status.HTTP_403_FORBIDDEN

        restore_res = bob_client.post(
            "/api/v1/messaging/keys/backup/restore/",
            {"recovery_code": "73915"},
            format="json",
        )
        assert restore_res.status_code == status.HTTP_200_OK
        master_priv = b64_decode(restore_res.data["restored_keys"]["master_private_key"])

        hist = bob_client.get(f"/api/v1/messaging/conversations/{conv_id}/messages/")
        assert hist.status_code == status.HTTP_200_OK
        decrypted = hybrid_decrypt(
            recipient_private_bytes=master_priv,
            ephemeral_public_key_b64=hist.data[0]["ephemeral_public_key"],
            ciphertext_b64=hist.data[0]["ciphertext"],
            nonce_b64=hist.data[0]["nonce"],
        )
        assert decrypted == "New device recovery test message!"


@pytest.mark.django_db
class TestWhatsAppStyleChatHistorySearchAndPagination:
    """Tests WhatsApp-style grouped keyword search across conversations and history cursor pagination."""

    def test_whatsapp_style_search_across_multiple_chats(self, alice, bob, charlie, alice_client, bob_client):
        UserFollow.objects.create(follower=alice, followed_user=bob)
        UserFollow.objects.create(follower=bob, followed_user=alice)
        UserFollow.objects.create(follower=alice, followed_user=charlie)
        UserFollow.objects.create(follower=charlie, followed_user=alice)

        conv_bob = get_or_create_user_to_user_conversation(alice, bob)
        conv_charlie = get_or_create_user_to_user_conversation(alice, charlie)

        alice_search_key = os.urandom(32)

        # Alice sends 2 messages mentioning "protein" to Bob, 1 to Charlie, and 1 unrelated message
        m1 = alice_client.post(
            f"/api/v1/messaging/conversations/{conv_bob.id}/messages/",
            {
                "ciphertext": "cipher_1==",
                "nonce": "nonce_1==",
                "search_tokens": compute_search_tokens(alice_search_key, "Did you buy whey protein today?"),
            },
            format="json",
        )
        assert m1.status_code == status.HTTP_201_CREATED

        m2 = alice_client.post(
            f"/api/v1/messaging/conversations/{conv_bob.id}/messages/",
            {
                "ciphertext": "cipher_2==",
                "nonce": "nonce_2==",
                "search_tokens": compute_search_tokens(alice_search_key, "Protein shake after leg day"),
            },
            format="json",
        )
        assert m2.status_code == status.HTTP_201_CREATED

        m3 = alice_client.post(
            f"/api/v1/messaging/conversations/{conv_charlie.id}/messages/",
            {
                "ciphertext": "cipher_3==",
                "nonce": "nonce_3==",
                "search_tokens": compute_search_tokens(alice_search_key, "Best protein brand recommendation"),
            },
            format="json",
        )
        assert m3.status_code == status.HTTP_201_CREATED

        alice_client.post(
            f"/api/v1/messaging/conversations/{conv_charlie.id}/messages/",
            {
                "ciphertext": "cipher_4==",
                "nonce": "nonce_4==",
                "search_tokens": compute_search_tokens(alice_search_key, "See you at 6pm"),
            },
            format="json",
        )

        # Search for "protein" across all chats via GET
        tok_protein = compute_search_token(alice_search_key, "protein")
        search_res = alice_client.get(f"/api/v1/messaging/messages/search/?token={tok_protein}")
        assert search_res.status_code == status.HTTP_200_OK
        assert search_res.data["total_conversations"] == 2
        assert search_res.data["total_matches"] == 3

        results = search_res.data["results"]
        conv_ids = {r["conversation"]["id"] for r in results}
        assert conv_ids == {str(conv_bob.id), str(conv_charlie.id)}
        counts = {r["conversation"]["id"]: r["match_count"] for r in results}
        assert counts[str(conv_bob.id)] == 2
        assert counts[str(conv_charlie.id)] == 1

        # Multi-word search ("protein" AND "leg") via POST matches only m2 in Bob's chat
        tok_leg = compute_search_token(alice_search_key, "leg")
        multi_res = alice_client.post(
            "/api/v1/messaging/messages/search/",
            {"tokens": [tok_protein, tok_leg], "match_mode": "all"},
            format="json",
        )
        assert multi_res.status_code == status.HTTP_200_OK
        assert multi_res.data["total_conversations"] == 1
        assert multi_res.data["total_matches"] == 1
        assert multi_res.data["results"][0]["matches"][0]["id"] == m2.data["id"]

        # Bob batch-indexes received message m1 under Bob's own search key
        bob_search_key = os.urandom(32)
        tok_bob_protein = compute_search_token(bob_search_key, "protein")
        idx_res = bob_client.post(
            "/api/v1/messaging/search/index/",
            {
                "items": [
                    {"message_id": m1.data["id"], "tokens": [tok_bob_protein]},
                ]
            },
            format="json",
        )
        assert idx_res.status_code == status.HTTP_200_OK
        assert idx_res.data["indexed_count"] == 1

        bob_search = bob_client.get(f"/api/v1/messaging/messages/search/?token={tok_bob_protein}")
        assert bob_search.status_code == status.HTTP_200_OK
        assert bob_search.data["total_matches"] == 1

        # Bob cannot search Alice's conversation with Charlie (IDOR protection)
        idor_res = bob_client.post(
            "/api/v1/messaging/messages/search/",
            {"tokens": [tok_protein], "conversation_id": str(conv_charlie.id)},
            format="json",
        )
        assert idor_res.status_code == status.HTTP_403_FORBIDDEN

    def test_message_history_cursor_pagination(self, alice, bob, alice_client):
        UserFollow.objects.create(follower=alice, followed_user=bob)
        conv = get_or_create_user_to_user_conversation(alice, bob)

        created_ids = []
        for i in range(5):
            msg = send_encrypted_message(
                conversation=conv,
                sender_user=alice,
                sender_type=MessageSenderTypeEnum.USER,
                ciphertext=f"c_{i}==",
                nonce=f"n_{i}==",
            )
            created_ids.append(str(msg.id))

        # New device fetches latest 2 messages descending
        page1 = alice_client.get(f"/api/v1/messaging/conversations/{conv.id}/messages/?order=desc&limit=2")
        assert page1.status_code == status.HTTP_200_OK
        assert [m["id"] for m in page1.data] == [created_ids[4], created_ids[3]]

        # Scroll older using `before` cursor
        page2 = alice_client.get(
            f"/api/v1/messaging/conversations/{conv.id}/messages/?order=desc&limit=2&before={created_ids[3]}"
        )
        assert page2.status_code == status.HTTP_200_OK
        assert [m["id"] for m in page2.data] == [created_ids[2], created_ids[1]]
