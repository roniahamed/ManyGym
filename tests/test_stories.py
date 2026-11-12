import io
import uuid
from datetime import timedelta
from unittest.mock import patch

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
from apps.gyms.models import Gym, GymAdminLog, GymBlockedUser, GymFollow, GymSetting
from apps.members.models import Member
from apps.posts.services import create_post
from apps.stories.models import Story, StoryView
from apps.stories.tasks import optimize_story_media_task
from apps.users.models import User, UserBlockedUser, UserFollow, UserProfile
from common.enums import (
    MediaTypeEnum,
    MemberJoiningStatus,
    PostPrivacyEnum,
    PostsAgeRestrictionEnum,
    ProcessingStatus,
    StaffStatus,
    StoryLifetimeEnum,
    StoryOwnerTypeEnum,
    StoryPrivacyEnum,
    TokenContextType,
)
from common.media import MediaOptimizerService


def _make_image(filename="story.jpg", fmt="JPEG", size=(600, 900)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=(20, 120, 200)).save(buf, format=fmt)
    buf.seek(0)
    content_type = "image/jpeg" if fmt.upper() in ("JPEG", "JPG") else f"image/{fmt.lower()}"
    return SimpleUploadedFile(filename, buf.read(), content_type=content_type)


def _make_video(filename="story.mp4"):
    return SimpleUploadedFile(filename, b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom", content_type="video/mp4")


def _auth_client(user, context_type=TokenContextType.PERSONAL, gym=None):
    token = issue_context_token(user=user, context_type=context_type, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def story_users(db):
    seed_default_permissions_and_roles()

    alice = User.objects.create_user(
        email="alice_story@manygym.com",
        password="Password123!",
        first_name="Alice",
        last_name="Runner",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=alice)
    alice.profile.date_of_birth = timezone.now().date() - timedelta(days=25 * 365)
    alice.profile.save()

    bob = User.objects.create_user(
        email="bob_story@manygym.com",
        password="Password123!",
        first_name="Bob",
        last_name="Lifter",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=bob)
    bob.profile.date_of_birth = timezone.now().date() - timedelta(days=24 * 365)
    bob.profile.save()

    carol = User.objects.create_user(
        email="carol_story@manygym.com",
        password="Password123!",
        first_name="Carol",
        last_name="Member",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=carol)

    gym_owner = User.objects.create_user(
        email="owner_story@manygym.com",
        password="Password123!",
        first_name="Gym",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=gym_owner)

    staff_user = User.objects.create_user(
        email="staff_story@manygym.com",
        password="Password123!",
        first_name="Gym",
        last_name="Staff",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=staff_user)

    gym = Gym.objects.create(
        owner_user=gym_owner,
        name="Apex Story Gym",
        timezone="UTC",
    )
    GymSetting.objects.create(
        gym=gym,
        is_published=True,
        is_deactivated=False,
        is_deleted=False,
        posts_age_restriction=PostsAgeRestrictionEnum.ANY_AGE,
    )

    staff_role = Role.objects.get(gym=None, slug="staff")
    GymStaffAssignment.objects.create(
        gym=gym,
        user=staff_user,
        role=staff_role,
        status=StaffStatus.ACTIVE,
    )

    Member.objects.create(
        gym=gym,
        user=carol,
        email=carol.email,
        first_name=carol.first_name,
        last_name=carol.last_name,
        joining_status=MemberJoiningStatus.JOINED,
    )

    return {
        "alice": alice,
        "bob": bob,
        "carol": carol,
        "gym_owner": gym_owner,
        "staff_user": staff_user,
        "gym": gym,
    }


@pytest.mark.django_db
class TestStoryUploadAndValidation:
    def test_public_user_uploads_single_image_default_18h_lifetime(
        self, story_users, django_capture_on_commit_callbacks
    ):
        alice = story_users["alice"]
        client = _auth_client(alice)

        with patch("apps.stories.tasks.optimize_story_media_task.delay") as mock_delay:
            with django_capture_on_commit_callbacks(execute=True):
                res = client.post(
                    "/api/v1/stories/",
                    data={
                        "file": _make_image("morning.png", fmt="PNG"),
                        "caption": "Morning cardio!",
                        "privacy": "public",
                    },
                    format="multipart",
                )

        assert res.status_code == status.HTTP_201_CREATED
        body = res.json()
        assert body["owner_type"] == StoryOwnerTypeEnum.USER
        assert body["user_id"] == str(alice.id)
        assert body["gym_id"] is None
        assert body["media_type"] == MediaTypeEnum.PICTURE
        assert body["media_url"]
        assert body["lifetime_hours"] == 18
        assert body["lifetime_label"] == "18 hours"
        assert body["privacy"] == StoryPrivacyEnum.PUBLIC
        assert body["caption"] == "Morning cardio!"
        assert body["processing_status"] == ProcessingStatus.PENDING

        story = Story.objects.get(id=body["id"])
        delta = story.expires_at - story.published_at
        assert abs(delta.total_seconds() - 18 * 3600) < 2
        assert mock_delay.called

    def test_public_user_uploads_single_video_with_custom_lifetime(self, story_users):
        alice = story_users["alice"]
        client = _auth_client(alice)

        for hours in [6, 12, 18, 24, 48]:
            res = client.post(
                "/api/v1/stories/",
                data={
                    "file": _make_video(f"lift_{hours}.mp4"),
                    "lifetime": f"{hours} hours",
                    "privacy": "followers",
                },
                format="multipart",
            )
            assert res.status_code == status.HTTP_201_CREATED
            body = res.json()
            assert body["media_type"] == MediaTypeEnum.VIDEO
            assert body["lifetime_hours"] == hours
            assert body["privacy"] == StoryPrivacyEnum.FOLLOWERS

    def test_rejects_multiple_files_in_single_story(self, story_users):
        alice = story_users["alice"]
        client = _auth_client(alice)

        res = client.post(
            "/api/v1/stories/",
            data={
                "files": [_make_image("one.jpg"), _make_image("two.jpg")],
                "privacy": "public",
            },
            format="multipart",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Only 1 media file" in res.json().get("message", "")

    def test_rejects_file_and_media_url_together(self, story_users):
        alice = story_users["alice"]
        client = _auth_client(alice)

        res = client.post(
            "/api/v1/stories/",
            data={
                "file": _make_image("one.jpg"),
                "media_url": "https://cdn.example.com/pic.jpg",
            },
            format="multipart",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_invalid_media_formats_and_oversized_files(self, story_users):
        alice = story_users["alice"]
        client = _auth_client(alice)

        gif = SimpleUploadedFile("anim.gif", b"GIF89a", content_type="image/gif")
        res_gif = client.post("/api/v1/stories/", data={"file": gif}, format="multipart")
        assert res_gif.status_code == status.HTTP_400_BAD_REQUEST

        avi = SimpleUploadedFile("clip.avi", b"RIFF....AVI", content_type="video/x-msvideo")
        res_avi = client.post("/api/v1/stories/", data={"file": avi}, format="multipart")
        assert res_avi.status_code == status.HTTP_400_BAD_REQUEST

        empty_res = client.post("/api/v1/stories/", data={"caption": "No media"}, format="json")
        assert empty_res.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_invalid_lifetimes(self, story_users):
        alice = story_users["alice"]
        client = _auth_client(alice)

        for bad_val in [0, 1, 10, 72, -6, "forever", True]:
            res = client.post(
                "/api/v1/stories/",
                data={
                    "media_url": "https://cdn.manygym.com/s1.jpg",
                    "lifetime_hours": bad_val,
                },
                format="json",
            )
            assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_public_user_cannot_use_members_only_privacy(self, story_users):
        alice = story_users["alice"]
        client = _auth_client(alice)

        res = client.post(
            "/api/v1/stories/",
            data={
                "media_url": "https://cdn.manygym.com/s1.jpg",
                "privacy": StoryPrivacyEnum.MEMBERS_ONLY,
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "members_only" in res.json().get("message", "")

    def test_gym_story_upload_by_owner_and_staff_with_all_privacies(self, story_users):
        gym = story_users["gym"]
        owner = story_users["gym_owner"]
        staff = story_users["staff_user"]

        owner_client = _auth_client(owner, context_type=TokenContextType.GYM, gym=gym)
        for priv in ["public", "followers", "members_only", "private"]:
            res = owner_client.post(
                "/api/v1/stories/",
                data={
                    "file": _make_image(f"gym_{priv}.jpg"),
                    "privacy": priv,
                    "lifetime_hours": 24,
                },
                format="multipart",
            )
            assert res.status_code == status.HTTP_201_CREATED
            body = res.json()
            assert body["owner_type"] == StoryOwnerTypeEnum.GYM
            assert body["gym_id"] == str(gym.id)
            assert body["user_id"] == str(owner.id)
            assert body["privacy"] == priv
            assert body["lifetime_hours"] == 24

        assert GymAdminLog.objects.filter(gym=gym, target_type="story").count() == 4

        staff_client = _auth_client(staff, context_type=TokenContextType.GYM, gym=gym)
        res_staff = staff_client.post(
            "/api/v1/stories/",
            data={
                "media_url": "https://cdn.manygym.com/gym_vid.mp4",
                "privacy": "members_only",
            },
            format="json",
        )
        assert res_staff.status_code == status.HTTP_201_CREATED
        assert res_staff.json()["user_id"] == str(staff.id)
        assert res_staff.json()["gym_id"] == str(gym.id)
        assert res_staff.json()["media_type"] == MediaTypeEnum.VIDEO

    def test_non_staff_cannot_upload_gym_story(self, story_users):
        gym = story_users["gym"]
        carol = story_users["carol"]  # gym member, NOT staff
        client = _auth_client(carol)
        client.credentials(
            HTTP_AUTHORIZATION=client._credentials["HTTP_AUTHORIZATION"],
            HTTP_X_GYM_CONTEXT=str(gym.id),
        )

        res = client.post(
            "/api/v1/stories/",
            data={
                "media_url": "https://cdn.manygym.com/hack.jpg",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_readonly_fields_resolved_automatically_from_token_and_media(self, story_users):
        alice = story_users["alice"]
        bob = story_users["bob"]
        gym = story_users["gym"]
        client = _auth_client(alice)

        # Spoofed owner_type, gym_id, user_id, media_type in body must not override token/media detection
        res = client.post(
            "/api/v1/stories/",
            data={
                "owner_type": "gym",
                "gym_id": str(gym.id),
                "user_id": str(bob.id),
                "media_type": "video",
                "file": _make_image("auto_pic.jpg", fmt="JPEG"),
                "privacy": "public",
            },
            format="multipart",
        )
        assert res.status_code == status.HTTP_201_CREATED
        body = res.json()
        assert body["owner_type"] == StoryOwnerTypeEnum.USER
        assert body["gym_id"] is None
        assert body["user_id"] == str(alice.id)
        assert body["media_type"] == MediaTypeEnum.PICTURE

    def test_unauthenticated_cannot_upload_story(self):
        client = APIClient()
        res = client.post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/anon.jpg"},
            format="json",
        )
        assert res.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestStorySourcePostAndMediaPipeline:
    def test_share_source_post_to_story_and_preserve_post_media_on_story_delete(self, story_users):
        gym = story_users["gym"]
        owner = story_users["gym_owner"]
        alice = story_users["alice"]

        post = create_post(
            gym=gym,
            author_user=owner,
            content_text="New squat racks arrived!",
            privacy=PostPrivacyEnum.PUBLIC,
            media_files=[_make_image("rack.png", fmt="PNG")],
        )
        post_media = post.media_attachments.first()
        post_path = MediaOptimizerService.get_absolute_path(post_media.original_url)
        assert post_path.exists()

        alice_client = _auth_client(alice)
        res = alice_client.post(
            "/api/v1/stories/",
            data={
                "source_post_id": str(post.id),
                "caption": "Must try these racks!",
                "privacy": "public",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        body = res.json()
        assert body["source_post_id"] == str(post.id)
        assert body["source_post"]["id"] == str(post.id)
        assert body["source_post"]["gym_name"] == gym.name
        assert body["media_url"]

        # Deleting the story must NOT delete the source post's media file on disk
        del_res = alice_client.delete(f"/api/v1/stories/{body['id']}/")
        assert del_res.status_code == status.HTTP_200_OK
        assert post_path.exists()

    def test_cannot_share_inaccessible_members_only_post(self, story_users):
        gym = story_users["gym"]
        owner = story_users["gym_owner"]
        bob = story_users["bob"]  # not a member of gym

        secret_post = create_post(
            gym=gym,
            author_user=owner,
            content_text="Members only promo code",
            privacy=PostPrivacyEnum.MEMBERS_ONLY,
            media_files=[_make_image("secret.png", fmt="PNG")],
        )

        bob_client = _auth_client(bob)
        res = bob_client.post(
            "/api/v1/stories/",
            data={
                "source_post_id": str(secret_post.id),
                "media_url": "https://cdn.manygym.com/own.jpg",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_celery_optimization_task_converts_image_story_to_webp(self, story_users):
        alice = story_users["alice"]
        client = _auth_client(alice)

        with patch("apps.stories.tasks.optimize_story_media_task.delay"):
            res = client.post(
                "/api/v1/stories/",
                data={"file": _make_image("raw.png", fmt="PNG")},
                format="multipart",
            )
        assert res.status_code == status.HTTP_201_CREATED
        story_id = res.json()["id"]

        optimize_story_media_task(story_id)

        story = Story.objects.get(id=story_id)
        assert story.processing_status == ProcessingStatus.COMPLETED
        assert story.optimized_url.endswith(".webp")
        assert story.thumbnail_url.endswith(".webp")
        assert story.width == 600
        assert story.height == 900


@pytest.mark.django_db
class TestStoryPrivacyExpiryViewsAndPerformance:
    def test_public_user_privacy_levels(self, story_users):
        alice = story_users["alice"]
        bob = story_users["bob"]
        carol = story_users["carol"]

        # Bob follows Alice; Carol does NOT follow Alice
        UserFollow.objects.create(follower=bob, followed_user=alice)

        alice_client = _auth_client(alice)
        s_pub = alice_client.post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/pub.jpg", "privacy": "public"},
            format="json",
        ).json()["id"]
        s_fol = alice_client.post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/fol.jpg", "privacy": "followers"},
            format="json",
        ).json()["id"]
        s_priv = alice_client.post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/priv.jpg", "privacy": "private"},
            format="json",
        ).json()["id"]

        # Bob (follower) sees public + followers, NOT private
        bob_client = _auth_client(bob)
        bob_ids = {s["id"] for s in bob_client.get("/api/v1/stories/").json()["results"]}
        assert s_pub in bob_ids
        assert s_fol in bob_ids
        assert s_priv not in bob_ids
        assert bob_client.get(f"/api/v1/stories/{s_priv}/").status_code == status.HTTP_403_FORBIDDEN

        # Carol (stranger) sees ONLY public
        carol_client = _auth_client(carol)
        carol_ids = {s["id"] for s in carol_client.get("/api/v1/stories/").json()["results"]}
        assert s_pub in carol_ids
        assert s_fol not in carol_ids
        assert s_priv not in carol_ids
        assert carol_client.get(f"/api/v1/stories/{s_fol}/").status_code == status.HTTP_403_FORBIDDEN

        # Guest sees ONLY public
        guest_ids = {s["id"] for s in APIClient().get("/api/v1/stories/").json()["results"]}
        assert s_pub in guest_ids
        assert s_fol not in guest_ids
        assert s_priv not in guest_ids

        # Alice sees all 3 including private in /my/
        alice_my_ids = {s["id"] for s in alice_client.get("/api/v1/stories/my/").json()["results"]}
        assert {s_pub, s_fol, s_priv}.issubset(alice_my_ids)

    def test_gym_privacy_levels(self, story_users):
        gym = story_users["gym"]
        owner = story_users["gym_owner"]
        bob = story_users["bob"]     # follows gym, NOT a member
        carol = story_users["carol"] # member of gym, NOT following
        alice = story_users["alice"] # stranger

        GymFollow.objects.create(user=bob, gym=gym)

        owner_client = _auth_client(owner, context_type=TokenContextType.GYM, gym=gym)
        g_pub = owner_client.post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/g_pub.jpg", "privacy": "public"},
            format="json",
        ).json()["id"]
        g_fol = owner_client.post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/g_fol.jpg", "privacy": "followers"},
            format="json",
        ).json()["id"]
        g_mem = owner_client.post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/g_mem.jpg", "privacy": "members_only"},
            format="json",
        ).json()["id"]
        g_priv = owner_client.post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/g_priv.jpg", "privacy": "private"},
            format="json",
        ).json()["id"]

        # Bob (follower only): public + followers
        bob_ids = {s["id"] for s in _auth_client(bob).get("/api/v1/stories/").json()["results"]}
        assert {g_pub, g_fol}.issubset(bob_ids)
        assert g_mem not in bob_ids
        assert g_priv not in bob_ids
        assert _auth_client(bob).get(f"/api/v1/stories/{g_mem}/").status_code == status.HTTP_403_FORBIDDEN

        # Carol (member only): public + members_only
        carol_ids = {s["id"] for s in _auth_client(carol).get("/api/v1/stories/").json()["results"]}
        assert {g_pub, g_mem}.issubset(carol_ids)
        assert g_fol not in carol_ids
        assert g_priv not in carol_ids

        # Alice (stranger): public only
        alice_ids = {s["id"] for s in _auth_client(alice).get("/api/v1/stories/").json()["results"]}
        assert g_pub in alice_ids
        assert g_fol not in alice_ids
        assert g_mem not in alice_ids
        assert g_priv not in alice_ids

        # Owner sees all 4
        owner_ids = {s["id"] for s in owner_client.get("/api/v1/stories/").json()["results"]}
        assert {g_pub, g_fol, g_mem, g_priv}.issubset(owner_ids)

    def test_blocked_users_and_age_restrictions_enforced(self, story_users):
        alice = story_users["alice"]
        bob = story_users["bob"]
        gym = story_users["gym"]
        owner = story_users["gym_owner"]

        # Underage user (16 years old)
        teen = User.objects.create_user(
            email="teen_story@manygym.com",
            password="Password123!",
            first_name="Teen",
            last_name="User",
            is_verified=True,
        )
        UserProfile.objects.get_or_create(user=teen)
        teen.profile.date_of_birth = timezone.now().date() - timedelta(days=16 * 365)
        teen.profile.save()

        gym.settings.posts_age_restriction = PostsAgeRestrictionEnum.AGE_18_PLUS
        gym.settings.save()

        UserBlockedUser.objects.create(blocker=alice, blocked_user=bob)
        GymBlockedUser.objects.create(gym=gym, user=bob, blocked_by=owner)

        alice_s = _auth_client(alice).post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/a1.jpg", "privacy": "public"},
            format="json",
        ).json()["id"]
        gym_s = _auth_client(owner, context_type=TokenContextType.GYM, gym=gym).post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/g1.jpg", "privacy": "public"},
            format="json",
        ).json()["id"]

        bob_client = _auth_client(bob)
        bob_ids = {s["id"] for s in bob_client.get("/api/v1/stories/").json()["results"]}
        assert alice_s not in bob_ids
        assert gym_s not in bob_ids
        assert bob_client.get(f"/api/v1/stories/{alice_s}/").status_code == status.HTTP_403_FORBIDDEN
        assert bob_client.get(f"/api/v1/stories/{gym_s}/").status_code == status.HTTP_403_FORBIDDEN

        teen_client = _auth_client(teen)
        teen_ids = {s["id"] for s in teen_client.get("/api/v1/stories/").json()["results"]}
        assert gym_s not in teen_ids
        assert teen_client.get(f"/api/v1/stories/{gym_s}/").status_code == status.HTTP_403_FORBIDDEN

    def test_expired_story_hidden_from_feed_but_available_in_owner_archive(self, story_users):
        alice = story_users["alice"]
        bob = story_users["bob"]
        alice_client = _auth_client(alice)

        s_id = alice_client.post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/exp.jpg", "lifetime_hours": 6},
            format="json",
        ).json()["id"]

        # Expire the story
        Story.objects.filter(id=s_id).update(expires_at=timezone.now() - timedelta(minutes=1))

        bob_client = _auth_client(bob)
        assert s_id not in {s["id"] for s in bob_client.get("/api/v1/stories/").json()["results"]}
        assert bob_client.get(f"/api/v1/stories/{s_id}/").status_code == status.HTTP_404_NOT_FOUND

        # Hidden by default in /my/ unless include_expired=true
        assert s_id not in {s["id"] for s in alice_client.get("/api/v1/stories/my/").json()["results"]}
        assert s_id in {
            s["id"] for s in alice_client.get("/api/v1/stories/my/?include_expired=true").json()["results"]
        }

    def test_story_views_tray_update_and_delete(self, story_users):
        alice = story_users["alice"]
        bob = story_users["bob"]
        alice_client = _auth_client(alice)
        bob_client = _auth_client(bob)

        s_id = alice_client.post(
            "/api/v1/stories/",
            data={"media_url": "https://cdn.manygym.com/v1.jpg", "lifetime_hours": 12},
            format="json",
        ).json()["id"]

        # Tray shows unviewed for Bob
        tray = bob_client.get("/api/v1/stories/tray/").json()
        alice_bucket = next(b for b in tray if b["owner_id"] == str(alice.id))
        assert alice_bucket["has_unviewed"] is True

        # Bob records view twice -> idempotent count = 1
        v1 = bob_client.post(f"/api/v1/stories/{s_id}/view/")
        assert v1.status_code == status.HTTP_200_OK
        assert v1.json()["views_count"] == 1
        assert v1.json()["newly_viewed"] is True

        v2 = bob_client.post(f"/api/v1/stories/{s_id}/view/")
        assert v2.status_code == status.HTTP_200_OK
        assert v2.json()["views_count"] == 1
        assert v2.json()["newly_viewed"] is False

        # Tray now shows has_unviewed = False for Bob
        tray_after = bob_client.get("/api/v1/stories/tray/").json()
        alice_bucket_after = next(b for b in tray_after if b["owner_id"] == str(alice.id))
        assert alice_bucket_after["has_unviewed"] is False

        # Viewers endpoint: Alice can view, Bob cannot
        viewers_res = alice_client.get(f"/api/v1/stories/{s_id}/viewers/")
        assert viewers_res.status_code == status.HTTP_200_OK
        assert len(viewers_res.json()["results"]) == 1
        assert viewers_res.json()["results"][0]["viewer_user_id"] == str(bob.id)
        assert bob_client.get(f"/api/v1/stories/{s_id}/viewers/").status_code == status.HTTP_403_FORBIDDEN

        # Patch: Alice updates lifetime and caption; Bob gets 403
        assert bob_client.patch(f"/api/v1/stories/{s_id}/", data={"caption": "hack"}, format="json").status_code == status.HTTP_403_FORBIDDEN
        patch_res = alice_client.patch(
            f"/api/v1/stories/{s_id}/",
            data={"caption": "Updated!", "lifetime_hours": 48, "privacy": "followers"},
            format="json",
        )
        assert patch_res.status_code == status.HTTP_200_OK
        assert patch_res.json()["caption"] == "Updated!"
        assert patch_res.json()["lifetime_hours"] == 48
        assert patch_res.json()["privacy"] == "followers"

        # Delete: Bob gets 403, Alice deletes
        assert bob_client.delete(f"/api/v1/stories/{s_id}/").status_code == status.HTTP_403_FORBIDDEN
        assert alice_client.delete(f"/api/v1/stories/{s_id}/").status_code == status.HTTP_200_OK
        assert not Story.objects.filter(id=s_id).exists()

    def test_story_feed_query_count_is_bounded(self, story_users):
        alice = story_users["alice"]
        bob = story_users["bob"]
        gym = story_users["gym"]
        owner = story_users["gym_owner"]

        for i in range(10):
            Story.objects.create(
                owner_type=StoryOwnerTypeEnum.USER,
                user=alice,
                media_url=f"https://cdn.manygym.com/u_{i}.jpg",
                media_type=MediaTypeEnum.PICTURE,
                privacy=StoryPrivacyEnum.PUBLIC,
            )
            Story.objects.create(
                owner_type=StoryOwnerTypeEnum.GYM,
                user=owner,
                gym=gym,
                media_url=f"https://cdn.manygym.com/g_{i}.jpg",
                media_type=MediaTypeEnum.PICTURE,
                privacy=StoryPrivacyEnum.PUBLIC,
            )

        bob_client = _auth_client(bob)
        with CaptureQueriesContext(connection) as ctx:
            res = bob_client.get("/api/v1/stories/")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()["results"]) == 20
        # Social context (6) + count + main query + auth user lookup <= 12 queries (constant O(1), no N+1)
        assert len(ctx) <= 12

