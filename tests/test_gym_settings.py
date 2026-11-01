import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User
from apps.gyms.models import Gym, GymSetting, GymBlockedUser
from apps.gyms.services import create_gym
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    AudienceMessagingEnum,
    AudienceJoiningRequestEnum,
    AudienceMembersVisibilityEnum,
    AudienceFollowingVisibilityEnum,
    PostsAgeRestrictionEnum,
)


@pytest.fixture
def owner_user(db):
    return User.objects.create_user(
        email="gym.owner@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Owner",
        is_verified=True,
    )


@pytest.fixture
def second_user(db):
    return User.objects.create_user(
        email="member.bob@example.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Member",
        is_verified=True,
    )


@pytest.fixture
def unauthorized_user(db):
    return User.objects.create_user(
        email="unauth@example.com",
        password="SecurePassword123!",
        first_name="Eve",
        last_name="Hacker",
        is_verified=True,
    )


@pytest.fixture
def auth_client(owner_user):
    tokens = issue_context_token(owner_user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def test_gym(owner_user):
    return create_gym(owner_user=owner_user, name="Apex Fitness")


@pytest.mark.django_db
class TestGymSettings:

    def test_default_settings_created_with_gym(self, test_gym):
        assert hasattr(test_gym, "settings")
        settings_obj = test_gym.settings
        assert settings_obj.language == "en"
        assert settings_obj.video_autoplay is True
        assert settings_obj.dark_mode is False
        assert settings_obj.admin_logs_alerts is True
        assert settings_obj.issues_alerts is True
        assert settings_obj.who_can_message == AudienceMessagingEnum.EVERYONE
        assert settings_obj.who_can_send_joining_request == AudienceJoiningRequestEnum.EVERYONE
        assert settings_obj.who_can_see_members == AudienceMembersVisibilityEnum.EVERYONE
        assert settings_obj.who_can_see_following == AudienceFollowingVisibilityEnum.EVERYONE
        assert settings_obj.posts_age_restriction == PostsAgeRestrictionEnum.ANY_AGE
        assert settings_obj.is_deactivated is False
        assert settings_obj.is_published is True
        assert settings_obj.is_deleted is False

    def test_get_settings_endpoint(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings")
        res = auth_client.get(f"{url}?gym_id={test_gym.id}")
        assert res.status_code == status.HTTP_200_OK
        data = res.data
        assert data["gym_id"] == str(test_gym.id)
        assert data["language"] == "en"
        assert data["video_autoplay"] is True
        assert data["dark_mode"] is False
        assert data["admin_logs_alerts"] is True
        assert data["issues_alerts"] is True
        assert data["who_can_message"] == "everyone"
        assert data["who_can_send_joining_request"] == "everyone"
        assert data["who_can_see_members"] == "everyone"
        assert data["who_can_see_following"] == "everyone"
        assert data["posts_age_restriction"] == "any_age"
        assert data["is_deactivated"] is False
        assert data["is_published"] is True
        assert data["is_deleted"] is False

    def test_patch_settings_endpoint(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings")
        payload = {
            "language": "bn",
            "video_autoplay": False,
            "dark_mode": True,
            "admin_logs_alerts": False,
            "issues_alerts": False,
            "who_can_message": AudienceMessagingEnum.MEMBERS_ONLY,
            "who_can_send_joining_request": AudienceJoiningRequestEnum.NO_ONE,
            "who_can_see_members": AudienceMembersVisibilityEnum.ONLY_MEMBERS,
            "who_can_see_following": AudienceFollowingVisibilityEnum.PRIVATE,
            "posts_age_restriction": PostsAgeRestrictionEnum.AGE_18_PLUS,
        }
        res = auth_client.patch(f"{url}?gym_id={test_gym.id}", payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        data = res.data
        assert data["language"] == "bn"
        assert data["video_autoplay"] is False
        assert data["dark_mode"] is True
        assert data["admin_logs_alerts"] is False
        assert data["issues_alerts"] is False
        assert data["who_can_message"] == "members_only"
        assert data["who_can_send_joining_request"] == "no_one"
        assert data["who_can_see_members"] == "only_members"
        assert data["who_can_see_following"] == "private"
        assert data["posts_age_restriction"] == "18_plus"

        # Verify persisted in database
        test_gym.settings.refresh_from_db()
        assert test_gym.settings.language == "bn"
        assert test_gym.settings.dark_mode is True

    def test_blocking_flow(self, auth_client, test_gym, owner_user, second_user):
        search_url = reverse("gyms_v1:gym-settings-blocked-users-search")
        blocked_list_url = reverse("gyms_v1:gym-settings-blocked-users")

        # 1. Search users to block - Bob should appear, Alice (owner) must not
        res_search = auth_client.get(f"{search_url}?gym_id={test_gym.id}&q=Bob")
        assert res_search.status_code == status.HTTP_200_OK
        assert len(res_search.data) == 1
        assert res_search.data[0]["id"] == str(second_user.id)

        # 2. Cannot block gym owner
        res_fail = auth_client.post(
            f"{blocked_list_url}?gym_id={test_gym.id}",
            {"user_id": str(owner_user.id), "reason": "Self block"},
            format="json",
        )
        assert res_fail.status_code == status.HTTP_400_BAD_REQUEST

        # 3. Block Bob
        res_block = auth_client.post(
            f"{blocked_list_url}?gym_id={test_gym.id}",
            {"user_id": str(second_user.id), "reason": "Spam comments"},
            format="json",
        )
        assert res_block.status_code == status.HTTP_201_CREATED
        assert res_block.data["user_id"] == str(second_user.id)
        assert res_block.data["reason"] == "Spam comments"

        # 4. List blocked users
        res_list = auth_client.get(f"{blocked_list_url}?gym_id={test_gym.id}")
        assert res_list.status_code == status.HTTP_200_OK
        assert len(res_list.data) == 1
        assert res_list.data[0]["email"] == second_user.email

        # 5. Search should now exclude Bob since Bob is already blocked
        res_search_after = auth_client.get(f"{search_url}?gym_id={test_gym.id}&q=Bob")
        assert len(res_search_after.data) == 0

        # 6. Unblock Bob
        detail_url = reverse("gyms_v1:gym-settings-blocked-user-detail", kwargs={"user_id": second_user.id})
        res_unblock = auth_client.delete(f"{detail_url}?gym_id={test_gym.id}")
        assert res_unblock.status_code == status.HTTP_200_OK

        # 7. List should be empty now
        res_list_after = auth_client.get(f"{blocked_list_url}?gym_id={test_gym.id}")
        assert len(res_list_after.data) == 0

    def test_access_control_actions(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings-access-control")

        # Deactivate
        res_deact = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "deactivate"}, format="json")
        assert res_deact.status_code == status.HTTP_200_OK
        assert res_deact.data["is_deactivated"] is True
        assert res_deact.data["deactivated_at"] is not None

        # Reactivate
        res_react = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "reactivate"}, format="json")
        assert res_react.status_code == status.HTTP_200_OK
        assert res_react.data["is_deactivated"] is False
        assert res_react.data["deactivated_at"] is None

        # Unpublish
        res_unpub = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "unpublish"}, format="json")
        assert res_unpub.status_code == status.HTTP_200_OK
        assert res_unpub.data["is_published"] is False
        assert res_unpub.data["unpublished_at"] is not None

        # Publish
        res_pub = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "publish"}, format="json")
        assert res_pub.status_code == status.HTTP_200_OK
        assert res_pub.data["is_published"] is True
        assert res_pub.data["unpublished_at"] is None

        # Delete
        res_del = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "delete"}, format="json")
        assert res_del.status_code == status.HTTP_200_OK
        assert res_del.data["is_deleted"] is True
        assert res_del.data["deleted_at"] is not None

        # Restore
        res_rest = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "restore"}, format="json")
        assert res_rest.status_code == status.HTTP_200_OK
        assert res_rest.data["is_deleted"] is False
        assert res_rest.data["deleted_at"] is None

    def test_unauthorized_user_forbidden(self, unauthorized_user, test_gym):
        tokens = issue_context_token(unauthorized_user, context_type=TokenContextType.PERSONAL)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        url = reverse("gyms_v1:gym-settings")
        res = client.get(f"{url}?gym_id={test_gym.id}")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        res_patch = client.patch(f"{url}?gym_id={test_gym.id}", {"dark_mode": True}, format="json")
        assert res_patch.status_code == status.HTTP_403_FORBIDDEN
