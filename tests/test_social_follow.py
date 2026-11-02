import uuid
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile, UserFollow
from apps.users.services import update_user_profile
from apps.gyms.models import Gym, GymFollow, GymBlockedUser
from apps.gyms.services import create_gym, block_user_for_gym
from apps.members.models import Member
from apps.members.services import create_member, accept_member_invitation
from apps.messaging.permissions import can_user_message_gym
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, AudienceMessagingEnum, MemberJoiningStatus


@pytest.fixture
def user_alice(db):
    user = User.objects.create_user(
        email="alice@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Walker",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def user_bob(db):
    user = User.objects.create_user(
        email="bob@example.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Builder",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
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
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.is_private = True
    profile.save()
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
    return create_gym(
        owner_user=user_alice,
        name="Titan Fitness Hub",
        short_description="Top tier strength and conditioning fitness club with luxury sauna and modern facilities." * 2,
    )


class TestUserFollowFlow:
    """Tests user-to-user following, unfollowing, and privacy rules."""

    def test_follow_public_user_success(self, client_alice, user_alice, user_bob):
        # Alice follows public user Bob
        response = client_alice.post(f"/api/v1/users/{user_bob.id}/follow/")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["is_following"] is True
        assert data["target_user_id"] == str(user_bob.id)
        assert UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

    def test_follow_user_idempotent(self, client_alice, user_alice, user_bob):
        # First follow
        client_alice.post(f"/api/v1/users/{user_bob.id}/follow/")
        # Second follow (should return 200 OK without creating duplicate)
        response = client_alice.post(f"/api/v1/users/{user_bob.id}/follow/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_following"] is True
        assert UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).count() == 1

    def test_cannot_follow_self(self, client_alice, user_alice):
        response = client_alice.post(f"/api/v1/users/{user_alice.id}/follow/")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_follow_nonexistent_user(self, client_alice):
        random_id = uuid.uuid4()
        response = client_alice.post(f"/api/v1/users/{random_id}/follow/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_follow_private_user(self, client_alice, user_charlie):
        # Charlie is private
        response = client_alice.post(f"/api/v1/users/{user_charlie.id}/follow/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        data = response.json()
        assert "private" in str(data).lower()
        assert not UserFollow.objects.filter(followed_user=user_charlie).exists()

    def test_unfollow_user_success(self, client_alice, user_alice, user_bob):
        # Follow first
        client_alice.post(f"/api/v1/users/{user_bob.id}/follow/")
        assert UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

        # Unfollow
        response = client_alice.delete(f"/api/v1/users/{user_bob.id}/follow/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_following"] is False
        assert not UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

    def test_unfollow_not_followed_returns_404(self, client_alice, user_bob):
        response = client_alice.delete(f"/api/v1/users/{user_bob.id}/follow/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_list_followers_and_following(self, client_alice, client_bob, user_alice, user_bob):
        # Alice follows Bob
        client_alice.post(f"/api/v1/users/{user_bob.id}/follow/")

        # List Bob's followers -> should show Alice
        res_followers = client_bob.get(f"/api/v1/users/{user_bob.id}/followers/")
        assert res_followers.status_code == status.HTTP_200_OK
        followers = res_followers.json()
        assert len(followers) == 1
        assert followers[0]["email"] == user_alice.email

        # List Alice's following -> should show Bob
        res_following = client_alice.get(f"/api/v1/users/{user_alice.id}/following/")
        assert res_following.status_code == status.HTTP_200_OK
        following = res_following.json()
        assert len(following) == 1
        assert following[0]["email"] == user_bob.email

    def test_private_user_followers_list_restricted(self, client_alice, user_charlie):
        # Charlie is private; Alice cannot list Charlie's followers
        response = client_alice.get(f"/api/v1/users/{user_charlie.id}/followers/")
        assert response.status_code == status.HTTP_403_FORBIDDEN


class TestGymFollowFlow:
    """Tests user-to-gym following, unfollowing, and blocklists."""

    def test_follow_gym_success(self, client_bob, user_bob, gym_instance):
        response = client_bob.post(f"/api/v1/gyms/{gym_instance.id}/follow/")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["is_following"] is True
        assert data["gym_id"] == str(gym_instance.id)
        assert GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

    def test_follow_gym_idempotent(self, client_bob, user_bob, gym_instance):
        client_bob.post(f"/api/v1/gyms/{gym_instance.id}/follow/")
        response = client_bob.post(f"/api/v1/gyms/{gym_instance.id}/follow/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_following"] is True
        assert GymFollow.objects.filter(user=user_bob, gym=gym_instance).count() == 1

    def test_follow_gym_blocked_user_rejected(self, client_bob, user_alice, user_bob, gym_instance):
        # Alice (owner) blocks Bob
        block_user_for_gym(gym=gym_instance, user_id=str(user_bob.id), blocked_by_user=user_alice)
        assert GymBlockedUser.objects.filter(gym=gym_instance, user=user_bob).exists()

        # Bob attempts to follow gym
        response = client_bob.post(f"/api/v1/gyms/{gym_instance.id}/follow/")
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

    def test_unfollow_gym_success(self, client_bob, user_bob, gym_instance):
        # Follow first
        client_bob.post(f"/api/v1/gyms/{gym_instance.id}/follow/")
        assert GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

        # Unfollow
        response = client_bob.delete(f"/api/v1/gyms/{gym_instance.id}/follow/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_following"] is False
        assert not GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

    def test_unfollow_gym_not_following_returns_404(self, client_bob, gym_instance):
        response = client_bob.delete(f"/api/v1/gyms/{gym_instance.id}/follow/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_list_gym_followers(self, client_bob, user_bob, gym_instance):
        client_bob.post(f"/api/v1/gyms/{gym_instance.id}/follow/")
        response = client_bob.get(f"/api/v1/gyms/{gym_instance.id}/followers/")
        assert response.status_code == status.HTTP_200_OK
        followers = response.json()
        assert len(followers) == 1
        assert followers[0]["email"] == user_bob.email

    def test_list_followed_gyms_by_user(self, client_bob, gym_instance):
        client_bob.post(f"/api/v1/gyms/{gym_instance.id}/follow/")
        response = client_bob.get("/api/v1/gyms/followed/")
        assert response.status_code == status.HTTP_200_OK
        gyms = response.json()
        assert len(gyms) == 1
        assert gyms[0]["gym_id"] == str(gym_instance.id)


class TestGymMemberAutoFollow:
    """Tests that gym members automatically follow their connected gyms by default and can unfollow later."""

    def test_member_auto_follows_gym_on_invitation_accept(self, user_bob, gym_instance):
        # 1. Create a member invitation for Bob
        member = create_member(
            gym=gym_instance,
            first_name="Bob",
            last_name="Builder",
            email="bob@example.com",
        )
        assert member.joining_status == MemberJoiningStatus.SENT_INVITATION
        assert not GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

        # 2. Bob accepts the invitation
        accept_member_invitation(token=member.invitation_token, user=user_bob)

        # 3. Bob MUST now automatically follow the gym
        assert GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

    def test_auto_followed_member_can_unfollow_later(self, client_bob, user_bob, gym_instance):
        # Member accepted invitation and auto-followed
        member = create_member(
            gym=gym_instance,
            first_name="Bob",
            last_name="Builder",
            email="bob@example.com",
        )
        accept_member_invitation(token=member.invitation_token, user=user_bob)
        assert GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

        # Bob decides to unfollow later
        response = client_bob.delete(f"/api/v1/gyms/{gym_instance.id}/follow/")
        assert response.status_code == status.HTTP_200_OK
        assert not GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

    def test_messaging_audience_policy_followers_and_members(self, user_bob, gym_instance):
        # Set gym policy to followers and members only
        settings_obj = gym_instance.get_settings()
        settings_obj.who_can_message = AudienceMessagingEnum.FOLLOWERS_AND_MEMBERS
        settings_obj.save()

        # Bob is NOT following and NOT a member -> should raise validation error
        with pytest.raises(Exception) as excinfo:
            can_user_message_gym(user_bob, gym_instance)
        assert "followers and members" in str(excinfo.value).lower()

        # Bob follows the gym
        GymFollow.objects.create(user=user_bob, gym=gym_instance)

        # Now Bob is allowed to message the gym
        assert can_user_message_gym(user_bob, gym_instance) is True


class TestUnifiedFollowAPI:
    """Tests the unified follow/unfollow endpoint (/api/v1/follows/)."""

    def test_unified_follow_user_post(self, client_alice, user_alice, user_bob):
        # Alice follows public user Bob via POST /api/v1/follows/
        payload = {
            "target_type": "user",
            "target_id": str(user_bob.id),
        }
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["is_following"] is True
        assert data["target_type"] == "user"
        assert data["target_id"] == str(user_bob.id)
        assert UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

    def test_unified_unfollow_user_delete(self, client_alice, user_alice, user_bob):
        # Follow first
        UserFollow.objects.create(follower=user_alice, followed_user=user_bob)

        # Unfollow via DELETE /api/v1/follows/ with JSON body
        payload = {
            "target_type": "user",
            "target_id": str(user_bob.id),
        }
        response = client_alice.delete("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["is_following"] is False
        assert not UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

    def test_unified_unfollow_user_query_params(self, client_alice, user_alice, user_bob):
        # Follow first
        UserFollow.objects.create(follower=user_alice, followed_user=user_bob)

        # Unfollow via DELETE /api/v1/follows/?target_type=user&target_id=...
        response = client_alice.delete(f"/api/v1/follows/?target_type=user&target_id={user_bob.id}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_following"] is False
        assert not UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

    def test_unified_unfollow_user_post_action(self, client_alice, user_alice, user_bob):
        # Follow first
        UserFollow.objects.create(follower=user_alice, followed_user=user_bob)

        # Unfollow via POST /api/v1/follows/ with action="unfollow"
        payload = {
            "target_type": "user",
            "target_id": str(user_bob.id),
            "action": "unfollow",
        }
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_following"] is False
        assert not UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

    def test_unified_follow_gym_post(self, client_bob, user_bob, gym_instance):
        # Bob follows gym via POST /api/v1/follows/
        payload = {
            "target_type": "gym",
            "target_id": str(gym_instance.id),
        }
        response = client_bob.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["is_following"] is True
        assert data["target_type"] == "gym"
        assert data["target_id"] == str(gym_instance.id)
        assert data["target_name"] == gym_instance.name
        assert GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

    def test_unified_unfollow_gym_delete(self, client_bob, user_bob, gym_instance):
        # Follow first
        GymFollow.objects.create(user=user_bob, gym=gym_instance)

        # Unfollow via DELETE /api/v1/follows/
        payload = {
            "target_type": "gym",
            "target_id": str(gym_instance.id),
        }
        response = client_bob.delete("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_following"] is False
        assert not GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

    def test_unified_follow_invalid_target_type(self, client_alice, user_bob):
        payload = {
            "target_type": "invalid_entity",
            "target_id": str(user_bob.id),
        }
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_unified_follow_private_user_rejected(self, client_alice, user_charlie):
        payload = {
            "target_type": "user",
            "target_id": str(user_charlie.id),
        }
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_auto_detect_follow_user_without_target_type(self, client_alice, user_alice, user_bob):
        # target_type is completely omitted! Auto-detected as user
        payload = {
            "target_id": str(user_bob.id),
        }
        response = client_alice.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["is_following"] is True
        assert data["target_type"] == "user"
        assert data["target_id"] == str(user_bob.id)
        assert UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

    def test_auto_detect_follow_gym_without_target_type(self, client_bob, user_bob, gym_instance):
        # target_type is completely omitted! Auto-detected as gym
        payload = {
            "target_id": str(gym_instance.id),
        }
        response = client_bob.post("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["is_following"] is True
        assert data["target_type"] == "gym"
        assert data["target_id"] == str(gym_instance.id)
        assert data["target_name"] == gym_instance.name
        assert GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

    def test_auto_detect_unfollow_user_without_target_type(self, client_alice, user_alice, user_bob):
        UserFollow.objects.create(follower=user_alice, followed_user=user_bob)

        # Unfollow with ONLY target_id
        payload = {
            "target_id": str(user_bob.id),
        }
        response = client_alice.delete("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_following"] is False
        assert response.json()["target_type"] == "user"
        assert not UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

    def test_auto_detect_unfollow_gym_without_target_type(self, client_bob, user_bob, gym_instance):
        GymFollow.objects.create(user=user_bob, gym=gym_instance)

        # Unfollow with ONLY target_id
        payload = {
            "target_id": str(gym_instance.id),
        }
        response = client_bob.delete("/api/v1/follows/", data=payload, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["is_following"] is False
        assert response.json()["target_type"] == "gym"
        assert not GymFollow.objects.filter(user=user_bob, gym=gym_instance).exists()

    def test_follow_and_unfollow_via_path_param_auto_detect(self, client_alice, user_alice, user_bob, gym_instance):
        # 1. Follow User via URL path POST /api/v1/follows/<target_id>/
        res_follow_user = client_alice.post(f"/api/v1/follows/{user_bob.id}/")
        assert res_follow_user.status_code == status.HTTP_201_CREATED
        assert res_follow_user.json()["target_type"] == "user"
        assert UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

        # 2. Unfollow User via URL path DELETE /api/v1/follows/<target_id>/
        res_unfollow_user = client_alice.delete(f"/api/v1/follows/{user_bob.id}/")
        assert res_unfollow_user.status_code == status.HTTP_200_OK
        assert res_unfollow_user.json()["is_following"] is False
        assert not UserFollow.objects.filter(follower=user_alice, followed_user=user_bob).exists()

        # 3. Follow Gym via URL path POST /api/v1/follows/<target_id>/
        res_follow_gym = client_alice.post(f"/api/v1/follows/{gym_instance.id}/")
        assert res_follow_gym.status_code == status.HTTP_201_CREATED
        assert res_follow_gym.json()["target_type"] == "gym"
        assert GymFollow.objects.filter(user=user_alice, gym=gym_instance).exists()

        # 4. Unfollow Gym via URL path DELETE /api/v1/follows/<target_id>/
        res_unfollow_gym = client_alice.delete(f"/api/v1/follows/{gym_instance.id}/")
        assert res_unfollow_gym.status_code == status.HTTP_200_OK
        assert res_unfollow_gym.json()["is_following"] is False
        assert not GymFollow.objects.filter(user=user_alice, gym=gym_instance).exists()



