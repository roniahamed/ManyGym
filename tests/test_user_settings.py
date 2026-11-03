import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserFollow, UserSetting, UserBlockedUser, UserProfile
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    UserAudienceMessagingEnum,
    UserAudienceVisibilityEnum,
    UserStatus,
)


@pytest.fixture
def user_alice(db):
    user = User.objects.create_user(
        email="alice@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Smith",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, is_private=False)
    return user


@pytest.fixture
def user_bob(db):
    user = User.objects.create_user(
        email="bob@example.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Jones",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, is_private=False)
    return user


@pytest.fixture
def user_charlie(db):
    user = User.objects.create_user(
        email="charlie@example.com",
        password="SecurePassword123!",
        first_name="Charlie",
        last_name="Brown",
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


@pytest.mark.django_db
class TestUserSettings:
    """Tests User Settings retrieve & update operations."""

    def test_default_user_settings(self, user_alice):
        settings_obj = user_alice.get_settings()
        assert settings_obj.language == "en"
        assert settings_obj.dark_mode is False
        assert settings_obj.who_can_message == UserAudienceMessagingEnum.EVERYONE
        assert settings_obj.who_can_see_followers == UserAudienceVisibilityEnum.EVERYONE
        assert settings_obj.who_can_see_following == UserAudienceVisibilityEnum.EVERYONE
        assert settings_obj.is_deactivated is False
        assert settings_obj.is_deleted is False

    def test_get_settings_endpoint(self, alice_client, user_alice):
        url = reverse("user-settings")
        res = alice_client.get(url)
        assert res.status_code == status.HTTP_200_OK
        assert res.data["user_id"] == str(user_alice.id)
        assert res.data["language"] == "en"
        assert res.data["dark_mode"] is False
        assert res.data["is_private"] is False
        assert res.data["who_can_message"] == "everyone"
        assert res.data["who_can_see_followers"] == "everyone"
        assert res.data["who_can_see_following"] == "everyone"

    def test_patch_settings_endpoint(self, alice_client, user_alice):
        url = reverse("user-settings")
        payload = {
            "language": "bn",
            "dark_mode": True,
            "is_private": True,
            "who_can_message": "followers",
            "who_can_see_followers": "private",
            "who_can_see_following": "followers",
        }
        res = alice_client.patch(url, payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["language"] == "bn"
        assert res.data["dark_mode"] is True
        assert res.data["is_private"] is True
        assert res.data["who_can_message"] == "followers"
        assert res.data["who_can_see_followers"] == "private"
        assert res.data["who_can_see_following"] == "followers"

        user_alice.refresh_from_db()
        assert user_alice.profile.is_private is True
        assert user_alice.settings.language == "bn"
        assert user_alice.settings.dark_mode is True


@pytest.mark.django_db
class TestUserBlocking:
    """Tests blocking flows, search, and follower removal for user profiles."""

    def test_search_users_to_block(self, alice_client, user_alice, user_bob, user_charlie):
        url = reverse("user-settings-blocked-users-search")
        res = alice_client.get(f"{url}?q=Bob")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data) == 1
        assert res.data[0]["id"] == str(user_bob.id)

        # Alice herself must not appear in search results
        res_self = alice_client.get(f"{url}?q=Alice")
        assert len(res_self.data) == 0

    def test_cannot_block_self(self, alice_client, user_alice):
        url = reverse("user-settings-blocked-users")
        res = alice_client.post(url, {"user_id": str(user_alice.id)}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_block_user_removes_follow_relationships(self, alice_client, bob_client, user_alice, user_bob):
        # Alice follows Bob, Bob follows Alice
        UserFollow.objects.create(follower=user_alice, followed_user=user_bob)
        UserFollow.objects.create(follower=user_bob, followed_user=user_alice)

        assert UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()
        assert UserFollow.objects.filter(follower=user_bob, followed_user=user_alice).exists()

        # Alice blocks Bob
        url = reverse("user-settings-blocked-users")
        res = alice_client.post(url, {"user_id": str(user_bob.id), "reason": "Harassment"}, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["user_id"] == str(user_bob.id)
        assert res.data["reason"] == "Harassment"

        # Both follow relations are severed automatically
        assert not UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()
        assert not UserFollow.objects.filter(follower=user_bob, followed_user=user_alice).exists()

        # Bob cannot follow Alice
        follow_url = reverse("user-unified-follow")
        res_bob_follow = bob_client.post(follow_url, {"target_id": str(user_alice.id), "target_type": "user"}, format="json")
        assert res_bob_follow.status_code == status.HTTP_403_FORBIDDEN

        # Alice unblocks Bob
        detail_url = reverse("user-settings-blocked-user-detail", kwargs={"user_id": user_bob.id})
        res_unblock = alice_client.delete(detail_url)
        assert res_unblock.status_code == status.HTTP_200_OK

        # List is empty
        res_list = alice_client.get(url)
        assert len(res_list.data) == 0

    def test_block_directly_from_followers_list(self, alice_client, bob_client, user_alice, user_bob):
        # Bob follows Alice
        UserFollow.objects.create(follower=user_bob, followed_user=user_alice)
        assert UserFollow.objects.filter(follower=user_bob, followed_user=user_alice).exists()

        # Alice blocks Bob directly via followers endpoint
        block_url = reverse("user-follower-block", kwargs={"user_id": user_bob.id})
        res = alice_client.post(block_url, {"reason": "Spam"}, format="json")
        assert res.status_code == status.HTTP_200_OK

        # Bob is blocked and unfollowed
        assert not UserFollow.objects.filter(follower=user_bob, followed_user=user_alice).exists()
        assert UserBlockedUser.objects.filter(blocker=user_alice, blocked_user=user_bob).exists()


@pytest.mark.django_db
class TestUserAudienceAndPrivacySettings:
    """Tests audience visibility and direct messaging policies for user profiles."""

    def test_followers_visibility_private(self, alice_client, bob_client, user_alice, user_bob):
        settings = user_alice.get_settings()
        settings.who_can_see_followers = UserAudienceVisibilityEnum.PRIVATE
        settings.save()

        followers_url = reverse("user-followers-list", kwargs={"user_id": user_alice.id})

        # Alice can view her own followers
        assert alice_client.get(followers_url).status_code == status.HTTP_200_OK

        # Bob cannot view Alice's followers
        assert bob_client.get(followers_url).status_code == status.HTTP_403_FORBIDDEN

    def test_followers_visibility_followers_only(self, alice_client, bob_client, charlie_client, user_alice, user_bob, user_charlie):
        settings = user_alice.get_settings()
        settings.who_can_see_followers = UserAudienceVisibilityEnum.FOLLOWERS
        settings.save()

        followers_url = reverse("user-followers-list", kwargs={"user_id": user_alice.id})

        # Bob is not following Alice -> 403
        assert bob_client.get(followers_url).status_code == status.HTTP_403_FORBIDDEN

        # Bob follows Alice -> 200
        UserFollow.objects.create(follower=user_bob, followed_user=user_alice)
        assert bob_client.get(followers_url).status_code == status.HTTP_200_OK

        # Charlie is not following -> 403
        assert charlie_client.get(followers_url).status_code == status.HTTP_403_FORBIDDEN

    def test_user_messaging_policies(self, alice_client, bob_client, user_alice, user_bob):
        from apps.messaging.services.conversation_services import get_or_create_user_to_user_conversation
        from common.exceptions import DomainValidationError, PermissionDeniedError

        # 1. NO_ONE policy: Bob cannot message Alice
        settings = user_alice.get_settings()
        settings.who_can_message = UserAudienceMessagingEnum.NO_ONE
        settings.save()
        with pytest.raises(DomainValidationError, match="does not accept direct messages"):
            get_or_create_user_to_user_conversation(user_bob, user_alice)

        # 2. FOLLOWERS policy: Bob must follow Alice
        settings.who_can_message = UserAudienceMessagingEnum.FOLLOWERS
        settings.save()
        with pytest.raises(DomainValidationError, match="only accepts direct messages from their followers"):
            get_or_create_user_to_user_conversation(user_bob, user_alice)

        # Bob follows Alice -> can message!
        UserFollow.objects.create(follower=user_bob, followed_user=user_alice)
        conv = get_or_create_user_to_user_conversation(user_bob, user_alice)
        assert conv is not None

        # 3. Blocked user cannot message
        UserBlockedUser.objects.create(blocker=user_alice, blocked_user=user_bob)
        with pytest.raises(PermissionDeniedError, match="blocked from messaging"):
            get_or_create_user_to_user_conversation(user_bob, user_alice)


@pytest.mark.django_db
class TestUserAccessAndControl:
    """Tests profile deactivation, login reactivation prompt, and deletion confirmation."""

    def test_deactivate_and_reactivate_user_account(self, alice_client, user_alice):
        url = reverse("user-settings-access-control")

        # 1. Deactivate account
        res = alice_client.post(url, {"action": "deactivate"}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["is_deactivated"] is True

        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.DEACTIVATED

        # 2. Attempt login while deactivated: returns clear deactivation message prompting reactivation
        anon_client = APIClient()
        login_url = "/api/v1/auth/login/"
        res_login = anon_client.post(
            login_url,
            {"email": user_alice.email, "password": "SecurePassword123!"},
            format="json",
        )
        assert res_login.status_code == status.HTTP_400_BAD_REQUEST
        err_msg = res_login.data.get("message") or res_login.data.get("detail")
        assert "deactivated" in err_msg
        assert "reactivate" in err_msg

        # 3. Login with reactivate=True: reactivates account and logs in
        res_reactivate_login = anon_client.post(
            login_url,
            {"email": user_alice.email, "password": "SecurePassword123!", "reactivate": True},
            format="json",
        )
        assert res_reactivate_login.status_code == status.HTTP_200_OK
        assert "reactivated" in res_reactivate_login.data["message"]
        assert "tokens" in res_reactivate_login.data

        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.ACTIVE
        assert user_alice.settings.is_deactivated is False

    def test_delete_user_account_confirmation(self, alice_client, user_alice, bob_client):
        url = reverse("user-settings-access-control")

        # 1. Missing password
        res_no_pw = alice_client.post(url, {"action": "delete", "confirmation": "delete"}, format="json")
        assert res_no_pw.status_code == status.HTTP_400_BAD_REQUEST

        # 2. Wrong password
        res_wrong_pw = alice_client.post(url, {"action": "delete", "password": "WrongPassword!", "confirmation": "delete"}, format="json")
        assert res_wrong_pw.status_code == status.HTTP_400_BAD_REQUEST

        # 3. Missing confirmation text
        res_no_conf = alice_client.post(url, {"action": "delete", "password": "SecurePassword123!"}, format="json")
        assert res_no_conf.status_code == status.HTTP_400_BAD_REQUEST

        # 4. Wrong confirmation word
        res_wrong_conf = alice_client.post(url, {"action": "delete", "password": "SecurePassword123!", "confirmation": "remove"}, format="json")
        assert res_wrong_conf.status_code == status.HTTP_400_BAD_REQUEST

        # 5. Valid Delete with password + 'delete' confirmation
        res = alice_client.post(
            url,
            {"action": "delete", "password": "SecurePassword123!", "confirmation": "delete"},
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["is_deleted"] is True
        assert res.data["deleted_at"] is not None

        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.DELETED
        assert user_alice.is_active is False

        # 6. Bob cannot view deleted user's followers
        followers_url = reverse("user-followers-list", kwargs={"user_id": user_alice.id})
        assert bob_client.get(followers_url).status_code == status.HTTP_404_NOT_FOUND

        # 7. Bob cannot follow deleted user
        follow_url = reverse("user-unified-follow")
        res_follow = bob_client.post(follow_url, {"target_id": str(user_alice.id), "target_type": "user"}, format="json")
        assert res_follow.status_code == status.HTTP_404_NOT_FOUND

        # 8. Login rejected for deleted user with clear prompt to restore
        anon_client = APIClient()
        login_url = "/api/v1/auth/login/"
        res_login_del = anon_client.post(
            login_url,
            {"email": user_alice.email, "password": "SecurePassword123!"},
            format="json",
        )
        assert res_login_del.status_code == status.HTTP_400_BAD_REQUEST
        err_msg = res_login_del.data.get("message") or res_login_del.data.get("detail")
        assert "deleted" in err_msg
        assert "restore" in err_msg

        # 9. Restore user account via login with restore=True
        res_restore = anon_client.post(
            login_url,
            {"email": user_alice.email, "password": "SecurePassword123!", "restore": True},
            format="json",
        )
        assert res_restore.status_code == status.HTTP_200_OK
        assert "restored" in res_restore.data["message"]
        assert "tokens" in res_restore.data

        user_alice.refresh_from_db()
        assert user_alice.status == UserStatus.ACTIVE
        assert user_alice.is_active is True
        assert user_alice.settings.is_deleted is False
