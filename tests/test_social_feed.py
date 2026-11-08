import uuid
import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.utils import timezone
from datetime import timedelta

from apps.users.models import User, UserProfile, UserFollow, UserBlockedUser
from apps.gyms.models import Gym, GymSetting, GymFollow, GymBlockedUser
from apps.members.models import Member
from apps.access_control.models import GymStaffAssignment
from apps.posts.models import GymPost
from apps.posts.services import create_post
from apps.posts.selectors import list_gym_feed
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, PostPrivacyEnum, PostsAgeRestrictionEnum, StaffStatus, MemberJoiningStatus


@pytest.fixture
def user_viewer(db):
    user = User.objects.create_user(
        email="viewer@manygym.com",
        password="Password123!",
        first_name="Viewer",
        last_name="User",
        is_verified=True,
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.date_of_birth = timezone.now().date() - timedelta(days=25 * 365)  # 25 years old
    profile.save()
    return user


@pytest.fixture
def viewer_client(user_viewer):
    token = issue_context_token(user=user_viewer, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def user_followed(db):
    user = User.objects.create_user(
        email="followed_trainer@manygym.com",
        password="Password123!",
        first_name="Followed",
        last_name="Trainer",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def user_stranger(db):
    user = User.objects.create_user(
        email="stranger@manygym.com",
        password="Password123!",
        first_name="Stranger",
        last_name="Guy",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def gym_connected(db, user_stranger):
    gym = Gym.objects.create(
        owner_user=user_stranger,
        name="Connected Fitness Gym",
        timezone="UTC",
    )
    GymSetting.objects.create(
        gym=gym,
        is_published=True,
        is_deactivated=False,
        is_deleted=False,
        posts_age_restriction=PostsAgeRestrictionEnum.ANY_AGE,
    )
    return gym


@pytest.fixture
def gym_followed(db, user_stranger):
    gym = Gym.objects.create(
        owner_user=user_stranger,
        name="Followed Athletic Club",
        timezone="UTC",
    )
    GymSetting.objects.create(
        gym=gym,
        is_published=True,
        is_deactivated=False,
        is_deleted=False,
        posts_age_restriction=PostsAgeRestrictionEnum.ANY_AGE,
    )
    return gym


@pytest.fixture
def gym_random(db, user_stranger):
    gym = Gym.objects.create(
        owner_user=user_stranger,
        name="Public Random Gym",
        timezone="UTC",
    )
    GymSetting.objects.create(
        gym=gym,
        is_published=True,
        is_deactivated=False,
        is_deleted=False,
        posts_age_restriction=PostsAgeRestrictionEnum.ANY_AGE,
    )
    return gym


@pytest.mark.django_db
class TestSocialCommunityFeed:
    """
    Tests for personalized social feed:
    - Posts of Followed list (Followed users and Followed gyms)
    - Posts of Connected Gym(s) (including members_only posts)
    - Public posts of any Users or Gyms
    """

    def test_feed_includes_followed_gym_posts(
        self, viewer_client, user_viewer, gym_followed, user_stranger
    ):
        # Viewer follows gym_followed
        GymFollow.objects.create(user=user_viewer, gym=gym_followed)

        post = create_post(
            gym=gym_followed,
            author_user=user_stranger,
            content_text="Special workout update from followed gym!",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        response = viewer_client.get("/api/v1/posts/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        post_ids = [p["id"] for p in results]
        assert str(post.id) in post_ids

        # Serializer metadata assertion
        post_data = next(p for p in results if p["id"] == str(post.id))
        assert post_data["is_following_gym"] is True
        assert post_data["gym_name"] == "Followed Athletic Club"

    def test_feed_includes_followed_user_posts(
        self, viewer_client, user_viewer, user_followed, gym_random
    ):
        # Viewer follows user_followed
        UserFollow.objects.create(follower=user_viewer, followed_user=user_followed)

        post = create_post(
            gym=gym_random,
            author_user=user_followed,
            content_text="Check out my new deadlift PR!",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        response = viewer_client.get("/api/v1/posts/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        post_ids = [p["id"] for p in results]
        assert str(post.id) in post_ids

        post_data = next(p for p in results if p["id"] == str(post.id))
        assert post_data["is_following_author"] is True

    def test_feed_includes_connected_gym_members_only_posts(
        self, viewer_client, user_viewer, gym_connected, user_stranger
    ):
        # User is connected to gym_connected as a member
        Member.objects.create(
            gym=gym_connected,
            user=user_viewer,
            email=user_viewer.email,
            first_name="Viewer",
            last_name="User",
            joining_status=MemberJoiningStatus.JOINED,
        )

        # Gym creates a members-only post and a public post
        members_post = create_post(
            gym=gym_connected,
            author_user=user_stranger,
            content_text="Member locker code: 4321",
            privacy=PostPrivacyEnum.MEMBERS_ONLY,
        )
        public_post = create_post(
            gym=gym_connected,
            author_user=user_stranger,
            content_text="Welcome new gym members!",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        response = viewer_client.get("/api/v1/posts/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        post_ids = [p["id"] for p in results]

        # Connected user sees BOTH public and members_only posts
        assert str(members_post.id) in post_ids
        assert str(public_post.id) in post_ids

        m_data = next(p for p in results if p["id"] == str(members_post.id))
        assert m_data["is_connected_gym"] is True

    def test_stranger_cannot_see_unconnected_gym_members_only_posts(
        self, viewer_client, gym_random, user_stranger
    ):
        # Gym creates members-only post
        secret_post = create_post(
            gym=gym_random,
            author_user=user_stranger,
            content_text="Secret members only post",
            privacy=PostPrivacyEnum.MEMBERS_ONLY,
        )

        response = viewer_client.get("/api/v1/posts/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        post_ids = [p["id"] for p in results]
        assert str(secret_post.id) not in post_ids

    def test_feed_shows_public_posts_of_any_users_or_gyms(
        self, viewer_client, gym_random, user_stranger
    ):
        # Viewer is neither following nor connected to gym_random or user_stranger
        public_post = create_post(
            gym=gym_random,
            author_user=user_stranger,
            content_text="Public announcement to the whole world!",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        response = viewer_client.get("/api/v1/posts/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        post_ids = [p["id"] for p in results]
        assert str(public_post.id) in post_ids

        post_data = next(p for p in results if p["id"] == str(public_post.id))
        assert post_data["is_connected_gym"] is False
        assert post_data["is_following_gym"] is False
        assert post_data["is_following_author"] is False

    def test_feed_filter_by_feed_type(
        self,
        viewer_client,
        user_viewer,
        gym_connected,
        gym_followed,
        gym_random,
        user_followed,
        user_stranger,
    ):
        # Setup:
        # 1. Connected gym
        Member.objects.create(
            gym=gym_connected,
            user=user_viewer,
            email=user_viewer.email,
            first_name="Viewer",
            last_name="User",
            joining_status=MemberJoiningStatus.JOINED,
        )
        post_connected = create_post(
            gym=gym_connected,
            author_user=user_stranger,
            content_text="Post in connected gym",
            privacy=PostPrivacyEnum.MEMBERS_ONLY,
        )

        # 2. Followed gym
        GymFollow.objects.create(user=user_viewer, gym=gym_followed)
        post_followed_gym = create_post(
            gym=gym_followed,
            author_user=user_stranger,
            content_text="Post in followed gym",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        # 3. Followed user
        UserFollow.objects.create(follower=user_viewer, followed_user=user_followed)
        post_followed_user = create_post(
            gym=gym_random,
            author_user=user_followed,
            content_text="Post by followed user",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        # 4. Pure public post (unconnected, unfollowed)
        post_public = create_post(
            gym=gym_random,
            author_user=user_stranger,
            content_text="Pure public stranger post",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        # Test A: feed_type=connected
        res_conn = viewer_client.get("/api/v1/posts/?feed_type=connected")
        assert res_conn.status_code == status.HTTP_200_OK
        conn_ids = [p["id"] for p in res_conn.json()["results"]]
        assert str(post_connected.id) in conn_ids
        assert str(post_followed_gym.id) not in conn_ids
        assert str(post_public.id) not in conn_ids

        # Test B: feed_type=followed
        res_flw = viewer_client.get("/api/v1/posts/?feed_type=followed")
        assert res_flw.status_code == status.HTTP_200_OK
        flw_ids = [p["id"] for p in res_flw.json()["results"]]
        assert str(post_followed_gym.id) in flw_ids
        assert str(post_followed_user.id) in flw_ids
        assert str(post_public.id) not in flw_ids

        # Test C: feed_type=public
        res_pub = viewer_client.get("/api/v1/posts/?feed_type=public")
        assert res_pub.status_code == status.HTTP_200_OK
        pub_ids = [p["id"] for p in res_pub.json()["results"]]
        assert str(post_public.id) in pub_ids
        assert str(post_followed_gym.id) in pub_ids
        assert str(post_followed_user.id) in pub_ids
        assert str(post_connected.id) not in pub_ids  # members_only is not in pure public

        # Test D: feed_type=all (default)
        res_all = viewer_client.get("/api/v1/posts/")
        assert res_all.status_code == status.HTTP_200_OK
        all_ids = [p["id"] for p in res_all.json()["results"]]
        assert str(post_connected.id) in all_ids
        assert str(post_followed_gym.id) in all_ids
        assert str(post_followed_user.id) in all_ids
        assert str(post_public.id) in all_ids

    def test_feed_alias_url(self, viewer_client, gym_random, user_stranger):
        # Verify /api/v1/posts/feed/ works identically
        post = create_post(
            gym=gym_random,
            author_user=user_stranger,
            content_text="Feed alias URL post test",
            privacy=PostPrivacyEnum.PUBLIC,
        )
        response = viewer_client.get("/api/v1/posts/feed/")
        assert response.status_code == status.HTTP_200_OK
        ids = [p["id"] for p in response.json()["results"]]
        assert str(post.id) in ids

    def test_feed_privacy_filtering(
        self, viewer_client, user_viewer, gym_connected, user_stranger
    ):
        Member.objects.create(
            gym=gym_connected,
            user=user_viewer,
            email=user_viewer.email,
            first_name="Viewer",
            last_name="User",
            joining_status=MemberJoiningStatus.JOINED,
        )
        post_m = create_post(
            gym=gym_connected,
            author_user=user_stranger,
            content_text="Only for members filter test",
            privacy=PostPrivacyEnum.MEMBERS_ONLY,
        )
        post_p = create_post(
            gym=gym_connected,
            author_user=user_stranger,
            content_text="Public filter test",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        # ?privacy=members_only
        res_m = viewer_client.get("/api/v1/posts/?privacy=members_only")
        assert res_m.status_code == status.HTTP_200_OK
        ids_m = [p["id"] for p in res_m.json()["results"]]
        assert str(post_m.id) in ids_m
        assert str(post_p.id) not in ids_m

        # ?privacy=public
        res_p = viewer_client.get("/api/v1/posts/?privacy=public")
        assert res_p.status_code == status.HTTP_200_OK
        ids_p = [p["id"] for p in res_p.json()["results"]]
        assert str(post_p.id) in ids_p
        assert str(post_m.id) not in ids_p

    def test_feed_excludes_blocked_gyms_and_users(
        self, viewer_client, user_viewer, gym_random, user_stranger, user_followed
    ):
        # 1. gym_random blocks user_viewer
        GymBlockedUser.objects.create(gym=gym_random, user=user_viewer)
        post_gym_blocked = create_post(
            gym=gym_random,
            author_user=user_stranger,
            content_text="Post from gym that blocked viewer",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        # 2. user_followed blocks user_viewer
        UserBlockedUser.objects.create(blocker=user_followed, blocked_user=user_viewer)
        gym_other = Gym.objects.create(
            owner_user=user_stranger,
            name="Other Gym",
            timezone="UTC",
        )
        GymSetting.objects.create(gym=gym_other, is_published=True, is_deactivated=False)
        post_user_blocked = create_post(
            gym=gym_other,
            author_user=user_followed,
            content_text="Post from author that blocked viewer",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        response = viewer_client.get("/api/v1/posts/")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        ids = [p["id"] for p in results]

        assert str(post_gym_blocked.id) not in ids
        assert str(post_user_blocked.id) not in ids

    def test_feed_enforces_posts_age_restriction(
        self, db, gym_random, user_stranger
    ):
        # Create underage user (15 years old)
        young_user = User.objects.create_user(
            email="youngster@manygym.com",
            password="Password123!",
            first_name="Young",
            last_name="Kid",
            is_verified=True,
        )
        profile, _ = UserProfile.objects.get_or_create(user=young_user)
        profile.date_of_birth = timezone.now().date() - timedelta(days=15 * 365)
        profile.save()

        # Gym has 18+ policy
        setting = gym_random.settings
        setting.posts_age_restriction = PostsAgeRestrictionEnum.AGE_18_PLUS
        setting.save()

        post = create_post(
            gym=gym_random,
            author_user=user_stranger,
            content_text="18+ adult powerlifting seminar",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        token = issue_context_token(user=young_user, context_type=TokenContextType.PERSONAL)
        young_client = APIClient()
        young_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")

        response = young_client.get("/api/v1/posts/")
        assert response.status_code == status.HTTP_200_OK
        ids = [p["id"] for p in response.json()["results"]]
        assert str(post.id) not in ids

    def test_unauthenticated_guest_sees_only_public_posts(
        self, gym_random, user_stranger
    ):
        anon_client = APIClient()
        post_pub = create_post(
            gym=gym_random,
            author_user=user_stranger,
            content_text="Guest visible public post",
            privacy=PostPrivacyEnum.PUBLIC,
        )
        post_sec = create_post(
            gym=gym_random,
            author_user=user_stranger,
            content_text="Guest invisible members post",
            privacy=PostPrivacyEnum.MEMBERS_ONLY,
        )

        response = anon_client.get("/api/v1/posts/")
        assert response.status_code == status.HTTP_200_OK
        ids = [p["id"] for p in response.json()["results"]]
        assert str(post_pub.id) in ids
        assert str(post_sec.id) not in ids
