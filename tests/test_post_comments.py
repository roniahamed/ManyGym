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
from apps.posts.comment_selectors import _fetch_bounded_replies_for_parents
from apps.posts.models import GymPost, PostComment
from apps.posts.services import create_comment, create_post
from apps.posts.tasks import optimize_comment_media_task
from apps.users.models import User, UserBlockedUser, UserFollow, UserProfile
from common.enums import (
    CommentMediaTypeEnum,
    MemberJoiningStatus,
    PostOwnerTypeEnum,
    PostPrivacyEnum,
    PostsAgeRestrictionEnum,
    ProcessingStatus,
    StaffStatus,
    TokenContextType,
)


def _make_image(filename="comment_photo.jpg", fmt="JPEG", size=(320, 240)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=(60, 130, 200)).save(buf, format=fmt)
    buf.seek(0)
    return SimpleUploadedFile(filename, buf.read(), content_type="image/jpeg")


def _make_gif(filename="reaction.gif", size=(120, 90)):
    buf = io.BytesIO()
    frame1 = Image.new("P", size, color=1)
    frame2 = Image.new("P", size, color=2)
    frame1.save(
        buf,
        format="GIF",
        save_all=True,
        append_images=[frame2],
        duration=100,
        loop=0,
    )
    buf.seek(0)
    return SimpleUploadedFile(filename, buf.read(), content_type="image/gif")


