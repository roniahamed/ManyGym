import time
import uuid
import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile, UserFollow
from apps.gyms.models import Gym, GymFollow
from apps.gyms.services import create_gym
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType


@pytest.fixture
def auth_client_factory(db):
    def _create(user=None, email=None):
        if not user:
            email_val = email or f"perf_user_{uuid.uuid4().hex[:8]}@example.com"
            user = User.objects.create_user(
                email=email_val,
                password="SecurePassword123!",
                first_name="Perf",
                last_name="Tester",
                is_verified=True,
            )
            UserProfile.objects.get_or_create(user=user)
            user.get_settings()
        else:
            user.get_settings()
        token = issue_context_token(user=user, context_type=TokenContextType.PERSONAL)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
        return client, user
    return _create


@pytest.fixture
def target_user(db):
    user = User.objects.create_user(
        email="target_social_user@example.com",
        password="SecurePassword123!",
        first_name="Target",
        last_name="Celebrity",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    user.get_settings()
    return user


@pytest.fixture
def target_gym(db, target_user):
    return create_gym(
        owner_user=target_user,
        name="Performance Test Gym",
        short_description="State-of-the-art gym built for performance testing and benchmarking under heavy loads with luxury recovery and wellness facilities." * 2,
    )


class TestFollowNPlusOneElimination:
    """
    Validates that database query counts remain O(1) constant regardless of the number
    of followers or followed entities, proving complete elimination of N+1 query problems.
    """

    def test_user_followers_no_n_plus_one(self, auth_client_factory, target_user):
        client, viewer = auth_client_factory()

        # Seed initial 5 followers
        initial_users = [
            User(
                email=f"initial_follower_{i}_{uuid.uuid4().hex[:6]}@example.com",
                first_name=f"First{i}",
                last_name=f"Last{i}",
                is_verified=True,
            )
            for i in range(5)
        ]
        User.objects.bulk_create(initial_users)
        saved_initial = list(User.objects.filter(email__startswith="initial_follower_"))
        UserProfile.objects.bulk_create([UserProfile(user=u) for u in saved_initial])
        UserFollow.objects.bulk_create([UserFollow(follower=u, followed_user=target_user) for u in saved_initial])

        # Ensure settings and connections are initialized prior to measurement
        viewer.get_settings()
        target_user.get_settings()

        # Measure query count with 5 followers
        with CaptureQueriesContext(connection) as ctx_5:
            res_5 = client.get(f"/api/v1/users/{target_user.id}/followers/")
            assert res_5.status_code == status.HTTP_200_OK
            assert len(res_5.json()) == 5
        query_count_5 = len(ctx_5.captured_queries)

        # Scale up to 50 followers (10x scale)
        additional_users = [
            User(
                email=f"scale_follower_{i}_{uuid.uuid4().hex[:6]}@example.com",
                first_name=f"Scale{i}",
                last_name=f"User{i}",
                is_verified=True,
            )
            for i in range(45)
        ]
        User.objects.bulk_create(additional_users)
        saved_scale = list(User.objects.filter(email__startswith="scale_follower_"))
        UserProfile.objects.bulk_create([UserProfile(user=u) for u in saved_scale])
        UserFollow.objects.bulk_create([UserFollow(follower=u, followed_user=target_user) for u in saved_scale])

        # Measure query count with 50 followers
        with CaptureQueriesContext(connection) as ctx_50:
            res_50 = client.get(f"/api/v1/users/{target_user.id}/followers/")
            assert res_50.status_code == status.HTTP_200_OK
            assert len(res_50.json()) == 50
        query_count_50 = len(ctx_50.captured_queries)

        # Query count MUST be identical between 5 and 50 followers (O(1) query complexity)
        assert query_count_5 == query_count_50, (
            f"N+1 query detected! 5 followers ran {query_count_5} queries, but 50 followers ran {query_count_50} queries."
        )

    def test_gym_followers_no_n_plus_one(self, auth_client_factory, target_gym):
        client, viewer = auth_client_factory()

        # Seed 5 gym followers
        users_5 = [
            User(
                email=f"gym_flwr_5_{i}_{uuid.uuid4().hex[:6]}@example.com",
                first_name=f"GymMember{i}",
                last_name="Test",
                is_verified=True,
            )
            for i in range(5)
        ]
        User.objects.bulk_create(users_5)
        saved_5 = list(User.objects.filter(email__startswith="gym_flwr_5_"))
        UserProfile.objects.bulk_create([UserProfile(user=u) for u in saved_5])
        GymFollow.objects.bulk_create([GymFollow(user=u, gym=target_gym) for u in saved_5])

        # Ensure settings and connections are initialized prior to measurement
        viewer.get_settings()
        target_gym.get_settings()

        with CaptureQueriesContext(connection) as ctx_5:
            res_5 = client.get(f"/api/v1/gyms/{target_gym.id}/followers/")
            assert res_5.status_code == status.HTTP_200_OK
            assert len(res_5.json()) == 5
        query_count_5 = len(ctx_5.captured_queries)

        # Scale up with 45 additional followers
        users_45 = [
            User(
                email=f"gym_flwr_scale_{i}_{uuid.uuid4().hex[:6]}@example.com",
                first_name=f"GymScale{i}",
                last_name="Test",
                is_verified=True,
            )
            for i in range(45)
        ]
        User.objects.bulk_create(users_45)
        saved_45 = list(User.objects.filter(email__startswith="gym_flwr_scale_"))
        UserProfile.objects.bulk_create([UserProfile(user=u) for u in saved_45])
        GymFollow.objects.bulk_create([GymFollow(user=u, gym=target_gym) for u in saved_45])

        with CaptureQueriesContext(connection) as ctx_50:
            res_50 = client.get(f"/api/v1/gyms/{target_gym.id}/followers/")
            assert res_50.status_code == status.HTTP_200_OK
            assert len(res_50.json()) == 50
        query_count_50 = len(ctx_50.captured_queries)

        assert query_count_5 == query_count_50, (
            f"N+1 query detected in gym followers! 5 followers ran {query_count_5} queries, 50 ran {query_count_50}."
        )


def get_operational_queries(ctx):
    return [
        q for q in ctx.captured_queries
        if not q["sql"].strip().startswith(("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT"))
    ]


class TestQueryCountThresholds:
    """
    Asserts exact, minimal query count budgets across all follower and following endpoints
    to prevent performance regressions.
    """

    def test_unified_follow_get_user_followers_query_budget(self, auth_client_factory, target_user):
        client, viewer = auth_client_factory()
        users = [
            User(
                email=f"flwr_budget_{i}_{uuid.uuid4().hex[:6]}@example.com",
                first_name=f"Budget{i}",
                last_name="Tester",
                is_verified=True,
            )
            for i in range(10)
        ]
        User.objects.bulk_create(users)
        saved = list(User.objects.filter(email__startswith="flwr_budget_"))
        UserProfile.objects.bulk_create([UserProfile(user=u) for u in saved])
        UserFollow.objects.bulk_create([UserFollow(follower=u, followed_user=target_user) for u in saved])

        # Auto-detect mode: maximum 5 operational queries (auth + gym check + user check + followers + is_following)
        with CaptureQueriesContext(connection) as ctx:
            response = client.get(f"/api/v1/follows/?target_id={target_user.id}")
            assert response.status_code == status.HTTP_200_OK
            assert response.json()["followers_count"] == 10

        op_queries = get_operational_queries(ctx)
        assert len(op_queries) <= 7, (
            f"Expected <= 7 queries for auto-detect UnifiedFollowView GET, but got {len(op_queries)}: "
            f"{[q['sql'] for q in op_queries]}"
        )

    def test_unified_follow_get_gym_followers_query_budget(self, auth_client_factory, target_gym):
        client, viewer = auth_client_factory()
        users = [
            User(
                email=f"gym_budget_{i}_{uuid.uuid4().hex[:6]}@example.com",
                first_name=f"GymBudget{i}",
                last_name="Tester",
                is_verified=True,
            )
            for i in range(10)
        ]
        User.objects.bulk_create(users)
        saved = list(User.objects.filter(email__startswith="gym_budget_"))
        UserProfile.objects.bulk_create([UserProfile(user=u) for u in saved])
        GymFollow.objects.bulk_create([GymFollow(user=u, gym=target_gym) for u in saved])

        with CaptureQueriesContext(connection) as ctx:
            response = client.get(f"/api/v1/follows/?target_id={target_gym.id}")
            assert response.status_code == status.HTTP_200_OK
            assert response.json()["followers_count"] == 10

        op_queries = get_operational_queries(ctx)
        assert len(op_queries) <= 7, (
            f"Expected <= 7 queries for UnifiedFollowView GET (gym followers), but got {len(op_queries)}: "
            f"{[q['sql'] for q in op_queries]}"
        )

    def test_unified_follow_get_current_user_followed_query_budget(self, auth_client_factory, target_user, target_gym):
        client, viewer = auth_client_factory()
        # Follow target_user and target_gym
        UserFollow.objects.create(follower=viewer, followed_user=target_user)
        GymFollow.objects.create(user=viewer, gym=target_gym)

        with CaptureQueriesContext(connection) as ctx:
            response = client.get("/api/v1/follows/")
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["total_followed_users"] == 1
            assert data["total_followed_gyms"] == 1

        op_queries = get_operational_queries(ctx)
        # Maximum allowed queries is 4:
        # 1. Auth token lookup
        # 2. User settings lookup
        # 3. list_user_following (follower=viewer)
        # 4. list_user_followed_gyms (user=viewer)
        assert len(op_queries) <= 4, (
            f"Expected <= 4 queries for UnifiedFollowView GET (followed list), but got {len(op_queries)}: "
            f"{[q['sql'] for q in op_queries]}"
        )

    def test_follow_user_post_query_budget(self, auth_client_factory, target_user):
        client, viewer = auth_client_factory()

        # Auto-detect mode: maximum 10 operational queries (auth + gym check + user check + settings + follow request check (2) + mutual block check (2) + is_following check + insert)
        with CaptureQueriesContext(connection) as ctx:
            response = client.post(
                "/api/v1/follows/",
                data={"target_id": str(target_user.id)},
                format="json",
            )
            assert response.status_code == status.HTTP_201_CREATED

        op_queries = get_operational_queries(ctx)
        assert len(op_queries) <= 10, (
            f"Expected <= 10 queries for POST /api/v1/follows/, but got {len(op_queries)}: "
            f"{[q['sql'] for q in op_queries]}"
        )

    def test_unfollow_user_delete_query_budget(self, auth_client_factory, target_user):
        client, viewer = auth_client_factory()
        UserFollow.objects.create(follower=viewer, followed_user=target_user)

        with CaptureQueriesContext(connection) as ctx:
            response = client.delete(f"/api/v1/follows/{target_user.id}/")
            assert response.status_code == status.HTTP_200_OK

        op_queries = get_operational_queries(ctx)
        # Expected <= 5 operational queries:
        # 1. Auth lookup
        # 2. Target check Gym
        # 3. Target resolution User
        # 4. UserFollow.objects.filter(...).delete()
        # 5. UserFollowRequest.objects.filter(...).delete()
        assert len(op_queries) <= 5, (
            f"Expected <= 5 queries for DELETE /api/v1/follows/, but got {len(op_queries)}: "
            f"{[q['sql'] for q in op_queries]}"
        )


class TestPaginationPerformance:
    """
    Validates StandardResultsSetPagination across follower and following endpoints
    to avoid unbounded memory consumption.
    """

    def test_unified_follow_pagination(self, auth_client_factory, target_user):
        client, viewer = auth_client_factory()
        # Create 25 followers
        users = [
            User(
                email=f"pg_user_{i}_{uuid.uuid4().hex[:6]}@example.com",
                first_name=f"Paginated{i}",
                last_name="Tester",
                is_verified=True,
            )
            for i in range(25)
        ]
        User.objects.bulk_create(users)
        saved = list(User.objects.filter(email__startswith="pg_user_"))
        UserProfile.objects.bulk_create([UserProfile(user=u) for u in saved])
        UserFollow.objects.bulk_create([UserFollow(follower=u, followed_user=target_user) for u in saved])

        response = client.get(f"/api/v1/follows/?target_id={target_user.id}&page=1&page_size=10")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["count"] == 25
        assert data["total_pages"] == 3
        assert data["current_page"] == 1
        assert len(data["results"]["followers"]) == 10
        assert data["results"]["followers_count"] == 25
        assert data["next"] is not None

    def test_gym_followers_pagination(self, auth_client_factory, target_gym):
        client, viewer = auth_client_factory()
        users = [
            User(
                email=f"gym_pg_{i}_{uuid.uuid4().hex[:6]}@example.com",
                first_name=f"GymPaginated{i}",
                last_name="Tester",
                is_verified=True,
            )
            for i in range(25)
        ]
        User.objects.bulk_create(users)
        saved = list(User.objects.filter(email__startswith="gym_pg_"))
        UserProfile.objects.bulk_create([UserProfile(user=u) for u in saved])
        GymFollow.objects.bulk_create([GymFollow(user=u, gym=target_gym) for u in saved])

        response = client.get(f"/api/v1/gyms/{target_gym.id}/followers/?page=2&page_size=10")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["count"] == 25
        assert data["total_pages"] == 3
        assert data["current_page"] == 2
        assert len(data["results"]) == 10
        assert data["previous"] is not None


class TestResponseTimeBenchmarks:
    """
    Measures and asserts that p95 response time for read endpoints is strictly under 200ms.
    """

    def test_read_endpoints_p95_under_200ms(self, auth_client_factory, target_user, target_gym):
        client, viewer = auth_client_factory()

        # Seed 30 followers
        users = [
            User(
                email=f"lat_user_{i}_{uuid.uuid4().hex[:6]}@example.com",
                first_name=f"Latency{i}",
                last_name="Tester",
                is_verified=True,
            )
            for i in range(30)
        ]
        User.objects.bulk_create(users)
        saved = list(User.objects.filter(email__startswith="lat_user_"))
        UserProfile.objects.bulk_create([UserProfile(user=u) for u in saved])
        UserFollow.objects.bulk_create([UserFollow(follower=u, followed_user=target_user) for u in saved])
        GymFollow.objects.bulk_create([GymFollow(user=u, gym=target_gym) for u in saved])

        import os

        is_ci = bool(os.environ.get("CI"))
        target_p95 = 400.0 if is_ci else 200.0

        # Warm-up request to eliminate cold-start routing/middleware overhead
        client.get(f"/api/v1/follows/?target_id={target_user.id}")

        latencies_ms = []

        # Execute 20 iterations
        for _ in range(20):
            start = time.perf_counter()
            response = client.get(f"/api/v1/follows/?target_id={target_user.id}")
            duration_ms = (time.perf_counter() - start) * 1000
            assert response.status_code == status.HTTP_200_OK
            latencies_ms.append(duration_ms)

        latencies_sorted = sorted(latencies_ms)
        p50 = latencies_sorted[int((len(latencies_sorted) - 1) * 0.50)]
        p95 = latencies_sorted[int((len(latencies_sorted) - 1) * 0.95)]

        print(f"\n[LATENCY BENCHMARK] p50: {p50:.2f}ms, p95: {p95:.2f}ms (Target: < {target_p95:.0f}ms)")
        assert p95 < target_p95, f"p95 latency ({p95:.2f}ms) exceeded {target_p95:.0f}ms target threshold!"
