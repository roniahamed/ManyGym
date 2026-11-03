import uuid
from datetime import date, timedelta
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym, GymSetting, GymBlockedUser, GymFollow
from apps.gyms.services import create_gym, block_user_for_gym, update_gym_settings, follow_gym
from apps.members.models import Member
from apps.posts.models import GymPost
from apps.posts.services import create_post
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    AudienceMessagingEnum,
    AudienceJoiningRequestEnum,
    AudienceMembersVisibilityEnum,
    AudienceFollowingVisibilityEnum,
    PostsAgeRestrictionEnum,
    MemberJoiningStatus,
)


@pytest.fixture
def owner_user(db):
    user = User.objects.create_user(
        email="gym.owner@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, date_of_birth=date(1990, 1, 1))
    return user


@pytest.fixture
def member_user(db):
    user = User.objects.create_user(
        email="member.bob@example.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Member",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, date_of_birth=date(1995, 5, 15))
    return user


@pytest.fixture
def outsider_adult_user(db):
    user = User.objects.create_user(
        email="adult.outsider@example.com",
        password="SecurePassword123!",
        first_name="Charlie",
        last_name="Adult",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, date_of_birth=date(2000, 3, 20))
    return user


@pytest.fixture
def under_age_user(db):
    user = User.objects.create_user(
        email="teen.user@example.com",
        password="SecurePassword123!",
        first_name="Dave",
        last_name="Teen",
        is_verified=True,
    )
    # 16 years old
    sixteen_years_ago = timezone.now().date() - timedelta(days=16 * 365 + 10)
    UserProfile.objects.create(user=user, date_of_birth=sixteen_years_ago)
    return user


@pytest.fixture
def user_without_dob(db):
    user = User.objects.create_user(
        email="nodob.user@example.com",
        password="SecurePassword123!",
        first_name="NoDob",
        last_name="User",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, date_of_birth=None)
    return user


def make_client(user):
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def auth_client(owner_user):
    return make_client(owner_user)


@pytest.fixture
def member_client(member_user):
    return make_client(member_user)


@pytest.fixture
def outsider_client(outsider_adult_user):
    return make_client(outsider_adult_user)


@pytest.fixture
def teen_client(under_age_user):
    return make_client(under_age_user)


@pytest.fixture
def test_gym(owner_user):
    return create_gym(owner_user=owner_user, name="Iron Paradise")


@pytest.fixture
def staff_user(db, test_gym):
    user = User.objects.create_user(
        email="staff.sam@example.com",
        password="SecurePassword123!",
        first_name="Sam",
        last_name="Staff",
        is_verified=True,
    )
    from apps.access_control.models import GymStaffAssignment, Role
    from common.enums import StaffStatus
    role, _ = Role.objects.get_or_create(gym=test_gym, name="Trainer", defaults={"slug": "trainer"})
    GymStaffAssignment.objects.create(gym=test_gym, user=user, role=role, status=StaffStatus.ACTIVE)
    return user


@pytest.fixture
def staff_client(staff_user):
    return make_client(staff_user)


@pytest.fixture
def active_member(test_gym, member_user):
    return Member.objects.create(
        gym=test_gym,
        user=member_user,
        first_name=member_user.first_name,
        last_name=member_user.last_name,
        email=member_user.email,
        joining_status=MemberJoiningStatus.JOINED,
    )


def get_error_message(res):
    if isinstance(res.data, dict):
        return res.data.get("message") or res.data.get("detail") or str(res.data)
    return str(res.data)


def get_results_list(res):
    if isinstance(res.data, dict) and "results" in res.data:
        return res.data["results"]
    return res.data if isinstance(res.data, list) else []


# ============================================================================
# 1. Who can send you messages?
# ============================================================================

@pytest.mark.django_db
class TestAudienceMessagingSettings:

    def test_messaging_policy_enforcement(self, test_gym, owner_user, member_user, outsider_adult_user, active_member):
        from apps.messaging.permissions import can_user_message_gym
        from common.exceptions import DomainValidationError, PermissionDeniedError

        setting = test_gym.get_settings()

        # Policy: EVERYONE (default)
        assert can_user_message_gym(outsider_adult_user, test_gym) is True
        assert can_user_message_gym(member_user, test_gym) is True

        # Policy: MEMBERS_ONLY
        setting.who_can_message = AudienceMessagingEnum.MEMBERS_ONLY
        setting.save()
        assert can_user_message_gym(member_user, test_gym) is True
        with pytest.raises(DomainValidationError, match="enrolled gym members"):
            can_user_message_gym(outsider_adult_user, test_gym)

        # Policy: FOLLOWERS_AND_MEMBERS
        setting.who_can_message = AudienceMessagingEnum.FOLLOWERS_AND_MEMBERS
        setting.save()
        assert can_user_message_gym(member_user, test_gym) is True
        with pytest.raises(DomainValidationError, match="followers and members"):
            can_user_message_gym(outsider_adult_user, test_gym)

        # Outsider follows gym -> allowed
        GymFollow.objects.create(user=outsider_adult_user, gym=test_gym)
        assert can_user_message_gym(outsider_adult_user, test_gym) is True

        # Blocked user -> PermissionDeniedError
        GymBlockedUser.objects.create(gym=test_gym, user=outsider_adult_user)
        with pytest.raises(PermissionDeniedError, match="blocked"):
            can_user_message_gym(outsider_adult_user, test_gym)

    def test_messaging_gym_lifecycle_enforcement(self, test_gym, outsider_adult_user):
        from apps.messaging.permissions import can_user_message_gym
        from common.exceptions import DomainValidationError, ResourceNotFoundError

        setting = test_gym.get_settings()

        # Deactivated gym
        setting.is_deactivated = True
        setting.save()
        with pytest.raises(DomainValidationError, match="deactivated"):
            can_user_message_gym(outsider_adult_user, test_gym)

        # Deleted gym
        setting.is_deactivated = False
        setting.is_deleted = True
        setting.save()
        with pytest.raises(ResourceNotFoundError, match="not found"):
            can_user_message_gym(outsider_adult_user, test_gym)


# ============================================================================
# 2. Who can send you a Member joining request?
# ============================================================================

@pytest.mark.django_db
class TestAudienceJoiningRequestSettings:

    def test_joining_request_everyone_allowed(self, outsider_client, test_gym, outsider_adult_user):
        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        res = outsider_client.post(url, {"notes": "Interested in morning passes"}, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["status"] == "pending"
        assert res.data["gym_id"] == str(test_gym.id)

        # Status endpoint confirms pending request
        status_res = outsider_client.get(url)
        assert status_res.status_code == status.HTTP_200_OK
        assert status_res.data["has_pending_request"] is True
        assert status_res.data["can_send_request"] is False

    def test_joining_request_no_one_rejected(self, outsider_client, test_gym):
        update_gym_settings(test_gym, who_can_send_joining_request=AudienceJoiningRequestEnum.NO_ONE)

        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        res = outsider_client.post(url, {"notes": "Please let me join"}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert "not currently accepting" in get_error_message(res)

    def test_joining_request_already_member_rejected(self, member_client, test_gym, active_member):
        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        res = member_client.post(url, {}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "already a member" in get_error_message(res)

    def test_joining_request_blocked_user_rejected(self, outsider_client, test_gym, outsider_adult_user):
        block_user_for_gym(gym=test_gym, user_id=str(outsider_adult_user.id))

        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        res = outsider_client.post(url, {}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert "blocked" in get_error_message(res)

    def test_joining_request_deactivated_gym_rejected(self, outsider_client, test_gym):
        test_gym.get_settings().deactivate()
        test_gym.get_settings().save()

        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})
        res = outsider_client.post(url, {}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "deactivated" in get_error_message(res)


# ============================================================================
# 3. Who can see your Gym’s Members (Manygym users)?
# ============================================================================

@pytest.mark.django_db
class TestAudienceGymMembersVisibilitySettings:

    def test_members_visibility_everyone(self, outsider_client, test_gym, active_member):
        url = reverse("gyms_v1:gym-members-list", kwargs={"gym_id": test_gym.id})
        res = outsider_client.get(url)
        assert res.status_code == status.HTTP_200_OK
        results = get_results_list(res)
        assert len(results) == 1
        assert results[0]["email"] == active_member.email
        assert results[0]["first_name"] == active_member.first_name

    def test_members_visibility_only_members_restricted_for_outsider(self, outsider_client, test_gym, active_member):
        update_gym_settings(test_gym, who_can_see_members=AudienceMembersVisibilityEnum.ONLY_MEMBERS)

        url = reverse("gyms_v1:gym-members-list", kwargs={"gym_id": test_gym.id})
        res = outsider_client.get(url)
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert "Only gym members" in get_error_message(res)

    def test_members_visibility_only_members_allowed_for_enrolled_member(self, member_client, test_gym, active_member):
        update_gym_settings(test_gym, who_can_see_members=AudienceMembersVisibilityEnum.ONLY_MEMBERS)

        url = reverse("gyms_v1:gym-members-list", kwargs={"gym_id": test_gym.id})
        res = member_client.get(url)
        assert res.status_code == status.HTTP_200_OK
        results = get_results_list(res)
        assert len(results) == 1
        assert str(results[0]["member_id"]) == str(active_member.id)

    def test_members_visibility_only_members_allowed_for_owner(self, auth_client, test_gym, active_member):
        update_gym_settings(test_gym, who_can_see_members=AudienceMembersVisibilityEnum.ONLY_MEMBERS)

        url = reverse("gyms_v1:gym-members-list", kwargs={"gym_id": test_gym.id})
        res = auth_client.get(url)
        assert res.status_code == status.HTTP_200_OK
        results = get_results_list(res)
        assert len(results) == 1

    def test_members_visibility_blocked_user_forbidden(self, member_client, test_gym, member_user, active_member):
        # Even though member is enrolled, if blocked -> 403 Forbidden
        block_user_for_gym(gym=test_gym, user_id=str(member_user.id))

        url = reverse("gyms_v1:gym-members-list", kwargs={"gym_id": test_gym.id})
        res = member_client.get(url)
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert "blocked" in get_error_message(res)


# ============================================================================
# 4. Who can see the people and pages you follow?
# ============================================================================

@pytest.mark.django_db
class TestAudienceFollowingSettings:

    def test_following_visibility_everyone(self, outsider_client, test_gym):
        url = reverse("gyms_v1:gym-following-list", kwargs={"gym_id": test_gym.id})
        res = outsider_client.get(url)
        assert res.status_code == status.HTTP_200_OK

    def test_following_visibility_only_members(self, outsider_client, member_client, auth_client, test_gym, active_member):
        update_gym_settings(test_gym, who_can_see_following=AudienceFollowingVisibilityEnum.ONLY_MEMBERS)

        url = reverse("gyms_v1:gym-following-list", kwargs={"gym_id": test_gym.id})

        # Outsider -> 403
        res_out = outsider_client.get(url)
        assert res_out.status_code == status.HTTP_403_FORBIDDEN

        # Member -> 200
        res_mem = member_client.get(url)
        assert res_mem.status_code == status.HTTP_200_OK

        # Owner -> 200
        res_own = auth_client.get(url)
        assert res_own.status_code == status.HTTP_200_OK

    def test_following_visibility_private(self, outsider_client, member_client, auth_client, test_gym, active_member):
        update_gym_settings(test_gym, who_can_see_following=AudienceFollowingVisibilityEnum.PRIVATE)

        url = reverse("gyms_v1:gym-following-list", kwargs={"gym_id": test_gym.id})

        # Outsider -> 403
        assert outsider_client.get(url).status_code == status.HTTP_403_FORBIDDEN

        # Member -> 403
        assert member_client.get(url).status_code == status.HTTP_403_FORBIDDEN

        # Owner -> 200
        assert auth_client.get(url).status_code == status.HTTP_200_OK

    def test_following_and_followers_blocked_user_forbidden(self, outsider_client, test_gym, outsider_adult_user):
        block_user_for_gym(gym=test_gym, user_id=str(outsider_adult_user.id))

        url_following = reverse("gyms_v1:gym-following-list", kwargs={"gym_id": test_gym.id})
        url_followers = reverse("gyms_v1:gym-followers-list", kwargs={"gym_id": test_gym.id})

        assert outsider_client.get(url_following).status_code == status.HTTP_403_FORBIDDEN
        assert outsider_client.get(url_followers).status_code == status.HTTP_403_FORBIDDEN


# ============================================================================
# 5. Age restriction for your Gym’s posts
# ============================================================================

@pytest.mark.django_db
class TestPostsAgeRestrictionSettings:

    def test_posts_age_restriction_any_age(self, test_gym, owner_user, outsider_client, teen_client):
        create_post(gym=test_gym, author_user=owner_user, content_text="Welcome all ages to our gym!")

        # Both teen (16) and adult (20+) see post in feed
        feed_url = f"/api/v1/posts/?gym_id={test_gym.id}"
        res_teen = teen_client.get(feed_url)
        assert res_teen.status_code == status.HTTP_200_OK
        assert len(get_results_list(res_teen)) == 1

        res_adult = outsider_client.get(feed_url)
        assert res_adult.status_code == status.HTTP_200_OK
        assert len(get_results_list(res_adult)) == 1

    def test_posts_age_restriction_18_plus(self, test_gym, owner_user, outsider_client, teen_client, user_without_dob, auth_client):
        post = create_post(gym=test_gym, author_user=owner_user, content_text="18+ Heavy powerlifting competition!")
        update_gym_settings(test_gym, posts_age_restriction=PostsAgeRestrictionEnum.AGE_18_PLUS)

        feed_url = f"/api/v1/posts/?gym_id={test_gym.id}"
        detail_url = f"/api/v1/posts/{post.id}/?gym_id={test_gym.id}"

        # 1. Teen (16) -> Feed filtered (0 posts), Detail -> 403 Forbidden
        res_teen_feed = teen_client.get(feed_url)
        assert res_teen_feed.status_code == status.HTTP_200_OK
        assert len(get_results_list(res_teen_feed)) == 0

        res_teen_detail = teen_client.get(detail_url)
        assert res_teen_detail.status_code == status.HTTP_403_FORBIDDEN
        assert "age-restricted" in get_error_message(res_teen_detail)

        # 2. User with no DOB -> Feed filtered (0 posts), Detail -> 403 Forbidden
        nodob_client = make_client(user_without_dob)
        res_nodob_feed = nodob_client.get(feed_url)
        assert res_nodob_feed.status_code == status.HTTP_200_OK
        assert len(get_results_list(res_nodob_feed)) == 0

        res_nodob_detail = nodob_client.get(detail_url)
        assert res_nodob_detail.status_code == status.HTTP_403_FORBIDDEN

        # 3. Adult (20+) -> Feed shows post (1 post), Detail -> 200 OK
        res_adult_feed = outsider_client.get(feed_url)
        assert res_adult_feed.status_code == status.HTTP_200_OK
        assert len(get_results_list(res_adult_feed)) == 1

        res_adult_detail = outsider_client.get(detail_url)
        assert res_adult_detail.status_code == status.HTTP_200_OK
        assert res_adult_detail.data["id"] == str(post.id)

        # 4. Gym Owner is exempt
        res_owner_feed = auth_client.get(feed_url)
        assert len(get_results_list(res_owner_feed)) == 1

        res_owner_detail = auth_client.get(detail_url)
        assert res_owner_detail.status_code == status.HTTP_200_OK

    def test_posts_blocked_user_cannot_view(self, test_gym, owner_user, outsider_client, outsider_adult_user):
        post = create_post(gym=test_gym, author_user=owner_user, content_text="Regular community announcement")
        block_user_for_gym(gym=test_gym, user_id=str(outsider_adult_user.id))

        feed_url = f"/api/v1/posts/?gym_id={test_gym.id}"
        detail_url = f"/api/v1/posts/{post.id}/?gym_id={test_gym.id}"

        res_feed = outsider_client.get(feed_url)
        assert res_feed.status_code == status.HTTP_200_OK
        assert len(get_results_list(res_feed)) == 0

        res_detail = outsider_client.get(detail_url)
        assert res_detail.status_code == status.HTTP_403_FORBIDDEN
        assert "blocked" in get_error_message(res_detail)


# ============================================================================
# 6. Blocking & Block from Followers
# ============================================================================

@pytest.mark.django_db
class TestBlockingAndBlockFromFollowers:

    def test_blocking_follower_automatically_removes_follow(self, auth_client, test_gym, outsider_adult_user):
        # Outsider follows gym
        follow_gym(outsider_adult_user, test_gym.id)
        assert GymFollow.objects.filter(gym=test_gym, user=outsider_adult_user).exists()

        # Gym blocks the outsider
        block_user_for_gym(gym=test_gym, user_id=str(outsider_adult_user.id), reason="Misconduct")

        # Confirm GymFollow was automatically deleted upon block
        assert not GymFollow.objects.filter(gym=test_gym, user=outsider_adult_user).exists()
        assert GymBlockedUser.objects.filter(gym=test_gym, user=outsider_adult_user).exists()

    def test_block_directly_from_followers_endpoint(self, auth_client, test_gym, outsider_adult_user):
        # Outsider follows gym
        follow_gym(outsider_adult_user, test_gym.id)
        assert GymFollow.objects.filter(gym=test_gym, user=outsider_adult_user).exists()

        # Admin uses "Block from Followers" endpoint
        url = reverse("gyms_v1:gym-follower-block", kwargs={"gym_id": test_gym.id, "user_id": outsider_adult_user.id})
        res = auth_client.post(f"{url}?gym_id={test_gym.id}")
        assert res.status_code == status.HTTP_200_OK
        assert "successfully blocked" in res.data["message"]

        # Follow removed and user blocked
        assert not GymFollow.objects.filter(gym=test_gym, user=outsider_adult_user).exists()
        assert GymBlockedUser.objects.filter(gym=test_gym, user=outsider_adult_user).exists()


# ============================================================================
# 7. Visibility & Access & Control (Deactivate, Unpublish, Delete)
# ============================================================================

@pytest.mark.django_db
class TestAccessAndControlLifecycleTransitions:

    def test_deactivate_and_reactivate_gym(self, auth_client, test_gym, outsider_client):
        url = reverse("gyms_v1:gym-settings-access-control")

        # Deactivate
        res = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "deactivate"}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["is_deactivated"] is True
        assert res.data["deactivated_at"] is not None

        # Outsider attempting to follow deactivated gym fails
        follow_url = reverse("gyms_v1:gym-follow-toggle", kwargs={"gym_id": test_gym.id})
        res_follow = outsider_client.post(follow_url)
        assert res_follow.status_code == status.HTTP_400_BAD_REQUEST

        # Reactivate
        res_react = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "reactivate"}, format="json")
        assert res_react.status_code == status.HTTP_200_OK
        assert res_react.data["is_deactivated"] is False
        assert res_react.data["deactivated_at"] is None

        # Outsider can follow again
        res_follow_ok = outsider_client.post(follow_url)
        assert res_follow_ok.status_code == status.HTTP_201_CREATED

    def test_unpublish_and_publish_gym(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings-access-control")

        # Unpublish
        res = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "unpublish"}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["is_published"] is False
        assert res.data["unpublished_at"] is not None

        # Publish
        res_pub = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "publish"}, format="json")
        assert res_pub.status_code == status.HTTP_200_OK
        assert res_pub.data["is_published"] is True
        assert res_pub.data["unpublished_at"] is None

    def test_soft_delete_and_restore_gym(self, auth_client, test_gym, outsider_client):
        url = reverse("gyms_v1:gym-settings-access-control")

        # 1. Missing password
        res_no_pw = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"action": "delete", "confirmation": "delete"},
            format="json",
        )
        assert res_no_pw.status_code == status.HTTP_400_BAD_REQUEST

        # 2. Wrong password
        res_wrong_pw = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"action": "delete", "password": "WrongPassword!", "confirmation": "delete"},
            format="json",
        )
        assert res_wrong_pw.status_code == status.HTTP_400_BAD_REQUEST

        # 3. Missing confirmation text
        res_no_conf = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"action": "delete", "password": "SecurePassword123!"},
            format="json",
        )
        assert res_no_conf.status_code == status.HTTP_400_BAD_REQUEST

        # 4. Wrong confirmation word
        res_wrong_conf = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"action": "delete", "password": "SecurePassword123!", "confirmation": "remove"},
            format="json",
        )
        assert res_wrong_conf.status_code == status.HTTP_400_BAD_REQUEST

        # 5. Successful Delete with password + 'delete' confirmation
        res = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {
                "action": "delete",
                "password": "SecurePassword123!",
                "confirmation": "delete",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["is_deleted"] is True
        assert res.data["deleted_at"] is not None

        # Outsider gets 404
        members_url = reverse("gyms_v1:gym-members-list", kwargs={"gym_id": test_gym.id})
        assert outsider_client.get(members_url).status_code == status.HTTP_404_NOT_FOUND

        # Restore
        res_rest = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "restore"}, format="json")
        assert res_rest.status_code == status.HTTP_200_OK
        assert res_rest.data["is_deleted"] is False
        assert res_rest.data["deleted_at"] is None

    def test_unpublished_gym_visibility_rules(self, auth_client, outsider_client, member_client, staff_client, test_gym, active_member):
        """
        Unpublished gym rule:
        Staff and gym admin/owner can access and perform all actions.
        Outsiders and even regular members CANNOT view or access (404 Not Found).
        """
        url = reverse("gyms_v1:gym-settings-access-control")

        # Unpublish gym
        res_unpub = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "unpublish"}, format="json")
        assert res_unpub.status_code == status.HTTP_200_OK
        assert res_unpub.data["is_published"] is False

        members_url = reverse("gyms_v1:gym-members-list", kwargs={"gym_id": test_gym.id})
        followers_url = reverse("gyms_v1:gym-followers-list", kwargs={"gym_id": test_gym.id})
        following_url = reverse("gyms_v1:gym-following-list", kwargs={"gym_id": test_gym.id})
        feed_url = f"/api/v1/posts/?gym_id={test_gym.id}"

        # 1. Outsider gets 404 on all endpoints
        assert outsider_client.get(members_url).status_code == status.HTTP_404_NOT_FOUND
        assert outsider_client.get(followers_url).status_code == status.HTTP_404_NOT_FOUND
        assert outsider_client.get(following_url).status_code == status.HTTP_404_NOT_FOUND
        assert outsider_client.get(feed_url).status_code == status.HTTP_404_NOT_FOUND

        # 2. Regular enrolled member ALSO gets 404
        assert member_client.get(members_url).status_code == status.HTTP_404_NOT_FOUND
        assert member_client.get(followers_url).status_code == status.HTTP_404_NOT_FOUND
        assert member_client.get(following_url).status_code == status.HTTP_404_NOT_FOUND
        assert member_client.get(feed_url).status_code == status.HTTP_404_NOT_FOUND

        # 3. Active Staff member CAN access normally (200 OK)
        assert staff_client.get(members_url).status_code == status.HTTP_200_OK
        assert staff_client.get(followers_url).status_code == status.HTTP_200_OK
        assert staff_client.get(following_url).status_code == status.HTTP_200_OK
        assert staff_client.get(feed_url).status_code == status.HTTP_200_OK

        # 4. Gym Owner / Admin CAN access normally (200 OK)
        assert auth_client.get(members_url).status_code == status.HTTP_200_OK
        assert auth_client.get(followers_url).status_code == status.HTTP_200_OK
        assert auth_client.get(following_url).status_code == status.HTTP_200_OK
        assert auth_client.get(feed_url).status_code == status.HTTP_200_OK

    def test_deactivated_gym_login_notice_and_switch_context_prompt(self, auth_client, owner_user, test_gym):
        """
        Deactivated gym rule:
        - When logging in, shows notice asking if user wants to reactivate.
        - When switching context to deactivated gym, returns prominent reactivation prompt message.
        """
        from rest_framework.test import APIClient
        url_access = reverse("gyms_v1:gym-settings-access-control")

        # Deactivate gym
        res_deact = auth_client.post(f"{url_access}?gym_id={test_gym.id}", {"action": "deactivate"}, format="json")
        assert res_deact.status_code == status.HTTP_200_OK
        assert res_deact.data["is_deactivated"] is True

        # 1. Login attempt by owner: returns deactivation notice
        anon_client = APIClient()
        login_url = "/api/v1/auth/login/"
        res_login = anon_client.post(
            login_url,
            {"email": owner_user.email, "password": "SecurePassword123!"},
            format="json",
        )
        assert res_login.status_code == status.HTTP_200_OK
        assert res_login.data.get("has_deactivated_gym") is True
        assert "deactivation_notice" in res_login.data
        assert "is deactivated" in res_login.data["deactivation_notice"]
        assert "reactivate" in res_login.data["deactivation_notice"]

        # 2. Switch context to deactivated gym: returns message prompting reactivation
        switch_url = "/api/v1/auth/switch-context/"
        res_switch = auth_client.post(
            switch_url,
            {"context_type": "gym", "gym_id": str(test_gym.id)},
            format="json",
        )
        assert res_switch.status_code == status.HTTP_200_OK
        assert res_switch.data.get("is_deactivated") is True
        assert "deactivated" in res_switch.data["message"]
        assert "reactivate" in res_switch.data["message"]
