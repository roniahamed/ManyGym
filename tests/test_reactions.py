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
from apps.gyms.models import Gym, GymBlockedUser, GymSetting
from apps.posts.models import GymPost, PostComment
from apps.posts.services import create_comment, create_post
from apps.reactions.models import Reaction, ReactionItem
from apps.reactions.services import seed_default_reaction_items
from apps.stories.models import Story
from apps.users.models import User, UserBlockedUser, UserProfile
from common.enums import (
    MediaTypeEnum,
    PostOwnerTypeEnum,
    PostPrivacyEnum,
    StaffStatus,
    StoryLifetimeEnum,
    StoryOwnerTypeEnum,
    StoryPrivacyEnum,
    TokenContextType,
)


def _auth_client(user, context_type=TokenContextType.PERSONAL, gym=None):
    token = issue_context_token(user=user, context_type=context_type, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def reaction_env(db):
    seed_default_permissions_and_roles()
    seed_default_reaction_items()

    alice = User.objects.create_user(
        email="alice_react@manygym.com",
        password="Password123!",
        first_name="Alice",
        last_name="React",
        is_verified=True,
    )
    UserProfile.objects.create(user=alice)

    bob = User.objects.create_user(
        email="bob_react@manygym.com",
        password="Password123!",
        first_name="Bob",
        last_name="Builder",
        is_verified=True,
    )
    UserProfile.objects.create(user=bob)

    charlie = User.objects.create_user(
        email="charlie_react@manygym.com",
        password="Password123!",
        first_name="Charlie",
        last_name="Athlete",
        is_verified=True,
    )
    UserProfile.objects.create(user=charlie)

    gym_owner = User.objects.create_user(
        email="gym_owner_react@manygym.com",
        password="Password123!",
        first_name="Gym",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.create(user=gym_owner)

    gym = Gym.objects.create(
        owner_user=gym_owner,
        name="Titan Reactions Gym",
        timezone="UTC",
    )
    GymSetting.objects.create(gym=gym)

    # Alice public post
    alice_post = create_post(
        gym=None,
        author_user=alice,
        content_text="Check out my new PR bench press!",
        privacy=PostPrivacyEnum.PUBLIC,
        owner_type=PostOwnerTypeEnum.USER,
    )

    # Comment on Alice post
    alice_comment = create_comment(
        actor_user=bob,
        source_post_id=alice_post.id,
        comment_text="Incredible work, Alice!",
    )

    # Nested reply to comment
    bob_reply = create_comment(
        actor_user=alice,
        source_post_id=alice_post.id,
        source_comment_id=alice_comment.id,
        comment_text="Thanks Bob! Let's hit leg day next.",
    )

    # Alice story
    alice_story = Story.objects.create(
        owner_type=StoryOwnerTypeEnum.USER,
        user=alice,
        media_url="https://cdn.manygym.com/alice_story.jpg",
        media_type=MediaTypeEnum.PICTURE,
        lifetime_hours=StoryLifetimeEnum.HOURS_18,
        privacy=StoryPrivacyEnum.PUBLIC,
        published_at=timezone.now(),
        expires_at=timezone.now() + timedelta(hours=18),
    )

    return {
        "alice": alice,
        "bob": bob,
        "charlie": charlie,
        "gym_owner": gym_owner,
        "gym": gym,
        "alice_post": alice_post,
        "alice_comment": alice_comment,
        "bob_reply": bob_reply,
        "alice_story": alice_story,
    }


@pytest.mark.django_db
class TestReactionItemsCatalog:
    """Tests master reaction item catalog and seed idempotency."""

    def test_list_reaction_items_returns_10_plus_items_including_smile_and_laugh(self, reaction_env):
        client = APIClient()
        res = client.get("/api/v1/reactions/items/")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()

        assert "results" in data
        assert data["count"] >= 10

        emojis = {item["emoji"]: item["code"] for item in data["results"]}
        codes = [item["code"] for item in data["results"]]

        # Explicit user request: 😊 and 😆 and 10+
        assert "😊" in emojis
        assert "😆" in emojis
        assert emojis["😊"] == "smile"
        assert emojis["😆"] == "laugh"

        # Check order sorting
        orders = [item["order"] for item in data["results"]]
        assert orders == sorted(orders)

    def test_seed_default_reaction_items_is_idempotent(self):
        # Call multiple times
        items1 = seed_default_reaction_items()
        items2 = seed_default_reaction_items()
        assert len(items1) == len(items2)
        assert ReactionItem.objects.count() == len(items1)


@pytest.mark.django_db
class TestPostReactions:
    """Tests reaction operations on community posts (create, toggle, switch, summary, remove)."""

    def test_post_reaction_lifecycle_create_toggle_and_switch(self, reaction_env):
        bob = reaction_env["bob"]
        post = reaction_env["alice_post"]
        bob_client = _auth_client(bob)

        # 1. React with Smile 😊
        res = bob_client.post(
            f"/api/v1/posts/{post.id}/reactions/",
            data={"reaction_code": "smile"},
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        body = res.json()
        assert body["status"] == "created"
        assert body["reaction"]["reaction_item"]["code"] == "smile"
        assert body["reaction"]["reaction_item"]["emoji"] == "😊"
        assert body["target"]["reactions_count"] == 1
        assert body["summary"]["total_reactions"] == 1
        assert body["summary"]["viewer_reaction"]["code"] == "smile"

        post.refresh_from_db()
        assert post.reactions_count == 1

        # 2. React with Smile 😊 again -> TOGGLE OFF (remove)
        res_toggle = bob_client.post(
            f"/api/v1/posts/{post.id}/reactions/",
            data={"reaction_code": "smile"},
            format="json",
        )
        assert res_toggle.status_code == status.HTTP_200_OK
        body_toggle = res_toggle.json()
        assert body_toggle["status"] == "removed"
        assert body_toggle["reaction"] is None
        assert body_toggle["target"]["reactions_count"] == 0
        assert body_toggle["summary"]["total_reactions"] == 0
        assert body_toggle["summary"]["viewer_reaction"] is None

        post.refresh_from_db()
        assert post.reactions_count == 0

        # 3. React with Laugh 😆
        res_laugh = bob_client.post(
            f"/api/v1/posts/{post.id}/reactions/",
            data={"reaction_code": "laugh"},
            format="json",
        )
        assert res_laugh.status_code == status.HTTP_201_CREATED
        assert res_laugh.json()["reaction"]["reaction_item"]["emoji"] == "😆"

        # 4. Switch from Laugh 😆 to Fire 🔥
        res_fire = bob_client.post(
            f"/api/v1/posts/{post.id}/reactions/",
            data={"reaction_code": "fire"},
            format="json",
        )
        assert res_fire.status_code == status.HTTP_200_OK
        body_fire = res_fire.json()
        assert body_fire["status"] == "updated"
        assert body_fire["reaction"]["reaction_item"]["code"] == "fire"
        assert body_fire["target"]["reactions_count"] == 1

        post.refresh_from_db()
        assert post.reactions_count == 1

        # 5. Explicit DELETE endpoint
        res_del = bob_client.delete(f"/api/v1/posts/{post.id}/reactions/")
        assert res_del.status_code == status.HTTP_200_OK
        assert res_del.json()["status"] == "removed"
        assert res_del.json()["target"]["reactions_count"] == 0

        post.refresh_from_db()
        assert post.reactions_count == 0

    def test_post_multiple_reactions_summary_and_filtering(self, reaction_env):
        alice = reaction_env["alice"]
        bob = reaction_env["bob"]
        charlie = reaction_env["charlie"]
        post = reaction_env["alice_post"]

        _auth_client(bob).post(f"/api/v1/posts/{post.id}/reactions/", data={"reaction_code": "fire"})
        _auth_client(charlie).post(f"/api/v1/posts/{post.id}/reactions/", data={"reaction_code": "fire"})
        _auth_client(alice).post(f"/api/v1/posts/{post.id}/reactions/", data={"reaction_code": "smile"})

        post.refresh_from_db()
        assert post.reactions_count == 3

        # Summary check
        res_summary = _auth_client(bob).get(f"/api/v1/posts/{post.id}/reactions/summary/")
        assert res_summary.status_code == status.HTTP_200_OK
        summary = res_summary.json()
        assert summary["total_reactions"] == 3
        assert summary["top_reactions"][0]["code"] == "fire"
        assert summary["top_reactions"][0]["count"] == 2
        assert summary["viewer_reaction"]["code"] == "fire"

        # List all reactions on post
        res_list = _auth_client(bob).get(f"/api/v1/posts/{post.id}/reactions/")
        assert res_list.status_code == status.HTTP_200_OK
        list_data = res_list.json()
        assert list_data["count"] == 3

        # Filter by code=fire
        res_filtered = _auth_client(bob).get(f"/api/v1/posts/{post.id}/reactions/?code=fire")
        assert res_filtered.status_code == status.HTTP_200_OK
        assert res_filtered.json()["count"] == 2

        # Filter by code=smile
        res_smile = _auth_client(bob).get(f"/api/v1/posts/{post.id}/reactions/?code=smile")
        assert res_smile.status_code == status.HTTP_200_OK
        assert res_smile.json()["count"] == 1

    def test_react_on_post_using_reaction_item_id(self, reaction_env):
        bob = reaction_env["bob"]
        post = reaction_env["alice_post"]
        smile_item = ReactionItem.objects.get(code="smile")

        client = _auth_client(bob)
        res = client.post(
            f"/api/v1/posts/{post.id}/reactions/",
            data={"reaction_item_id": str(smile_item.id)},
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        assert res.json()["reaction"]["reaction_item"]["id"] == str(smile_item.id)

    def test_react_as_gym_on_post(self, reaction_env):
        gym_owner = reaction_env["gym_owner"]
        gym = reaction_env["gym"]
        post = reaction_env["alice_post"]

        # React as gym
        client = _auth_client(gym_owner, context_type=TokenContextType.GYM, gym=gym)
        res = client.post(
            f"/api/v1/posts/{post.id}/reactions/",
            data={"reaction_code": "muscle", "owner_type": "gym", "gym_id": str(gym.id)},
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        body = res.json()
        assert body["reaction"]["owner_type"] == "gym"
        assert body["reaction"]["gym_id"] == str(gym.id)
        assert body["reaction"]["gym_name"] == gym.name

        # Non-staff cannot react as gym
        bob = reaction_env["bob"]
        bob_client = _auth_client(bob)
        res_bad = bob_client.post(
            f"/api/v1/posts/{post.id}/reactions/",
            data={"reaction_code": "fire", "owner_type": "gym", "gym_id": str(gym.id)},
            format="json",
        )
        assert res_bad.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestStoryReactions:
    """Tests reaction operations on ephemeral stories."""

    def test_story_reaction_lifecycle(self, reaction_env):
        bob = reaction_env["bob"]
        story = reaction_env["alice_story"]
        client = _auth_client(bob)

        # 1. React with Laugh 😆
        res = client.post(
            f"/api/v1/stories/{story.id}/reactions/",
            data={"reaction_code": "laugh"},
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        body = res.json()
        assert body["status"] == "created"
        assert body["reaction"]["reaction_item"]["emoji"] == "😆"
        assert body["target"]["reactions_count"] == 1

        story.refresh_from_db()
        assert story.reactions_count == 1

        # 2. Toggle off
        res_toggle = client.post(
            f"/api/v1/stories/{story.id}/reactions/",
            data={"reaction_code": "laugh"},
            format="json",
        )
        assert res_toggle.status_code == status.HTTP_200_OK
        assert res_toggle.json()["status"] == "removed"

        story.refresh_from_db()
        assert story.reactions_count == 0

        # 3. Switch emoji from Fire 🔥 to Love ❤️
        client.post(f"/api/v1/stories/{story.id}/reactions/", data={"reaction_code": "fire"})
        res_switch = client.post(f"/api/v1/stories/{story.id}/reactions/", data={"reaction_code": "love"})
        assert res_switch.status_code == status.HTTP_200_OK
        assert res_switch.json()["status"] == "updated"
        assert res_switch.json()["reaction"]["reaction_item"]["code"] == "love"

        # 4. Check story reactions summary
        res_sum = client.get(f"/api/v1/stories/{story.id}/reactions/summary/")
        assert res_sum.status_code == status.HTTP_200_OK
        assert res_sum.json()["total_reactions"] == 1
        assert res_sum.json()["viewer_reaction"]["code"] == "love"

        # 5. Delete reaction on story
        res_del = client.delete(f"/api/v1/stories/{story.id}/reactions/")
        assert res_del.status_code == status.HTTP_200_OK
        assert res_del.json()["status"] == "removed"

    def test_cannot_react_to_expired_story(self, reaction_env):
        bob = reaction_env["bob"]
        story = reaction_env["alice_story"]
        story.expires_at = timezone.now() - timedelta(minutes=10)
        story.save()

        client = _auth_client(bob)
        res = client.post(
            f"/api/v1/stories/{story.id}/reactions/",
            data={"reaction_code": "fire"},
            format="json",
        )
        assert res.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestCommentReactions:
    """Tests reaction operations on post comments and nested replies."""

    def test_comment_and_reply_reaction_lifecycle(self, reaction_env):
        alice = reaction_env["alice"]
        bob = reaction_env["bob"]
        comment = reaction_env["alice_comment"]
        reply = reaction_env["bob_reply"]

        alice_client = _auth_client(alice)
        bob_client = _auth_client(bob)

        # 1. Alice reacts with Strong 💪 to Bob's top-level comment
        res1 = alice_client.post(
            f"/api/v1/comments/{comment.id}/reactions/",
            data={"reaction_code": "muscle"},
            format="json",
        )
        assert res1.status_code == status.HTTP_201_CREATED
        assert res1.json()["reaction"]["reaction_item"]["code"] == "muscle"

        comment.refresh_from_db()
        assert comment.reactions_count == 1

        # Also accessible via post-scoped comment reaction URL
        post_id = reaction_env["alice_post"].id
        res_post_scoped = alice_client.get(
            f"/api/v1/posts/{post_id}/comments/{comment.id}/reactions/summary/"
        )
        assert res_post_scoped.status_code == status.HTTP_200_OK
        assert res_post_scoped.json()["total_reactions"] == 1

        # 2. Bob reacts with Clap 👏 to Alice's nested reply
        res2 = bob_client.post(
            f"/api/v1/comments/{reply.id}/reactions/",
            data={"reaction_code": "clap"},
            format="json",
        )
        assert res2.status_code == status.HTTP_201_CREATED
        assert res2.json()["reaction"]["reaction_item"]["code"] == "clap"

        reply.refresh_from_db()
        assert reply.reactions_count == 1

        # 3. Toggle off on comment
        res_off = alice_client.post(
            f"/api/v1/comments/{comment.id}/reactions/",
            data={"reaction_code": "muscle"},
            format="json",
        )
        assert res_off.status_code == status.HTTP_200_OK
        assert res_off.json()["status"] == "removed"
        comment.refresh_from_db()
        assert comment.reactions_count == 0

        # 4. Explicit delete on reply
        res_del_reply = bob_client.delete(f"/api/v1/comments/{reply.id}/reactions/")
        assert res_del_reply.status_code == status.HTTP_200_OK
        reply.refresh_from_db()
        assert reply.reactions_count == 0


@pytest.mark.django_db
class TestUnifiedReactionsEndpoint:
    """Tests /api/v1/reactions/ endpoint targeting post, story, and comment."""

    def test_unified_react_on_post_story_and_comment(self, reaction_env):
        bob = reaction_env["bob"]
        post = reaction_env["alice_post"]
        story = reaction_env["alice_story"]
        comment = reaction_env["alice_comment"]
        client = _auth_client(bob)

        # 1. Post via unified endpoint
        res_post = client.post(
            "/api/v1/reactions/",
            data={"post_id": str(post.id), "reaction_code": "smile"},
            format="json",
        )
        assert res_post.status_code == status.HTTP_201_CREATED
        post_reaction_id = res_post.json()["reaction"]["id"]

        # 2. Story via unified endpoint
        res_story = client.post(
            "/api/v1/reactions/",
            data={"story_id": str(story.id), "reaction_code": "fire"},
            format="json",
        )
        assert res_story.status_code == status.HTTP_201_CREATED

        # 3. Comment via unified endpoint
        res_comment = client.post(
            "/api/v1/reactions/",
            data={"comment_id": str(comment.id), "reaction_code": "laugh"},
            format="json",
        )
        assert res_comment.status_code == status.HTTP_201_CREATED

        # 4. Filter via unified GET
        res_list = client.get(f"/api/v1/reactions/?post_id={post.id}")
        assert res_list.status_code == status.HTTP_200_OK
        assert res_list.json()["count"] == 1

        # 5. Lookup reaction by ID
        res_detail = client.get(f"/api/v1/reactions/{post_reaction_id}/")
        assert res_detail.status_code == status.HTTP_200_OK
        assert res_detail.json()["reaction_item"]["code"] == "smile"

        # 6. Delete reaction by ID
        res_del = client.delete(f"/api/v1/reactions/{post_reaction_id}/")
        assert res_del.status_code == status.HTTP_200_OK
        assert res_del.json()["status"] == "removed"

        post.refresh_from_db()
        assert post.reactions_count == 0


@pytest.mark.django_db
class TestValidationAndSecurityEdgeCases:
    """Tests security boundaries, permissions, invalid payloads, and constraints."""

    def test_unauthenticated_cannot_react(self, reaction_env):
        post = reaction_env["alice_post"]
        anon = APIClient()
        res = anon.post(f"/api/v1/posts/{post.id}/reactions/", data={"reaction_code": "smile"})
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cannot_specify_multiple_targets(self, reaction_env):
        bob = reaction_env["bob"]
        post = reaction_env["alice_post"]
        story = reaction_env["alice_story"]
        client = _auth_client(bob)

        res = client.post(
            "/api/v1/reactions/",
            data={
                "post_id": str(post.id),
                "story_id": str(story.id),
                "reaction_code": "smile",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_specify_zero_targets_on_unified_endpoint(self, reaction_env):
        bob = reaction_env["bob"]
        client = _auth_client(bob)
        res = client.post(
            "/api/v1/reactions/",
            data={"reaction_code": "smile"},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_blocked_user_cannot_react_to_post(self, reaction_env):
        alice = reaction_env["alice"]
        bob = reaction_env["bob"]
        post = reaction_env["alice_post"]

        # Alice blocks Bob
        UserBlockedUser.objects.create(blocker=alice, blocked_user=bob)

        bob_client = _auth_client(bob)
        res = bob_client.post(
            f"/api/v1/posts/{post.id}/reactions/",
            data={"reaction_code": "smile"},
            format="json",
        )
        assert res.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN)

    def test_cascade_deletion_cleans_up_reactions(self, reaction_env):
        bob = reaction_env["bob"]
        post = reaction_env["alice_post"]
        story = reaction_env["alice_story"]
        comment = reaction_env["alice_comment"]

        _auth_client(bob).post(f"/api/v1/posts/{post.id}/reactions/", data={"reaction_code": "smile"})
        _auth_client(bob).post(f"/api/v1/stories/{story.id}/reactions/", data={"reaction_code": "fire"})
        _auth_client(bob).post(f"/api/v1/comments/{comment.id}/reactions/", data={"reaction_code": "laugh"})

        assert Reaction.objects.count() == 3

        post.delete()
        # Post and its comments deleted -> post reaction and comment reaction should be gone
        assert Reaction.objects.filter(post__isnull=False).count() == 0
        assert Reaction.objects.filter(comment__isnull=False).count() == 0

        story.delete()
        assert Reaction.objects.filter(story__isnull=False).count() == 0
        assert Reaction.objects.count() == 0

