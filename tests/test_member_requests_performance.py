import time
import uuid
from decimal import Decimal
import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym
from apps.gyms.services import create_gym
from apps.members.models import MemberRequest, Member
from apps.memberships.models import MembershipPlan
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    MemberRequestStatus,
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
)


def make_client(user):
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def owner_user(db):
    user = User.objects.create_user(
        email=f"owner_{uuid.uuid4().hex[:8]}@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    return user


@pytest.fixture
def test_gym(owner_user):
    return create_gym(owner_user=owner_user, name="Performance Gym")


@pytest.fixture
def plan(test_gym):
    return MembershipPlan.objects.create(
        gym=test_gym,
        name="Performance Plan",
        price=Decimal("99.00"),
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )


@pytest.mark.django_db
class TestMemberRequestsPerformance:

    def test_member_requests_list_n_plus_one_elimination(self, test_gym, owner_user, plan):
        """
        Validates that querying member requests does not suffer from N+1 user/profile lookups.
        Query count with 5 requests vs 25 requests must remain O(1) constant.
        """
        client = make_client(owner_user)

        # 1. Create initial 5 requests with users
        initial_users = [
            User(
                email=f"req_user_init_{i}_{uuid.uuid4().hex[:6]}@example.com",
                first_name=f"User{i}",
                last_name=f"Init{i}",
                is_verified=True,
            )
            for i in range(5)
        ]
        User.objects.bulk_create(initial_users)
        saved_initial = list(User.objects.filter(email__startswith="req_user_init_"))
        UserProfile.objects.bulk_create([UserProfile(user=u, avatar_url="https://example.com/p.jpg") for u in saved_initial])
        MemberRequest.objects.bulk_create([
            MemberRequest(gym=test_gym, user=u, interested_plan=plan, notes="Initial note")
            for u in saved_initial
        ])

        list_url = f"{reverse('member-request-list')}?gym_id={test_gym.id}&page_size=30"

        with CaptureQueriesContext(connection) as ctx_5:
            res_5 = client.get(list_url)
            assert res_5.status_code == status.HTTP_200_OK
            assert res_5.data["count"] == 5

        queries_5 = len(ctx_5.captured_queries)

        # 2. Add 20 more requests (5x scale)
        more_users = [
            User(
                email=f"req_user_scale_{i}_{uuid.uuid4().hex[:6]}@example.com",
                first_name=f"Scale{i}",
                last_name=f"User{i}",
                is_verified=True,
            )
            for i in range(20)
        ]
        User.objects.bulk_create(more_users)
        saved_scale = list(User.objects.filter(email__startswith="req_user_scale_"))
        UserProfile.objects.bulk_create([UserProfile(user=u, avatar_url="https://example.com/scale.jpg") for u in saved_scale])
        MemberRequest.objects.bulk_create([
            MemberRequest(gym=test_gym, user=u, interested_plan=plan, notes="Scale note")
            for u in saved_scale
        ])

        with CaptureQueriesContext(connection) as ctx_25:
            res_25 = client.get(list_url)
            assert res_25.status_code == status.HTTP_200_OK
            assert res_25.data["count"] == 25

        queries_25 = len(ctx_25.captured_queries)

        print(f"\n[BENCHMARK] List Member Requests: 5 items={queries_5} queries, 25 items={queries_25} queries")
        for q in ctx_25.captured_queries:
            print(f"  SQL: {q['sql'][:120]}... [{q['time']}s]")

        # N+1 invariant: queries_25 must equal queries_5 (O(1) complexity)
        assert queries_25 == queries_5, f"N+1 query detected! Expected constant queries ({queries_5}), got {queries_25}."
        # Upper bound: list endpoint must execute <= 4 queries (auth user, gym resolution, pagination count, records fetch)
        assert queries_25 <= 4, f"Too many queries for list endpoint: {queries_25}"

    def test_member_requests_list_response_time_benchmark(self, test_gym, owner_user):
        """
        Benchmarks response time over multiple iterations to ensure p95 < 200ms under test load.
        """
        client = make_client(owner_user)
        list_url = f"{reverse('member-request-list')}?gym_id={test_gym.id}&page_size=20"

        latencies = []
        # Warmup
        client.get(list_url)

        for _ in range(15):
            start = time.perf_counter()
            res = client.get(list_url)
            duration_ms = (time.perf_counter() - start) * 1000.0
            assert res.status_code == status.HTTP_200_OK
            latencies.append(duration_ms)

        import os

        is_ci = bool(os.environ.get("CI"))
        target_p95 = 400.0 if is_ci else 200.0

        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int((len(latencies) - 1) * 0.95)]

        print(f"\n[BENCHMARK] Member Requests List Latency: p50={p50:.2f}ms, p95={p95:.2f}ms")
        assert p95 < target_p95, f"p95 latency {p95:.2f}ms exceeded {target_p95:.0f}ms target."

    def test_member_request_detail_query_count(self, test_gym, owner_user, plan):
        """
        Detail endpoint should fetch request, gym, user, and profile with minimum DB hits (<= 2).
        """
        applicant = User.objects.create_user(
            email="single_applicant@example.com",
            password="SecurePassword123!",
            first_name="Single",
            last_name="Applicant",
            is_verified=True,
        )
        UserProfile.objects.create(user=applicant)
        req = MemberRequest.objects.create(
            gym=test_gym,
            user=applicant,
            interested_plan=plan,
            notes="Detail test note",
        )

        client = make_client(owner_user)
        url = reverse("member-request-detail", kwargs={"request_id": req.id})

        with CaptureQueriesContext(connection) as ctx:
            res = client.get(f"{url}?gym_id={test_gym.id}")
            assert res.status_code == status.HTTP_200_OK
            assert res.data["id"] == str(req.id)

        queries_count = len(ctx.captured_queries)
        print(f"\n[BENCHMARK] Member Request Detail Queries: {queries_count}")
        for q in ctx.captured_queries:
            print(f"  SQL: {q['sql'][:120]}... [{q['time']}s]")

        assert queries_count <= 2, f"Expected <= 2 queries for detail, got {queries_count}"

    def test_member_joining_request_status_query_count(self, test_gym, plan):
        """
        Public status check for a user against a gym should execute cleanly with minimal queries.
        """
        user = User.objects.create_user(
            email="status_user@example.com",
            password="SecurePassword123!",
            first_name="Status",
            last_name="Tester",
            is_verified=True,
        )
        UserProfile.objects.create(user=user)
        client = make_client(user)
        url = reverse("gyms_v1:gym-join-request", kwargs={"gym_id": test_gym.id})

        with CaptureQueriesContext(connection) as ctx:
            res = client.get(url)
            assert res.status_code == status.HTTP_200_OK
            assert res.data["can_send_request"] is True

        queries_count = len(ctx.captured_queries)
        print(f"\n[BENCHMARK] Member Request Status Queries: {queries_count}")
        for q in ctx.captured_queries:
            print(f"  SQL: {q['sql'][:120]}... [{q['time']}s]")
        # 1 user auth + 1 gym & settings + 1 blocked check + 1 member check + 1 pending req check <= 5
        assert queries_count <= 5, f"Expected <= 5 queries, got {queries_count}"

    def test_member_request_accept_query_efficiency(self, test_gym, owner_user, plan):
        """
        Accept endpoint must resolve the request, check conflicts in 1 query, create member and subscription efficiently.
        """
        applicant = User.objects.create_user(
            email="accept_perf_applicant@example.com",
            password="SecurePassword123!",
            first_name="Accept",
            last_name="Applicant",
            is_verified=True,
        )
        UserProfile.objects.create(user=applicant)
        req = MemberRequest.objects.create(
            gym=test_gym,
            user=applicant,
            interested_plan=plan,
            notes="Ready to accept",
        )

        client = make_client(owner_user)
        url = reverse("member-request-accept", kwargs={"request_id": req.id})
        payload = {
            "gym_id": str(test_gym.id),
            "plan_id": str(plan.id),
            "start_date": "2026-11-01",
            "initial_payment_amount": "99.00",
            "initial_payment_method": "cash",
        }

        with CaptureQueriesContext(connection) as ctx:
            res = client.post(url, data=payload, format="json")
            assert res.status_code == status.HTTP_201_CREATED

        queries_count = len(ctx.captured_queries)
        print(f"\n[BENCHMARK] Member Request Accept Queries: {queries_count}")
        for q in ctx.captured_queries:
            print(f"  SQL: {q['sql'][:120]}... [{q['time']}s]")

        # Ensure accept executes efficiently under a bounded query budget (including atomic savepoints/releases and admin logs)
        assert queries_count <= 40, f"Expected <= 40 queries, got {queries_count}"
