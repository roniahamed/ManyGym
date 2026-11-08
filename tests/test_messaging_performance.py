import time
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile, UserFollow
from apps.gyms.models import Gym
from apps.gyms.services import create_gym
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, MessageSenderTypeEnum
from apps.messaging.services import (
    get_or_create_user_to_user_conversation,
    get_or_create_user_to_gym_conversation,
    get_or_create_gym_to_gym_conversation,
    send_encrypted_message,
)


@pytest.fixture
def perf_setup(db):
    """
    Sets up a realistic workload:
    - Primary user Alice with linked UserProfile
    - 10 other users with UserProfiles
    - 2 gyms
    - 10 conversations (user-to-user, user-to-gym, gym-to-gym)
    - 50 messages in Alice's primary conversation
    """
    alice = User.objects.create_user(
        email="alice_perf@example.com",
        password="Password123!",
        first_name="Alice",
        last_name="Performance",
        is_verified=True,
    )
    UserProfile.objects.create(user=alice, avatar_url="https://example.com/alice.png")

    gym1 = create_gym(owner_user=alice, name="Performance Gym Alpha")
    bob = User.objects.create_user(
        email="bob_perf@example.com",
        password="Password123!",
        first_name="Bob",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.create(user=bob, avatar_url="https://example.com/bob.png")
    gym2 = create_gym(owner_user=bob, name="Performance Gym Beta")

    conversations = []
    # Create 8 user-to-user conversations with distinct users
    for i in range(8):
        peer = User.objects.create_user(
            email=f"peer_{i}@example.com",
            password="Password123!",
            first_name=f"Peer{i}",
            last_name="Test",
            is_verified=True,
        )
        UserProfile.objects.create(user=peer, avatar_url=f"https://example.com/peer_{i}.png")
        UserFollow.objects.create(follower=alice, followed_user=peer)
        UserFollow.objects.create(follower=peer, followed_user=alice)
        conv = get_or_create_user_to_user_conversation(alice, peer)
        conversations.append(conv)

    # 1 User to Gym conversation
    u2g_conv = get_or_create_user_to_gym_conversation(alice, gym2)
    conversations.append(u2g_conv)

    # 1 Gym to Gym conversation
    g2g_conv = get_or_create_gym_to_gym_conversation(alice, gym1, gym2)
    conversations.append(g2g_conv)

    # Populate 50 messages in the first conversation
    primary_conv = conversations[0]
    for m in range(50):
        send_encrypted_message(
            conversation=primary_conv,
            sender_user=alice if m % 2 == 0 else primary_conv.user_b,
            sender_type=MessageSenderTypeEnum.USER,
            ciphertext=f"ciphertext_payload_number_{m}==",
            nonce=f"nonce_{m}==",
        )

    # Auth clients
    alice_tokens = issue_context_token(alice, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {alice_tokens['access']}")

    return {
        "alice": alice,
        "client": client,
        "conversations": conversations,
        "primary_conv": primary_conv,
        "gym1": gym1,
        "gym2": gym2,
    }


@pytest.mark.django_db
class TestMessagingPerformanceBenchmarks:
    """
    Benchmarks query count, response time, and N+1 query elimination
    across performance-critical messaging endpoints.
    """

    def test_conversations_list_query_count_and_n_plus_one_elimination(self, perf_setup, django_assert_num_queries):
        client = perf_setup["client"]

        # Warmup request to eliminate initial lazy-loading and URL resolving latency
        client.get("/api/v1/messaging/conversations/")

        # Measure baseline query count
        with CaptureQueriesContext(connection) as ctx:
            start_time = time.perf_counter()
            res = client.get("/api/v1/messaging/conversations/")
            duration_ms = (time.perf_counter() - start_time) * 1000

        assert res.status_code == status.HTTP_200_OK
        assert len(res.data) >= 8  # all active conversations returned

        query_count = len(ctx)
        print(f"\n[BENCHMARK] Conversations List: {query_count} queries in {duration_ms:.2f}ms")
        for i, q in enumerate(ctx.captured_queries):
            print(f"  Q{i+1}: {q['sql'][:120]}...")

        # Without optimization, 10 conversations trigger 22 queries due to user.profile N+1
        # With optimization, query count is reduced by ~70%+ down to 6 queries!
        assert query_count <= 6, f"Expected <= 6 queries, got {query_count}"
        assert duration_ms < 200, f"Response time exceeded 200ms target! Got {duration_ms:.2f}ms"

    def test_conversation_detail_query_count(self, perf_setup):
        client = perf_setup["client"]
        conv_id = perf_setup["primary_conv"].id

        with CaptureQueriesContext(connection) as ctx:
            start_time = time.perf_counter()
            res = client.get(f"/api/v1/messaging/conversations/{conv_id}/")
            duration_ms = (time.perf_counter() - start_time) * 1000

        assert res.status_code == status.HTTP_200_OK
        query_count = len(ctx)
        print(f"\n[BENCHMARK] Conversation Detail: {query_count} queries in {duration_ms:.2f}ms")
        for i, q in enumerate(ctx.captured_queries):
            print(f"  Q{i+1}: {q['sql'][:120]}...")

        # Must execute in at most 5 queries (reduced from 7)
        assert query_count <= 5, f"Too many queries for conversation detail: {query_count}"
        assert duration_ms < 100, f"Detail response time exceeded 100ms: {duration_ms:.2f}ms"

    def test_conversation_messages_history_query_count_and_timing(self, perf_setup):
        client = perf_setup["client"]
        conv_id = perf_setup["primary_conv"].id

        with CaptureQueriesContext(connection) as ctx:
            start_time = time.perf_counter()
            res = client.get(f"/api/v1/messaging/conversations/{conv_id}/messages/?limit=50")
            duration_ms = (time.perf_counter() - start_time) * 1000

        assert res.status_code == status.HTTP_200_OK
        assert len(res.data) == 50

        query_count = len(ctx)
        print(f"\n[BENCHMARK] Conversation Messages (50 items): {query_count} queries in {duration_ms:.2f}ms")

        # Fetching 50 messages must take at most 3 queries (auth + conversation access check + messages select_related)
        assert query_count <= 3, f"Too many queries fetching messages: {query_count}"
        assert duration_ms < 150, f"Messages response time exceeded 150ms: {duration_ms:.2f}ms"

    def test_mark_conversation_read_efficiency(self, perf_setup):
        client = perf_setup["client"]
        conv_id = perf_setup["primary_conv"].id

        with CaptureQueriesContext(connection) as ctx:
            start_time = time.perf_counter()
            res = client.post(f"/api/v1/messaging/conversations/{conv_id}/read/", {}, format="json")
            duration_ms = (time.perf_counter() - start_time) * 1000

        assert res.status_code == status.HTTP_200_OK
        query_count = len(ctx)
        print(f"\n[BENCHMARK] Mark Read: {query_count} queries in {duration_ms:.2f}ms")
        for i, q in enumerate(ctx.captured_queries):
            print(f"  Q{i+1}: {q['sql'][:120]}...")

        # Reduced from 9 down to 7 queries
        assert query_count <= 7, f"Too many queries marking read: {query_count}"
        assert duration_ms < 150, f"Mark read response time exceeded 150ms: {duration_ms:.2f}ms"
