import io
import uuid
from datetime import timedelta

import pytest
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.access_control.models import GymStaffAssignment, Role
from apps.access_control.services import seed_default_permissions_and_roles
from apps.authentication.services import issue_context_token
from apps.gyms.models import Gym, GymBlockedUser, GymFollow, GymSetting
from apps.members.models import Member
from apps.posts.models import GymPost
from apps.posts.services import create_post
from apps.stories.models import Story
from apps.users.models import User, UserBlockedUser, UserFollow, UserProfile
from common.enums import (
    MemberJoiningStatus,
    PostOwnerTypeEnum,
    PostPrivacyEnum,
    PostsAgeRestrictionEnum,
    StaffStatus,
    StoryOwnerTypeEnum,
    StoryPrivacyEnum,
    TokenContextType,
)


def _make_image(filename="repost_img.jpg", fmt="JPEG", size=(400, 400)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=(40, 140, 220)).save(buf, format=fmt)
    buf.seek(0)
    return SimpleUploadedFile(filename, buf.read(), content_type="image/jpeg")


def _auth_client(user, context_type=TokenContextType.PERSONAL, gym=None):
    token = issue_context_token(user=user, context_type=context_type, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def repost_env(db):
    seed_default_permissions_and_roles()

    alice = User.objects.create_user(
        email="alice_repost@manygym.com",
        password="Password123!",
        first_name="Alice",
        last_name="Athlete",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=alice)
    alice.profile.date_of_birth = timezone.now().date() - timedelta(days=25 * 365)
    alice.profile.save()

    bob = User.objects.create_user(
        email="bob_repost@manygym.com",
        password="Password123!",
        first_name="Bob",
        last_name="Follower",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=bob)
    bob.profile.date_of_birth = timezone.now().date() - timedelta(days=24 * 365)
    bob.profile.save()

    carol = User.objects.create_user(
        email="carol_repost@manygym.com",
        password="Password123!",
        first_name="Carol",
        last_name="Stranger",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=carol)
    carol.profile.date_of_birth = timezone.now().date() - timedelta(days=26 * 365)
    carol.profile.save()

    gym_owner = User.objects.create_user(
        email="owner_repost@manygym.com",
        password="Password123!",
        first_name="Gym",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=gym_owner)

    limited_staff = User.objects.create_user(
        email="limited_repost@manygym.com",
        password="Password123!",
        first_name="Limited",
        last_name="Staff",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=limited_staff)

    gym = Gym.objects.create(
        owner_user=gym_owner,
        name="Titan Strength Club",
        timezone="UTC",
    )
    GymSetting.objects.create(
        gym=gym,
        is_published=True,
        is_deactivated=False,
        is_deleted=False,
        posts_age_restriction=PostsAgeRestrictionEnum.ANY_AGE,
    )

    no_perm_role = Role.objects.create(
        gym=gym,
        slug="front_desk_no_posts",
        name="Front Desk",
        is_custom=True,
    )
    GymStaffAssignment.objects.create(
        gym=gym,
        user=limited_staff,
        role=no_perm_role,
        status=StaffStatus.ACTIVE,
    )

    # Bob follows Alice and follows Gym; Alice is a Member of Gym
    UserFollow.objects.create(follower=bob, followed_user=alice)
    GymFollow.objects.create(user=bob, gym=gym)
    Member.objects.create(
        gym=gym,
        user=alice,
        email=alice.email,
        first_name=alice.first_name,
        last_name=alice.last_name,
        joining_status=MemberJoiningStatus.JOINED,
    )

    return {
        "alice": alice,
        "bob": bob,
        "carol": carol,
        "gym_owner": gym_owner,
        "limited_staff": limited_staff,
        "gym": gym,
        "alice_client": _auth_client(alice, TokenContextType.PERSONAL),
        "bob_client": _auth_client(bob, TokenContextType.PERSONAL),
        "carol_client": _auth_client(carol, TokenContextType.PERSONAL),
        "owner_personal_client": _auth_client(gym_owner, TokenContextType.PERSONAL),
        "gym_client": _auth_client(gym_owner, TokenContextType.GYM, gym=gym),
        "limited_gym_client": _auth_client(limited_staff, TokenContextType.GYM, gym=gym),
        "anon_client": APIClient(),
    }


@pytest.mark.django_db
class TestPersonalUserPostsAndPrivacy:
    def test_personal_user_can_create_update_delete_post_and_enforce_privacy(self, repost_env):
        alice = repost_env["alice"]
        alice_client = repost_env["alice_client"]
        bob_client = repost_env["bob_client"]
        carol_client = repost_env["carol_client"]
        anon_client = repost_env["anon_client"]

        # 1. Personal user cannot use members_only privacy
        res_bad = alice_client.post(
            "/api/v1/posts/",
            {"content_text": "Invalid privacy", "privacy": "members_only"},
            format="json",
        )
        assert res_bad.status_code == status.HTTP_400_BAD_REQUEST

        # 2. Personal user creates public, followers, and private posts
        res_pub = alice_client.post(
            "/api/v1/posts/",
            {"content_text": "Alice public PR!", "privacy": "public"},
            format="json",
        )
        assert res_pub.status_code == status.HTTP_201_CREATED
        assert res_pub.data["owner_type"] == PostOwnerTypeEnum.USER
        assert res_pub.data["gym_id"] is None
        pub_id = res_pub.data["id"]

        res_flw = alice_client.post(
            "/api/v1/posts/",
            {"content_text": "Alice followers-only tip", "privacy": "followers"},
            format="json",
        )
        assert res_flw.status_code == status.HTTP_201_CREATED
        flw_id = res_flw.data["id"]

        res_priv = alice_client.post(
            "/api/v1/posts/",
            {"content_text": "Alice private diary", "privacy": "private"},
            format="json",
        )
        assert res_priv.status_code == status.HTTP_201_CREATED
        priv_id = res_priv.data["id"]

        # 3. Profile feed visibility (?user_id=alice.id)
        # Alice sees all 3 on /posts/my/ and ?user_id=alice.id
        res_my = alice_client.get("/api/v1/posts/my/")
        assert res_my.status_code == status.HTTP_200_OK
        my_ids = [p["id"] for p in res_my.data["results"]]
        assert {pub_id, flw_id, priv_id}.issubset(set(my_ids))

        # Bob (follower) sees public + followers, NOT private
        res_bob_profile = bob_client.get(f"/api/v1/posts/?user_id={alice.id}")
        assert res_bob_profile.status_code == status.HTTP_200_OK
        bob_ids = [p["id"] for p in res_bob_profile.data["results"]]
        assert pub_id in bob_ids
        assert flw_id in bob_ids
        assert priv_id not in bob_ids

        # Carol (non-follower) sees ONLY public
        res_carol_profile = carol_client.get(f"/api/v1/posts/?user_id={alice.id}")
        assert res_carol_profile.status_code == status.HTTP_200_OK
        carol_ids = [p["id"] for p in res_carol_profile.data["results"]]
        assert pub_id in carol_ids
        assert flw_id not in carol_ids
        assert priv_id not in carol_ids

        # Guest sees ONLY public
        res_anon = anon_client.get(f"/api/v1/posts/?user_id={alice.id}")
        assert res_anon.status_code == status.HTTP_200_OK
        anon_ids = [p["id"] for p in res_anon.data["results"]]
        assert pub_id in anon_ids
        assert flw_id not in anon_ids
        assert priv_id not in anon_ids

        # Detail endpoint enforces 403 for followers/private
        assert carol_client.get(f"/api/v1/posts/{flw_id}/").status_code == status.HTTP_403_FORBIDDEN
        assert bob_client.get(f"/api/v1/posts/{priv_id}/").status_code == status.HTTP_403_FORBIDDEN
        assert bob_client.get(f"/api/v1/posts/{flw_id}/").status_code == status.HTTP_200_OK

        # 4. Non-owner cannot PATCH/DELETE personal user post
        assert bob_client.patch(f"/api/v1/posts/{pub_id}/", {"content_text": "Hack"}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert bob_client.delete(f"/api/v1/posts/{pub_id}/").status_code == status.HTTP_403_FORBIDDEN

        # 5. Owner cannot PATCH personal user post to members_only
        assert alice_client.patch(f"/api/v1/posts/{pub_id}/", {"privacy": "members_only"}, format="json").status_code == status.HTTP_400_BAD_REQUEST

        # 6. Owner can update & delete own post
        res_patch = alice_client.patch(f"/api/v1/posts/{pub_id}/", {"content_text": "Updated PR!", "privacy": "followers"}, format="json")
        assert res_patch.status_code == status.HTTP_200_OK
        assert res_patch.data["content_text"] == "Updated PR!"
        assert res_patch.data["privacy"] == "followers"

        res_del = alice_client.delete(f"/api/v1/posts/{priv_id}/")
        assert res_del.status_code == status.HTTP_200_OK
        assert not GymPost.objects.filter(id=priv_id).exists()


@pytest.mark.django_db
class TestRepostToProfileAndStory:
    def test_user_reposts_another_user_post_and_own_previous_post_to_profile(self, repost_env):
        alice = repost_env["alice"]
        bob = repost_env["bob"]
        alice_client = repost_env["alice_client"]
        bob_client = repost_env["bob_client"]
        carol_client = repost_env["carol_client"]

        # Alice creates a public post with an image
        img = _make_image("alice_pr.jpg")
        alice_post = create_post(
            author_user=alice,
            owner_type=PostOwnerTypeEnum.USER,
            content_text="Deadlift 180kg today!",
            privacy=PostPrivacyEnum.PUBLIC,
            media_files=[img],
        )

        # 1. Bob reposts Alice's post onto Bob's profile feed with optional commentary
        res_repost = bob_client.post(
            f"/api/v1/posts/{alice_post.id}/repost/",
            {
                "target": "profile",
                "privacy": "public",
                "content_text": "Inspiring lift!",
            },
            format="json",
        )
        assert res_repost.status_code == status.HTTP_201_CREATED
        assert res_repost.data["target"] == "profile"
        assert res_repost.data["owner_type"] == PostOwnerTypeEnum.USER
        assert res_repost.data["author_user_id"] == str(bob.id)
        assert res_repost.data["gym_id"] is None
        assert res_repost.data["is_repost"] is True
        assert res_repost.data["source_post_id"] == str(alice_post.id)
        assert res_repost.data["source_post"]["id"] == str(alice_post.id)
        assert res_repost.data["source_post"]["content_text"] == "Deadlift 180kg today!"
        assert res_repost.data["source_post_unavailable"] is False
        assert res_repost.data["content_text"] == "Inspiring lift!"

        alice_post.refresh_from_db()
        assert alice_post.reposts_count == 1

        # Repost appears on Bob's profile feed (?user_id=bob.id) and /posts/my/ and global feed
        res_bob_profile = carol_client.get(f"/api/v1/posts/?user_id={bob.id}")
        assert res_bob_profile.status_code == status.HTTP_200_OK
        assert res_repost.data["id"] in [p["id"] for p in res_bob_profile.data["results"]]

        res_bob_my = bob_client.get("/api/v1/posts/my/?is_repost=true")
        assert res_bob_my.status_code == status.HTTP_200_OK
        assert res_repost.data["id"] in [p["id"] for p in res_bob_my.data["results"]]

        # 2. Alice reposts HER OWN previous post without commentary text (pure share)
        res_self_repost = alice_client.post(
            "/api/v1/posts/repost/",
            {
                "source_post_id": str(alice_post.id),
                "target": "profile",
                "privacy": "followers",
            },
            format="json",
        )
        assert res_self_repost.status_code == status.HTTP_201_CREATED
        assert res_self_repost.data["is_repost"] is True
        assert res_self_repost.data["content_text"] is None
        assert res_self_repost.data["privacy"] == "followers"
        assert res_self_repost.data["source_post_id"] == str(alice_post.id)

        alice_post.refresh_from_db()
        assert alice_post.reposts_count == 2

        # 3. GET /api/v1/posts/<id>/reposts/ returns visible reposts only
        res_list_carol = carol_client.get(f"/api/v1/posts/{alice_post.id}/reposts/")
        assert res_list_carol.status_code == status.HTTP_200_OK
        carol_repost_ids = [p["id"] for p in res_list_carol.data["results"]]
        assert res_repost.data["id"] in carol_repost_ids
        assert res_self_repost.data["id"] not in carol_repost_ids  # followers-only hidden from Carol

        # 4. Also works via POST /api/v1/posts/ with source_post_id
        res_via_posts = bob_client.post(
            "/api/v1/posts/",
            {"source_post_id": str(alice_post.id), "privacy": "private"},
            format="json",
        )
        assert res_via_posts.status_code == status.HTTP_201_CREATED
        assert res_via_posts.data["is_repost"] is True
        assert res_via_posts.data["privacy"] == "private"

        # 5. Deleting a repost decrements source_post.reposts_count
        del_res = bob_client.delete(f"/api/v1/posts/{res_via_posts.data['id']}/")
        assert del_res.status_code == status.HTTP_200_OK
        alice_post.refresh_from_db()
        assert alice_post.reposts_count == 2

        # 6. Deleting original source post marks existing repost as source_post_unavailable=True
        alice_client.delete(f"/api/v1/posts/{alice_post.id}/")
        repost_detail = carol_client.get(f"/api/v1/posts/{res_repost.data['id']}/")
        assert repost_detail.status_code == status.HTTP_200_OK
        assert repost_detail.data["is_repost"] is True
        assert repost_detail.data["source_post"] is None
        assert repost_detail.data["source_post_unavailable"] is True

    def test_gym_auto_context_post_repost_and_privacy(self, repost_env):
        alice = repost_env["alice"]
        bob = repost_env["bob"]
        gym = repost_env["gym"]
        gym_client = repost_env["gym_client"]
        limited_gym_client = repost_env["limited_gym_client"]
        bob_client = repost_env["bob_client"]
        alice_client = repost_env["alice_client"]
        carol_client = repost_env["carol_client"]

        # 1. Limited staff without posts:manage cannot post or repost in gym context
        res_denied = limited_gym_client.post(
            "/api/v1/posts/",
            {"content_text": "Unauthorized gym post"},
            format="json",
        )
        assert res_denied.status_code == status.HTTP_403_FORBIDDEN

        # 2. Gym owner with Gym Bearer token posts without ?gym_id= (auto-detected)
        res_gym_post = gym_client.post(
            "/api/v1/posts/",
            {"content_text": "Gym followers workout schedule", "privacy": "followers"},
            format="json",
        )
        assert res_gym_post.status_code == status.HTTP_201_CREATED
        assert res_gym_post.data["owner_type"] == PostOwnerTypeEnum.GYM
        assert res_gym_post.data["gym_id"] == str(gym.id)
        assert res_gym_post.data["privacy"] == "followers"

        # Bob follows Gym -> sees followers post; Carol does NOT -> 403
        assert bob_client.get(f"/api/v1/posts/{res_gym_post.data['id']}/").status_code == status.HTTP_200_OK
        assert carol_client.get(f"/api/v1/posts/{res_gym_post.data['id']}/").status_code == status.HTTP_403_FORBIDDEN

        # 3. Gym creates a private post -> visible on /posts/my/ in gym context, 403 for members/followers
        res_gym_priv = gym_client.post(
            "/api/v1/posts/",
            {"content_text": "Internal gym maintenance plan", "privacy": "private"},
            format="json",
        )
        assert res_gym_priv.status_code == status.HTTP_201_CREATED
        assert alice_client.get(f"/api/v1/posts/{res_gym_priv.data['id']}/").status_code == status.HTTP_403_FORBIDDEN
        my_gym_feed = gym_client.get("/api/v1/posts/my/")
        assert res_gym_priv.data["id"] in [p["id"] for p in my_gym_feed.data["results"]]

        # 4. Gym reposts Alice's public post onto Gym's profile feed with members_only privacy
        alice_pub = create_post(
            author_user=alice,
            owner_type=PostOwnerTypeEnum.USER,
            content_text="Alice marathon training guide",
            privacy=PostPrivacyEnum.PUBLIC,
        )
        res_gym_repost = gym_client.post(
            f"/api/v1/posts/{alice_pub.id}/repost/",
            {"target": "profile", "privacy": "members_only", "content_text": "Member shoutout!"},
            format="json",
        )
        assert res_gym_repost.status_code == status.HTTP_201_CREATED
        assert res_gym_repost.data["owner_type"] == PostOwnerTypeEnum.GYM
        assert res_gym_repost.data["gym_id"] == str(gym.id)
        assert res_gym_repost.data["privacy"] == "members_only"
        assert res_gym_repost.data["source_post"]["id"] == str(alice_pub.id)

        # Limited staff cannot repost in gym context -> 403
        res_limited_repost = limited_gym_client.post(
            f"/api/v1/posts/{alice_pub.id}/repost/",
            {"target": "profile", "privacy": "public"},
            format="json",
        )
        assert res_limited_repost.status_code == status.HTTP_403_FORBIDDEN

    def test_share_on_story_for_user_and_gym_posts(self, repost_env):
        alice = repost_env["alice"]
        gym = repost_env["gym"]
        alice_client = repost_env["alice_client"]
        bob_client = repost_env["bob_client"]
        carol_client = repost_env["carol_client"]
        gym_client = repost_env["gym_client"]

        img = _make_image("story_share.jpg")
        user_media_post = create_post(
            author_user=alice,
            owner_type=PostOwnerTypeEnum.USER,
            content_text="Sunset run",
            privacy=PostPrivacyEnum.PUBLIC,
            media_files=[img],
        )
        text_only_post = create_post(
            author_user=alice,
            owner_type=PostOwnerTypeEnum.USER,
            content_text="Text-only motivation",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        # 1. Text-only post shared to Story without media fails with 400 (preserves Story media rule)
        res_text_story = bob_client.post(
            f"/api/v1/posts/{text_only_post.id}/repost/",
            {"target": "story", "privacy": "public"},
            format="json",
        )
        assert res_text_story.status_code == status.HTTP_400_BAD_REQUEST

        # 2. Bob shares Alice's media post onto Bob's Story (auto Personal Bearer context)
        res_story = bob_client.post(
            f"/api/v1/posts/{user_media_post.id}/repost/",
            {
                "target": "story",
                "privacy": "followers",
                "caption": "Check out Alice's run!",
                "lifetime_hours": 24,
                "background_color": "#111827",
            },
            format="json",
        )
        assert res_story.status_code == status.HTTP_201_CREATED
        assert res_story.data["target"] == "story"
        assert res_story.data["owner_type"] == StoryOwnerTypeEnum.USER
        assert res_story.data["gym_id"] is None
        assert res_story.data["source_post_id"] == str(user_media_post.id)
        assert res_story.data["source_post"]["author_name"] == "Alice Athlete"
        assert res_story.data["privacy"] == StoryPrivacyEnum.FOLLOWERS
        assert res_story.data["lifetime_hours"] == 24
        assert Story.objects.filter(id=res_story.data["id"]).exists()

        # Public user cannot share to Story with members_only privacy
        res_bad_story_priv = bob_client.post(
            f"/api/v1/posts/{user_media_post.id}/repost/",
            {"target": "story", "privacy": "members_only"},
            format="json",
        )
        assert res_bad_story_priv.status_code == status.HTTP_400_BAD_REQUEST

        # 3. Gym shares Alice's media post onto Gym Story with members_only privacy (auto Gym Bearer context)
        res_gym_story = gym_client.post(
            f"/api/v1/posts/{user_media_post.id}/repost/",
            {
                "target": "story",
                "privacy": "members_only",
                "caption": "Member highlight!",
            },
            format="json",
        )
        assert res_gym_story.status_code == status.HTTP_201_CREATED
        assert res_gym_story.data["target"] == "story"
        assert res_gym_story.data["owner_type"] == StoryOwnerTypeEnum.GYM
        assert res_gym_story.data["gym_id"] == str(gym.id)
        assert res_gym_story.data["privacy"] == StoryPrivacyEnum.MEMBERS_ONLY

        # Member Alice can view gym members_only story; non-member Carol gets 403
        assert alice_client.get(f"/api/v1/stories/{res_gym_story.data['id']}/").status_code == status.HTTP_200_OK
        assert carol_client.get(f"/api/v1/stories/{res_gym_story.data['id']}/").status_code == status.HTTP_403_FORBIDDEN

        # 4. Reposting a repost onto Story inherits the root post's media
        bob_profile_repost = bob_client.post(
            f"/api/v1/posts/{user_media_post.id}/repost/",
            {"target": "profile", "privacy": "public", "content_text": "Reposted!"},
            format="json",
        )
        assert bob_profile_repost.status_code == status.HTTP_201_CREATED
        res_repost_to_story = carol_client.post(
            f"/api/v1/posts/{bob_profile_repost.data['id']}/repost/",
            {"target": "story", "privacy": "public"},
            format="json",
        )
        assert res_repost_to_story.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestRepostSecurityAndPerformance:
    def test_idor_prevention_on_repost_and_nested_source_post(self, repost_env):
        alice = repost_env["alice"]
        bob = repost_env["bob"]
        carol = repost_env["carol"]
        gym = repost_env["gym"]
        gym_owner = repost_env["gym_owner"]
        alice_client = repost_env["alice_client"]
        bob_client = repost_env["bob_client"]
        carol_client = repost_env["carol_client"]

        # 1. Carol cannot repost Alice's private or followers-only post
        alice_priv = create_post(
            author_user=alice,
            owner_type=PostOwnerTypeEnum.USER,
            content_text="Alice secret",
            privacy=PostPrivacyEnum.PRIVATE,
        )
        alice_flw = create_post(
            author_user=alice,
            owner_type=PostOwnerTypeEnum.USER,
            content_text="Alice followers only",
            privacy=PostPrivacyEnum.FOLLOWERS,
        )
        assert carol_client.post(f"/api/v1/posts/{alice_priv.id}/repost/", {"target": "profile"}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert carol_client.post(f"/api/v1/posts/{alice_flw.id}/repost/", {"target": "profile"}, format="json").status_code == status.HTTP_403_FORBIDDEN

        # Alice CAN repost her own previous private post
        res_own_priv = alice_client.post(
            f"/api/v1/posts/{alice_priv.id}/repost/",
            {"target": "profile", "privacy": "private", "content_text": "Throwback"},
            format="json",
        )
        assert res_own_priv.status_code == status.HTTP_201_CREATED

        # 2. Nested source_post masking (anti-IDOR leak):
        # Gym creates a members_only post. Member Alice reposts it publicly on her profile.
        # Stranger Carol views Alice's repost -> Carol MUST NOT see the restricted members_only source_post!
        gym_secret = create_post(
            gym=gym,
            author_user=gym_owner,
            content_text="VIP Locker Combo 9999",
            privacy=PostPrivacyEnum.MEMBERS_ONLY,
        )
        res_alice_share = alice_client.post(
            f"/api/v1/posts/{gym_secret.id}/repost/",
            {"target": "profile", "privacy": "public", "content_text": "Check our gym update"},
            format="json",
        )
        assert res_alice_share.status_code == status.HTTP_201_CREATED
        repost_id = res_alice_share.data["id"]

        res_carol_view = carol_client.get(f"/api/v1/posts/{repost_id}/")
        assert res_carol_view.status_code == status.HTTP_200_OK
        assert res_carol_view.data["content_text"] == "Check our gym update"
        assert res_carol_view.data["source_post"] is None
        assert res_carol_view.data["source_post_unavailable"] is True

        # 3. Blocked user cannot repost
        UserBlockedUser.objects.create(blocker=alice, blocked_user=bob)
        alice_pub = create_post(
            author_user=alice,
            owner_type=PostOwnerTypeEnum.USER,
            content_text="Alice public",
            privacy=PostPrivacyEnum.PUBLIC,
        )
        assert bob_client.post(f"/api/v1/posts/{alice_pub.id}/repost/", {"target": "profile"}, format="json").status_code == status.HTTP_403_FORBIDDEN

        # 4. Gym-blocked user cannot repost gym post
        GymBlockedUser.objects.create(gym=gym, user=carol)
        gym_pub = create_post(
            gym=gym,
            author_user=gym_owner,
            content_text="Gym public",
            privacy=PostPrivacyEnum.PUBLIC,
        )
        assert carol_client.post(f"/api/v1/posts/{gym_pub.id}/repost/", {"target": "profile"}, format="json").status_code == status.HTTP_403_FORBIDDEN

    def test_type_juggling_and_validation_edges(self, repost_env):
        alice = repost_env["alice"]
        alice_client = repost_env["alice_client"]

        post = create_post(
            author_user=alice,
            owner_type=PostOwnerTypeEnum.USER,
            content_text="Valid post",
            privacy=PostPrivacyEnum.PUBLIC,
        )

        # Invalid target
        res1 = alice_client.post(f"/api/v1/posts/{post.id}/repost/", {"target": "email"}, format="json")
        assert res1.status_code == status.HTTP_400_BAD_REQUEST

        # Type juggling target=True
        res2 = alice_client.post(f"/api/v1/posts/{post.id}/repost/", {"target": True}, format="json")
        assert res2.status_code == status.HTTP_400_BAD_REQUEST

        # Mismatched body source_post_id vs URL post_id
        res3 = alice_client.post(
            f"/api/v1/posts/{post.id}/repost/",
            {"source_post_id": str(uuid.uuid4()), "target": "profile"},
            format="json",
        )
        assert res3.status_code == status.HTTP_400_BAD_REQUEST

        # Non-existent post
        res4 = alice_client.post(f"/api/v1/posts/{uuid.uuid4()}/repost/", {"target": "profile"}, format="json")
        assert res4.status_code == status.HTTP_404_NOT_FOUND

    def test_feed_repost_serialization_constant_query_count(self, repost_env):
        alice = repost_env["alice"]
        bob = repost_env["bob"]
        bob_client = repost_env["bob_client"]

        for i in range(10):
            orig = create_post(
                author_user=alice,
                owner_type=PostOwnerTypeEnum.USER,
                content_text=f"Workout #{i}",
                privacy=PostPrivacyEnum.PUBLIC,
            )
            create_post(
                author_user=bob,
                owner_type=PostOwnerTypeEnum.USER,
                source_post_id=orig.id,
                content_text=f"Repost #{i}",
                privacy=PostPrivacyEnum.PUBLIC,
            )

        with CaptureQueriesContext(connection) as ctx:
            res = bob_client.get(f"/api/v1/posts/?user_id={bob.id}")
            assert res.status_code == status.HTTP_200_OK
            assert len(res.data["results"]) == 10

        # Constant O(1) queries (social context + count + paginated posts + prefetches)
        assert len(ctx.captured_queries) <= 16