def _make_fake_video(filename="lift.mp4"):
    return SimpleUploadedFile(filename, b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom", content_type="video/mp4")


def _auth_client(user, context_type=TokenContextType.PERSONAL, gym=None):
    token = issue_context_token(user=user, context_type=context_type, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def comment_env(db):
    seed_default_permissions_and_roles()

    alice = User.objects.create_user(
        email="alice_comm@manygym.com",
        password="Password123!",
        first_name="Alice",
        last_name="Lifter",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=alice)
    alice.profile.date_of_birth = timezone.now().date() - timedelta(days=25 * 365)
    alice.profile.save()

    bob = User.objects.create_user(
        email="bob_comm@manygym.com",
        password="Password123!",
        first_name="Bob",
        last_name="Coach",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=bob)
    bob.profile.date_of_birth = timezone.now().date() - timedelta(days=24 * 365)
    bob.profile.save()

    carol = User.objects.create_user(
        email="carol_comm@manygym.com",
        password="Password123!",
        first_name="Carol",
        last_name="Runner",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=carol)
    carol.profile.date_of_birth = timezone.now().date() - timedelta(days=27 * 365)
    carol.profile.save()

    minor = User.objects.create_user(
        email="minor_comm@manygym.com",
        password="Password123!",
        first_name="Teen",
        last_name="Member",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=minor)
    minor.profile.date_of_birth = timezone.now().date() - timedelta(days=16 * 365)
    minor.profile.save()

    gym_owner = User.objects.create_user(
        email="owner_comm@manygym.com",
        password="Password123!",
        first_name="Gym",
        last_name="Boss",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=gym_owner)

    limited_staff = User.objects.create_user(
        email="limited_comm@manygym.com",
        password="Password123!",
        first_name="Desk",
        last_name="Staff",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=limited_staff)

    gym = Gym.objects.create(
        owner_user=gym_owner,
        name="Apex Barbell Club",
        timezone="UTC",
    )
    GymSetting.objects.create(
        gym=gym,
        is_published=True,
        is_deactivated=False,
        is_deleted=False,
        posts_age_restriction=PostsAgeRestrictionEnum.ANY_AGE,
    )

    no_posts_role = Role.objects.create(
        gym=gym,
        slug="front_desk_comments_test",
        name="Front Desk",
        is_custom=True,
    )
    GymStaffAssignment.objects.create(
        gym=gym,
        user=limited_staff,
        role=no_posts_role,
        status=StaffStatus.ACTIVE,
    )

    UserFollow.objects.create(follower=bob, followed_user=alice)
    GymFollow.objects.create(user=bob, gym=gym)
    Member.objects.create(
        gym=gym,
        user=bob,
        first_name=bob.first_name,
        last_name=bob.last_name,
        email=bob.email,
        joining_status=MemberJoiningStatus.JOINED,
    )

    alice_public_post = create_post(
        author_user=alice,
        owner_type=PostOwnerTypeEnum.USER,
        content_text="Alice hit a PR today!",
        privacy=PostPrivacyEnum.PUBLIC,
    )
    alice_followers_post = create_post(
        author_user=alice,
        owner_type=PostOwnerTypeEnum.USER,
        content_text="Followers-only training log.",
        privacy=PostPrivacyEnum.FOLLOWERS,
    )
    gym_public_post = create_post(
        gym=gym,
        author_user=gym_owner,
        owner_type=PostOwnerTypeEnum.GYM,
        content_text="Apex open gym Saturday!",
        privacy=PostPrivacyEnum.PUBLIC,
    )
    gym_members_post = create_post(
        gym=gym,
        author_user=gym_owner,
        owner_type=PostOwnerTypeEnum.GYM,
        content_text="Members only seminar.",
        privacy=PostPrivacyEnum.MEMBERS_ONLY,
    )

    return {
        "alice": alice,
        "bob": bob,
        "carol": carol,
        "minor": minor,
        "gym_owner": gym_owner,
        "limited_staff": limited_staff,
        "gym": gym,
        "alice_public_post": alice_public_post,
        "alice_followers_post": alice_followers_post,
        "gym_public_post": gym_public_post,
        "gym_members_post": gym_members_post,
    }


@pytest.mark.django_db
class TestPostCommentsMediaAndGymContext:
    def test_create_comments_with_text_photo_video_gif_and_optimize_task(self, comment_env):
        bob = comment_env["bob"]
        post = comment_env["alice_public_post"]
        client = _auth_client(bob)

        # 1. Text-only comment via /posts/<post_id>/comments/
        resp_text = client.post(
            f"/api/v1/posts/{post.id}/comments/",
            {"comment_text": "Huge lift!"},
            format="json",
        )
        assert resp_text.status_code == status.HTTP_201_CREATED
        d_text = resp_text.json()
        assert d_text["user_id"] == str(bob.id)
        assert d_text["source_post_id"] == str(post.id)
        assert d_text["source_comment_id"] is None
        assert d_text["comment_text"] == "Huge lift!"
        assert d_text["depth"] == 0
        assert d_text["media_type"] is None

        # 2. Photo-only comment via multipart upload + Celery optimization task
        resp_photo = client.post(
            f"/api/v1/posts/{post.id}/comments/",
            {"comment_photo": _make_image("pr.jpg")},
            format="multipart",
        )
        assert resp_photo.status_code == status.HTTP_201_CREATED
        d_photo = resp_photo.json()
        assert d_photo["media_type"] == CommentMediaTypeEnum.PHOTO
        assert d_photo["comment_photo"] is not None
        assert d_photo["comment_text"] is None
        assert d_photo["processing_status"] == ProcessingStatus.PENDING

        optimize_comment_media_task(d_photo["id"])
        photo_comment = PostComment.objects.get(id=d_photo["id"])
        assert photo_comment.processing_status == ProcessingStatus.COMPLETED
        assert photo_comment.optimized_url.endswith(".webp")
        assert photo_comment.thumbnail_url.endswith(".webp")
        assert photo_comment.comment_photo == photo_comment.optimized_url

        # 3. Video comment via /api/v1/comments/ (body source_post_id)
        resp_video = client.post(
            "/api/v1/comments/",
            {
                "source_post_id": str(post.id),
                "comment_text": "Form check video",
                "comment_video": _make_fake_video("form.mp4"),
            },
            format="multipart",
        )
        assert resp_video.status_code == status.HTTP_201_CREATED
        d_video = resp_video.json()
        assert d_video["media_type"] == CommentMediaTypeEnum.VIDEO
        assert d_video["comment_video"] is not None
        assert d_video["comment_text"] == "Form check video"

        # 4. GIF file upload preserves .gif animation
        resp_gif_file = client.post(
            f"/api/v1/posts/{post.id}/comments/",
            {"comment_gif": _make_gif("clap.gif")},
            format="multipart",
        )
        assert resp_gif_file.status_code == status.HTTP_201_CREATED
        d_gif_file = resp_gif_file.json()
        assert d_gif_file["media_type"] == CommentMediaTypeEnum.GIF
        assert d_gif_file["comment_gif"].endswith(".gif")
        assert d_gif_file["width"] == 120
        assert d_gif_file["height"] == 90
        assert d_gif_file["processing_status"] == ProcessingStatus.COMPLETED

        # 5. External GIF URL (e.g. Giphy)
        gif_url = "https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif"
        resp_gif_url = client.post(
            f"/api/v1/posts/{post.id}/comments/",
            {"comment_gif": gif_url},
            format="json",
        )
        assert resp_gif_url.status_code == status.HTTP_201_CREATED
        assert resp_gif_url.json()["comment_gif"] == gif_url
        assert resp_gif_url.json()["media_type"] == CommentMediaTypeEnum.GIF

        post.refresh_from_db()
        assert post.comments_count == 5

        # Verify Post detail exposes updated comments_count
        post_resp = client.get(f"/api/v1/posts/{post.id}/")
        assert post_resp.status_code == status.HTTP_200_OK
        assert post_resp.json()["comments_count"] == 5

    def test_gym_context_comment_requires_posts_manage_permission(self, comment_env):
        gym = comment_env["gym"]
        gym_owner = comment_env["gym_owner"]
        limited_staff = comment_env["limited_staff"]
        post = comment_env["alice_public_post"]

        limited_client = _auth_client(limited_staff, context_type=TokenContextType.GYM, gym=gym)
        denied = limited_client.post(
            f"/api/v1/posts/{post.id}/comments/",
            {"comment_text": "Unauthorized gym comment"},
            format="json",
        )
        assert denied.status_code == status.HTTP_403_FORBIDDEN

        owner_client = _auth_client(gym_owner, context_type=TokenContextType.GYM, gym=gym)
        allowed = owner_client.post(
            f"/api/v1/posts/{post.id}/comments/",
            {"comment_text": "Great job from Apex!"},
            format="json",
        )
        assert allowed.status_code == status.HTTP_201_CREATED
        body = allowed.json()
        assert body["owner_type"] == PostOwnerTypeEnum.GYM
        assert body["gym_id"] == str(gym.id)
        assert body["gym_name"] == gym.name
        assert body["user_id"] == str(gym_owner.id)


@pytest.mark.django_db
class TestNestedCommentsRepliesAndPagination:
    def test_nested_replies_tree_depth_and_pagination(self, comment_env):
        alice = comment_env["alice"]
        bob = comment_env["bob"]
        carol = comment_env["carol"]
        post = comment_env["alice_public_post"]

        alice_client = _auth_client(alice)
        bob_client = _auth_client(bob)
        carol_client = _auth_client(carol)

        # Create 3 top-level comments
        c1 = alice_client.post(
            f"/api/v1/posts/{post.id}/comments/",
            {"comment_text": "Top level 1"},
            format="json",
        ).json()
        c2 = bob_client.post(
            f"/api/v1/posts/{post.id}/comments/",
            {"comment_text": "Top level 2"},
            format="json",
        ).json()
        c3 = carol_client.post(
            f"/api/v1/posts/{post.id}/comments/",
            {"comment_text": "Top level 3"},
            format="json",
        ).json()

        # Create 3 direct replies on c1 (depth 1) via different endpoints
        r1 = bob_client.post(
            f"/api/v1/posts/{post.id}/comments/",
            {"source_comment_id": c1["id"], "comment_text": "Reply 1 to c1"},
            format="json",
        ).json()
        r2 = carol_client.post(
            f"/api/v1/comments/{c1['id']}/replies/",
            {"comment_text": "Reply 2 to c1"},
            format="json",
        ).json()
        r3 = alice_client.post(
            f"/api/v1/posts/{post.id}/comments/{c1['id']}/replies/",
            {"comment_text": "Reply 3 to c1"},
            format="json",
        ).json()

        assert r1["depth"] == 1
        assert r1["root_comment_id"] == c1["id"]
        assert r1["source_comment_id"] == c1["id"]
        assert r1["reply_to_user_id"] == str(alice.id)
        assert r1["reply_to_user_name"] == "Alice Lifter"

        # Nested reply on r1 (depth 2) and reply on that (depth 3)
        r1_1 = alice_client.post(
            f"/api/v1/comments/{r1['id']}/replies/",
            {"comment_text": "Nested depth 2"},
            format="json",
        ).json()
        r1_1_1 = bob_client.post(
            f"/api/v1/comments/{r1_1['id']}/replies/",
            {"comment_text": "Nested depth 3", "comment_gif": "https://media.giphy.com/media/test/giphy.gif"},
            format="json",
        ).json()

        assert r1_1["depth"] == 2
        assert r1_1["root_comment_id"] == c1["id"]
        assert r1_1["reply_to_user_id"] == str(bob.id)
        assert r1_1_1["depth"] == 3
        assert r1_1_1["root_comment_id"] == c1["id"]
        assert r1_1_1["reply_to_user_id"] == str(alice.id)

        post.refresh_from_db()
        assert post.comments_count == 8  # 3 top + 3 depth1 + 1 depth2 + 1 depth3

        c1_db = PostComment.objects.get(id=c1["id"])
        assert c1_db.replies_count == 3
        assert c1_db.total_replies_count == 5

        # 1. Paginated top-level comments (page_size=2, replies_limit=2, reply_depth=3)
        page1 = carol_client.get(
            f"/api/v1/posts/{post.id}/comments/?page=1&page_size=2&sort=oldest&replies_limit=2&reply_depth=3"
        )
        assert page1.status_code == status.HTTP_200_OK
        p1_data = page1.json()
        assert p1_data["count"] == 3
        assert p1_data["total_pages"] == 2
        assert p1_data["current_page"] == 1
        assert len(p1_data["results"]) == 2
        assert p1_data["results"][0]["id"] == c1["id"]
        assert p1_data["results"][0]["replies_count"] == 3
        assert p1_data["results"][0]["total_replies_count"] == 5
        assert p1_data["results"][0]["has_more_replies"] is True
        assert len(p1_data["results"][0]["replies"]) == 2
        # Verify nested depth 2 & 3 loaded under r1!
        nested_r1 = p1_data["results"][0]["replies"][0]
        assert nested_r1["id"] == r1["id"]
        assert len(nested_r1["replies"]) == 1
        assert nested_r1["replies"][0]["id"] == r1_1["id"]
        assert len(nested_r1["replies"][0]["replies"]) == 1
        assert nested_r1["replies"][0]["replies"][0]["id"] == r1_1_1["id"]

        page2 = carol_client.get(
            f"/api/v1/posts/{post.id}/comments/?page=2&page_size=2&sort=oldest"
        )
        assert page2.status_code == status.HTTP_200_OK
        assert len(page2.json()["results"]) == 1
        assert page2.json()["results"][0]["id"] == c3["id"]

        # 2. Paginated replies endpoint at any depth
        rep_p1 = carol_client.get(f"/api/v1/comments/{c1['id']}/replies/?page=1&page_size=2")
        assert rep_p1.status_code == status.HTTP_200_OK
        assert rep_p1.json()["count"] == 3
        assert [r["id"] for r in rep_p1.json()["results"]] == [r1["id"], r2["id"]]

        rep_p2 = carol_client.get(f"/api/v1/comments/{c1['id']}/replies/?page=2&page_size=2")
        assert rep_p2.status_code == status.HTTP_200_OK
        assert [r["id"] for r in rep_p2.json()["results"]] == [r3["id"]]

        # 3. Media type filtering & most_replied sort
        gif_filtered = carol_client.get(f"/api/v1/comments/{r1_1['id']}/replies/?media_type=gif")
        assert gif_filtered.status_code == status.HTTP_200_OK
        assert gif_filtered.json()["count"] == 1
        assert gif_filtered.json()["results"][0]["id"] == r1_1_1["id"]

        most_replied = carol_client.get(f"/api/v1/posts/{post.id}/comments/?sort=most_replied")
        assert most_replied.status_code == status.HTTP_200_OK
        assert most_replied.json()["results"][0]["id"] == c1["id"]

    def test_constant_query_count_for_nested_comments_and_window_path(self, comment_env):
        alice = comment_env["alice"]
        bob = comment_env["bob"]
        post = comment_env["alice_public_post"]

        top_comments = []
        for i in range(15):
            top = create_comment(
                actor_user=alice,
                source_post_id=post.id,
                comment_text=f"Parent {i}",
            )
            top_comments.append(top)
            for j in range(3):
                child = create_comment(
                    actor_user=bob,
                    source_post_id=post.id,
                    source_comment_id=top.id,
                    comment_text=f"Child {i}-{j}",
                )
                create_comment(
                    actor_user=alice,
                    source_post_id=post.id,
                    source_comment_id=child.id,
                    comment_text=f"Grandchild {i}-{j}",
                )

        client = _auth_client(bob)

        with CaptureQueriesContext(connection) as ctx_small:
            r_small = client.get(f"/api/v1/posts/{post.id}/comments/?page=1&page_size=5&reply_depth=2&replies_limit=2")
        assert r_small.status_code == status.HTTP_200_OK

        with CaptureQueriesContext(connection) as ctx_large:
            r_large = client.get(f"/api/v1/posts/{post.id}/comments/?page=1&page_size=15&reply_depth=2&replies_limit=2")
        assert r_large.status_code == status.HTTP_200_OK
        assert len(r_large.json()["results"]) == 15

        # Query count must stay constant regardless of page size (no N+1 per comment or per reply)
        assert len(ctx_large.captured_queries) == len(ctx_small.captured_queries)
        assert len(ctx_large.captured_queries) <= 16

        # Explicitly exercise the PostgreSQL Window(RowNumber()) bounded query path (total_possible > 200)
        top0 = top_comments[0]
        PostComment.objects.filter(id=top0.id).update(replies_count=250)
        top0.refresh_from_db()
        bounded = _fetch_bounded_replies_for_parents(
            parent_nodes=[top0],
            per_parent_limit=2,
            requesting_user=bob,
        )
        assert len(bounded) == 3  # per_parent_limit + 1


@pytest.mark.django_db
class TestCommentUpdateDeleteAndCascade:
    def test_edit_comment_preserves_media_and_enforces_ownership(self, comment_env):
        alice = comment_env["alice"]
        bob = comment_env["bob"]
        post = comment_env["alice_public_post"]

        bob_client = _auth_client(bob)
        alice_client = _auth_client(alice)

        created = bob_client.post(
            f"/api/v1/posts/{post.id}/comments/",
            {
                "comment_text": "Initial text",
                "comment_photo": _make_image("initial.jpg"),
            },
            format="multipart",
        ).json()

        # Post owner (Alice) cannot edit Bob's comment
        forbidden_edit = alice_client.patch(
            f"/api/v1/comments/{created['id']}/",
            {"comment_text": "Tampered"},
            format="json",
        )
        assert forbidden_edit.status_code == status.HTTP_403_FORBIDDEN

        # Partial edit of comment_text preserves existing comment_photo
        edited = bob_client.patch(
            f"/api/v1/comments/{created['id']}/",
            {"comment_text": "Updated text"},
            format="json",
        )
        assert edited.status_code == status.HTTP_200_OK
        ed = edited.json()
        assert ed["comment_text"] == "Updated text"
        assert ed["comment_photo"] is not None
        assert ed["is_edited"] is True
        assert ed["edited_at"] is not None

        # Switching media to GIF and removing text still leaves valid comment
        switched = bob_client.patch(
            f"/api/v1/comments/{created['id']}/",
            {
                "comment_text": "",
                "comment_gif": "https://media.giphy.com/media/ok/giphy.gif",
            },
            format="json",
        )
        assert switched.status_code == status.HTTP_200_OK
        sw = switched.json()
        assert sw["comment_text"] is None
        assert sw["comment_photo"] is None
        assert sw["comment_gif"] == "https://media.giphy.com/media/ok/giphy.gif"
        assert sw["media_type"] == CommentMediaTypeEnum.GIF

        # Removing media when comment_text is already empty must fail
        empty_err = bob_client.patch(
            f"/api/v1/comments/{created['id']}/",
            {"remove_media": True},
            format="json",
        )
        assert empty_err.status_code == status.HTTP_400_BAD_REQUEST

    def test_delete_comment_cascades_subtree_and_updates_all_counters(self, comment_env):
        alice = comment_env["alice"]
        bob = comment_env["bob"]
        carol = comment_env["carol"]
        post = comment_env["alice_public_post"]

        root = create_comment(actor_user=alice, source_post_id=post.id, comment_text="Root")
        child1 = create_comment(actor_user=bob, source_post_id=post.id, source_comment_id=root.id, comment_text="Child 1")
        grandchild = create_comment(actor_user=carol, source_post_id=post.id, source_comment_id=child1.id, comment_text="Grandchild")
        child2 = create_comment(actor_user=carol, source_post_id=post.id, source_comment_id=root.id, comment_text="Child 2")

        post.refresh_from_db()
        assert post.comments_count == 4

        # Carol cannot delete Bob's comment (not author and not post owner)
        carol_client = _auth_client(carol)
        assert carol_client.delete(f"/api/v1/comments/{child1.id}/").status_code == status.HTTP_403_FORBIDDEN

        # Bob deletes child1 -> deletes child1 + grandchild (2 rows)
        bob_client = _auth_client(bob)
        del_resp = bob_client.delete(f"/api/v1/comments/{child1.id}/")
        assert del_resp.status_code == status.HTTP_200_OK
        assert del_resp.json()["deleted_count"] == 2

        assert not PostComment.objects.filter(id=grandchild.id).exists()
        root.refresh_from_db()
        post.refresh_from_db()
        assert root.replies_count == 1
        assert root.total_replies_count == 1
        assert post.comments_count == 2  # root + child2 remain

        # Post owner (Alice) can moderate and delete Carol's child2
        alice_client = _auth_client(alice)
        mod_del = alice_client.delete(f"/api/v1/posts/{post.id}/comments/{child2.id}/")
        assert mod_del.status_code == status.HTTP_200_OK
        post.refresh_from_db()
        root.refresh_from_db()
        assert post.comments_count == 1
        assert root.replies_count == 0
        assert root.total_replies_count == 0


@pytest.mark.django_db
class TestCommentSecurityPrivacyAndValidationEdges:
    def test_privacy_blocklists_age_restriction_and_guest_rules(self, comment_env):
        alice = comment_env["alice"]
        bob = comment_env["bob"]
        carol = comment_env["carol"]
        minor = comment_env["minor"]
        gym = comment_env["gym"]
        gym_owner = comment_env["gym_owner"]

        alice_public_post = comment_env["alice_public_post"]
        alice_followers_post = comment_env["alice_followers_post"]
        gym_members_post = comment_env["gym_members_post"]

        create_comment(actor_user=alice, source_post_id=alice_public_post.id, comment_text="Public comment")
        c_bob = create_comment(actor_user=bob, source_post_id=alice_public_post.id, comment_text="Bob comment")

        guest = APIClient()
        # Guest cannot post comment
        assert guest.post(f"/api/v1/posts/{alice_public_post.id}/comments/", {"comment_text": "Hi"}, format="json").status_code == status.HTTP_401_UNAUTHORIZED
        # Guest can read public post comments
        assert guest.get(f"/api/v1/posts/{alice_public_post.id}/comments/").status_code == status.HTTP_200_OK
        # Guest cannot read followers-only or members-only post comments
        assert guest.get(f"/api/v1/posts/{alice_followers_post.id}/comments/").status_code == status.HTTP_403_FORBIDDEN
        assert guest.get(f"/api/v1/posts/{gym_members_post.id}/comments/").status_code == status.HTTP_403_FORBIDDEN

        # Carol (non-follower, non-member) cannot comment on followers-only or members-only posts
        carol_client = _auth_client(carol)
        assert carol_client.post(f"/api/v1/posts/{alice_followers_post.id}/comments/", {"comment_text": "Sneak"}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert carol_client.post(f"/api/v1/posts/{gym_members_post.id}/comments/", {"comment_text": "Sneak"}, format="json").status_code == status.HTTP_403_FORBIDDEN

        # Bob (follower & member) CAN comment on both
        bob_client = _auth_client(bob)
        assert bob_client.post(f"/api/v1/posts/{alice_followers_post.id}/comments/", {"comment_text": "Follower comment"}, format="json").status_code == status.HTTP_201_CREATED
        assert bob_client.post(f"/api/v1/posts/{gym_members_post.id}/comments/", {"comment_text": "Member comment"}, format="json").status_code == status.HTTP_201_CREATED

        # Mutual user block hides comments and blocks replies
        UserBlockedUser.objects.create(blocker=bob, blocked_user=carol)
        visible_to_carol = carol_client.get(f"/api/v1/posts/{alice_public_post.id}/comments/").json()["results"]
        assert all(item["id"] != str(c_bob.id) for item in visible_to_carol)
        assert carol_client.post(f"/api/v1/comments/{c_bob.id}/replies/", {"comment_text": "Blocked reply"}, format="json").status_code == status.HTTP_403_FORBIDDEN

        # Gym block and 18+ age restriction
        gym_public_post = comment_env["gym_public_post"]
        GymBlockedUser.objects.create(gym=gym, user=carol, blocked_by=gym_owner)
        assert carol_client.post(f"/api/v1/posts/{gym_public_post.id}/comments/", {"comment_text": "Blocked"}, format="json").status_code == status.HTTP_403_FORBIDDEN

        gym.settings.posts_age_restriction = PostsAgeRestrictionEnum.AGE_18_PLUS
        gym.settings.save()
        minor_client = _auth_client(minor)
        assert minor_client.post(f"/api/v1/posts/{gym_public_post.id}/comments/", {"comment_text": "Underage"}, format="json").status_code == status.HTTP_403_FORBIDDEN

    def test_validation_edges_depth_cap_and_type_juggling(self, comment_env):
        alice = comment_env["alice"]
        post1 = comment_env["alice_public_post"]
        post2 = comment_env["gym_public_post"]
        client = _auth_client(alice)

        # Empty comment rejected
        assert client.post(f"/api/v1/posts/{post1.id}/comments/", {}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(f"/api/v1/posts/{post1.id}/comments/", {"comment_text": "   "}, format="json").status_code == status.HTTP_400_BAD_REQUEST

        # Multiple media attachments rejected
        assert client.post(
            f"/api/v1/posts/{post1.id}/comments/",
            {
                "comment_photo": _make_image("a.jpg"),
                "comment_gif": _make_gif("b.gif"),
            },
            format="multipart",
        ).status_code == status.HTTP_400_BAD_REQUEST

        # Wrong file formats per field rejected
        assert client.post(
            f"/api/v1/posts/{post1.id}/comments/",
            {"comment_photo": _make_fake_video("bad.mp4")},
            format="multipart",
        ).status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(
            f"/api/v1/posts/{post1.id}/comments/",
            {"comment_video": _make_image("bad.jpg")},
            format="multipart",
        ).status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(
            f"/api/v1/posts/{post1.id}/comments/",
            {"comment_gif": _make_image("not_gif.jpg")},
            format="multipart",
        ).status_code == status.HTTP_400_BAD_REQUEST

        # Type juggling (boolean/int instead of string/UUID)
        assert client.post(
            f"/api/v1/posts/{post1.id}/comments/",
            {"comment_text": True},
            format="json",
        ).status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(
            f"/api/v1/posts/{post1.id}/comments/",
            {"comment_gif": 12345},
            format="json",
        ).status_code == status.HTTP_400_BAD_REQUEST

        # Cross-post source_comment_id rejected
        c_post2 = create_comment(actor_user=alice, source_post_id=post2.id, comment_text="On post 2")
        assert client.post(
            f"/api/v1/posts/{post1.id}/comments/",
            {"source_comment_id": str(c_post2.id), "comment_text": "Cross post"},
            format="json",
        ).status_code == status.HTTP_400_BAD_REQUEST

        # Max nesting depth (10) enforced
        parent = create_comment(actor_user=alice, source_post_id=post1.id, comment_text="D0")
        for d in range(1, 11):
            parent = create_comment(
                actor_user=alice,
                source_post_id=post1.id,
                source_comment_id=parent.id,
                comment_text=f"D{d}",
            )
        assert parent.depth == 10
        assert client.post(
            f"/api/v1/comments/{parent.id}/replies/",
            {"comment_text": "Too deep D11"},
            format="json",
        ).status_code == status.HTTP_400_BAD_REQUEST
