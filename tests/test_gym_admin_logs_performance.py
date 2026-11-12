import time
import uuid
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym, GymAdminLog
from apps.gyms.services import create_gym
from apps.gyms.services.admin_log_services import log_admin_action
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, AdminLogCategory, AdminLogActionType


@pytest.fixture
def perf_owner_user(db):
    user = User.objects.create_user(
        email="owner.perf.logs@manygym.com",
        password="SecurePassword123!",
        first_name="Marcus",
        last_name="Aurelius",
        is_verified=True,
    )
    UserProfile.objects.create(
        user=user,
        avatar_url="https://cdn.manygym.com/marcus.webp",
    )
    return user


@pytest.fixture
def perf_staff_user(db):
    user = User.objects.create_user(
        email="staff.perf.logs@manygym.com",
        password="SecurePassword123!",
        first_name="Lucius",
        last_name="Verus",
        is_verified=True,
    )
    UserProfile.objects.create(
        user=user,
        avatar_url="https://cdn.manygym.com/lucius.webp",
    )
    return user


@pytest.fixture
def perf_gym(perf_owner_user):
    return create_gym(owner_user=perf_owner_user, name="Olympus Performance Arena")


@pytest.fixture
def auth_client(perf_owner_user):
    tokens = issue_context_token(perf_owner_user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def populated_logs(perf_gym, perf_owner_user, perf_staff_user):
    """Seeds 60 realistic administrative audit logs across various actors and categories."""
    logs = []
    categories = [
        AdminLogCategory.GYM_PROFILE,
        AdminLogCategory.POSTS,
        AdminLogCategory.ACCESS_CONTROL,
        AdminLogCategory.VISIBILITY,
        AdminLogCategory.MEMBERS,
        AdminLogCategory.MEMBERSHIP_PLANS,
    ]
    actions = [
        ("Updated page information", AdminLogActionType.UPDATE_PAGE_INFO),
        ("Published a post", AdminLogActionType.PUBLISH_POST),
        ("Added an admin", AdminLogActionType.ADD_ADMIN),
        ("Changed page visibility", AdminLogActionType.CHANGE_PAGE_VISIBILITY),
        ("Created a member", AdminLogActionType.CREATE_MEMBER),
        ("Created a custom membership plan", AdminLogActionType.CREATE_MEMBERSHIP_PLAN),
    ]

    for i in range(60):
        actor = perf_owner_user if i % 2 == 0 else perf_staff_user
        idx = i % len(actions)
        act, act_type = actions[idx]
        cat = categories[idx]

        log_item = GymAdminLog(
            gym=perf_gym,
            actor=actor,
            actor_name=f"{actor.first_name} {actor.last_name}",
            actor_email=actor.email,
            action=f"{act} #{i}",
            action_type=act_type,
            category=cat,
            details=f"Performance test detail record #{i}",
            target_type="gym" if idx == 0 else "post",
            target_id=str(uuid.uuid4()),
            metadata={"iteration": i, "batch": "perf_test"},
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0 Performance Benchmark Suite v1.0",
        )
        logs.append(log_item)

    GymAdminLog.objects.bulk_create(logs)
    return logs


@pytest.mark.django_db
class TestGymAdminLogsPerformanceAndQueryBudgets:
    """
    Measurable performance verification suite for the Gym Admin Logs subsystem.
    Enforces strict query budgets, N+1 query elimination, database aggregations,
    and p95 latency targets under load.
    """

    # =========================================================================
    # 1. QUERY BUDGETS & CONSOLIDATION
    # =========================================================================

    def test_list_admin_logs_query_budget(
        self, auth_client, perf_gym, populated_logs, django_assert_num_queries
    ):
        """
        GET /api/v1/gyms/logs/admin/
        Strict query budget: Exactly 4 queries
        1. FastJWT user authentication + profile prefetch
        2. resolve_gym_context (Gym lookup)
        3. COUNT(*) query for pagination envelope
        4. Paginated records with select_related('actor', 'actor__profile') and only() projections
        """
        url = f"{reverse('gyms_v1:gym-admin-logs-list')}?gym_id={perf_gym.id}&page=1&page_size=20"

        with django_assert_num_queries(4):
            resp = auth_client.get(url)
            assert resp.status_code == status.HTTP_200_OK
            data = resp.json()
            assert data["count"] == 60
            assert len(data["results"]) == 20
            assert data["results"][0]["admin"]["full_name"] != ""

    def test_list_admin_logs_n_plus_one_elimination(
        self, auth_client, perf_gym, populated_logs, django_assert_num_queries
    ):
        """
        N+1 Verification: Query count must remain constant O(1) regardless of page size.
        Fetching 5 records vs 50 records must both execute in exactly 4 queries.
        """
        url_5 = f"{reverse('gyms_v1:gym-admin-logs-list')}?gym_id={perf_gym.id}&page=1&page_size=5"
        url_50 = f"{reverse('gyms_v1:gym-admin-logs-list')}?gym_id={perf_gym.id}&page=1&page_size=50"

        with django_assert_num_queries(4):
            resp_5 = auth_client.get(url_5)
            assert resp_5.status_code == status.HTTP_200_OK
            assert len(resp_5.json()["results"]) == 5

        with django_assert_num_queries(4):
            resp_50 = auth_client.get(url_50)
            assert resp_50.status_code == status.HTTP_200_OK
            assert len(resp_50.json()["results"]) == 50

    def test_metrics_admin_logs_query_budget(
        self, auth_client, perf_gym, populated_logs, django_assert_num_queries
    ):
        """
        GET /api/v1/gyms/logs/admin/metrics/
        Strict query budget: Exactly 5 queries
        1. FastJWT auth + profile
        2. resolve_gym_context
        3. Consolidated database aggregation: total_logs + logs_today in 1 SQL query using Q filter
        4. Category count distribution (GROUP BY category)
        5. 5 Recent logs with select_related('actor', 'actor__profile') and only() projections
        """
        url = f"{reverse('gyms_v1:gym-admin-logs-metrics')}?gym_id={perf_gym.id}"

        with django_assert_num_queries(5):
            resp = auth_client.get(url)
            assert resp.status_code == status.HTTP_200_OK
            data = resp.json()
            assert data["total_logs"] == 60
            assert len(data["recent_logs"]) == 5
            assert len(data["by_category"]) > 0

    def test_detail_admin_logs_query_budget(
        self, auth_client, perf_gym, populated_logs, django_assert_num_queries
    ):
        """
        GET /api/v1/gyms/logs/admin/<id>/
        Strict query budget: Exactly 3 queries (auth + context + single log select_related).
        """
        target_log = populated_logs[0]
        url = f"{reverse('gyms_v1:gym-admin-log-detail', kwargs={'log_id': target_log.id})}?gym_id={perf_gym.id}"

        with django_assert_num_queries(3):
            resp = auth_client.get(url)
            assert resp.status_code == status.HTTP_200_OK
            assert resp.json()["id"] == str(target_log.id)

    def test_post_record_admin_log_query_budget(
        self, auth_client, perf_gym, django_assert_num_queries
    ):
        """
        POST /api/v1/gyms/logs/admin/
        Strict query budget: Exactly 5 queries under pytest atomic transaction:
        - 3 operational queries: (1) FastJWT auth + profile, (2) resolve_gym_context, (3) INSERT INTO gym_admin_logs
        - 2 atomic savepoint wrappers (SAVEPOINT, RELEASE SAVEPOINT)
        (Serialization uses already-prefetched request.user.profile with 0 additional queries).
        """
        url = f"{reverse('gyms_v1:gym-admin-logs-list')}?gym_id={perf_gym.id}"
        payload = {
            "action": "Updated page information",
            "action_type": AdminLogActionType.UPDATE_PAGE_INFO,
            "category": AdminLogCategory.GYM_PROFILE,
            "details": "Changed gym business hours",
        }

        with django_assert_num_queries(5):
            resp = auth_client.post(url, payload, format="json")
            assert resp.status_code == status.HTTP_201_CREATED
            assert resp.json()["action"] == "Updated page information"

    def test_export_csv_query_budget(
        self, auth_client, perf_gym, populated_logs, django_assert_num_queries
    ):
        """
        GET /api/v1/gyms/logs/admin/export/?format=csv
        Memory-efficient iterator query budget: Exactly 3 queries
        1. FastJWT auth + profile
        2. resolve_gym_context
        3. Chunked iterator stream with only() projections and select_related('actor')
        """
        url = f"{reverse('gyms_v1:gym-admin-logs-export')}?gym_id={perf_gym.id}&format=csv"

        with django_assert_num_queries(3):
            resp = auth_client.get(url)
            assert resp.status_code == status.HTTP_200_OK
            assert "text/csv" in resp["Content-Type"]
            lines = resp.content.decode("utf-8").strip().split("\n")
            assert len(lines) == 61  # Header + 60 logs

    # =========================================================================
    # 2. RESPONSE TIME LATENCY BENCHMARKS (p50 & p95 < 200 ms)
    # =========================================================================

    def test_response_time_latency_benchmark(self, auth_client, perf_gym, populated_logs):
        """
        Measures p50 and p95 latency over 25 consecutive requests for standard read endpoints.
        Target: p95 response time < 200 ms (< 400 ms on shared CI runners).
        """
        import os

        is_ci = bool(os.environ.get("CI"))
        target_p95 = 400.0 if is_ci else 200.0
        target_p50 = 200.0 if is_ci else 100.0

        endpoints = [
            ("List Admin Logs", f"{reverse('gyms_v1:gym-admin-logs-list')}?gym_id={perf_gym.id}&page=1&page_size=20"),
            ("Admin Logs Metrics", f"{reverse('gyms_v1:gym-admin-logs-metrics')}?gym_id={perf_gym.id}"),
            ("Admin Log Detail", f"{reverse('gyms_v1:gym-admin-log-detail', kwargs={'log_id': populated_logs[0].id})}?gym_id={perf_gym.id}"),
            ("Admin Log Action Types", reverse("gyms_v1:gym-admin-logs-actions")),
        ]

        iterations = 25

        for name, url in endpoints:
            # Warm-up request to eliminate cold-start routing/middleware overhead
            auth_client.get(url)

            latencies = []
            for _ in range(iterations):
                start = time.perf_counter()
                resp = auth_client.get(url)
                duration_ms = (time.perf_counter() - start) * 1000.0
                assert resp.status_code == status.HTTP_200_OK
                latencies.append(duration_ms)

            latencies.sort()
            p50 = latencies[int((len(latencies) - 1) * 0.50)]
            p95 = latencies[int((len(latencies) - 1) * 0.95)]

            print(f"\n[BENCHMARK] {name}: p50 = {p50:.2f} ms, p95 = {p95:.2f} ms (Target < {target_p95:.0f} ms)")

            # Assert p95 response time is strictly below target
            assert p95 < target_p95, f"{name} p95 latency {p95:.2f} ms exceeded {target_p95:.0f} ms target!"
            assert p50 < target_p50, f"{name} p50 latency {p50:.2f} ms exceeded {target_p50:.0f} ms target!"
