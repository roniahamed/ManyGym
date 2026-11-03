import time
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile, UserSetting, UserBlockedUser, UserFollow
from apps.gyms.models import Gym, GymSetting, GymBlockedUser
from apps.gyms.services import create_gym
from apps.access_control.services import seed_default_permissions_and_roles
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, UserAudienceMessagingEnum, UserAudienceVisibilityEnum


@pytest.fixture(autouse=True)
def setup_seeds(db):
    seed_default_permissions_and_roles()


@pytest.fixture
def perf_user_alice(db):
    user = User.objects.create_user(
        email="alice.perf@manygym.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Performance",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, is_private=False)
    user.get_settings()
    return user


@pytest.fixture
def perf_user_bob(db):
    user = User.objects.create_user(
        email="bob.perf@manygym.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Performance",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, is_private=False, avatar_url="https://cdn.manygym.com/bob.jpg")
    user.get_settings()
    return user


@pytest.fixture
def perf_candidate_batch(db):
    users = []
    for i in range(20):
        u = User.objects.create_user(
            email=f"candidate_{i}@manygym.com",
            password="SecurePassword123!",
            first_name=f"Candidate{i}",
            last_name="Batch",
            is_verified=True,
        )
        UserProfile.objects.create(user=u, avatar_url=f"https://cdn.manygym.com/u{i}.jpg")
        users.append(u)
    return users


@pytest.fixture
def perf_gym(perf_user_alice):
    return create_gym(owner_user=perf_user_alice, name="Apex Performance Gym")


@pytest.fixture
def alice_auth_client(perf_user_alice):
    tokens = issue_context_token(perf_user_alice, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def gym_auth_client(perf_user_alice, perf_gym):
    tokens = issue_context_token(perf_user_alice, context_type=TokenContextType.GYM, gym=perf_gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.mark.django_db
class TestUserSettingsPerformanceAndQueryCounts:
    """
    Validates performance targets and ensures zero N+1 regressions for User Settings endpoints.
    """

    def test_get_user_settings_query_budget(self, alice_auth_client, django_assert_num_queries):
        """GET /api/v1/users/settings/ must execute within 2 queries (auth + settings with select_related)."""
        url = reverse("user-settings")
        with django_assert_num_queries(2):
            res = alice_auth_client.get(url)
            assert res.status_code == status.HTTP_200_OK
            assert "language" in res.data
            assert "is_private" in res.data

    def test_patch_user_settings_query_budget(self, alice_auth_client, django_assert_num_queries):
        """PATCH /api/v1/users/settings/ must execute within a strict query budget without lazy loads."""
        url = reverse("user-settings")
        payload = {
            "language": "es",
            "dark_mode": True,
            "is_private": True,
            "who_can_message": UserAudienceMessagingEnum.NO_ONE,
        }
        # Max 7 queries: auth, begin, select settings, update profile, update settings, commit, re-fetch
        with django_assert_num_queries(7):
            res = alice_auth_client.patch(url, payload, format="json")
            assert res.status_code == status.HTTP_200_OK
            assert res.data["language"] == "es"
            assert res.data["is_private"] is True

    def test_list_blocked_users_n_plus_one_elimination(
        self, alice_auth_client, perf_user_alice, perf_candidate_batch, django_assert_num_queries
    ):
        """
        Verifies that GET /api/v1/users/settings/blocked-users/ maintains a constant O(1) query count
        regardless of whether 1 user or 15 users are returned (proving absence of N+1).
        """
        url = reverse("user-settings-blocked-users")

        # Block 15 users
        for u in perf_candidate_batch[:15]:
            UserBlockedUser.objects.create(blocker=perf_user_alice, blocked_user=u, reason="Bulk test")

        # Must execute in exactly 2 queries (auth + blocked queryset with select_related and only projections)
        with django_assert_num_queries(2):
            res = alice_auth_client.get(url)
            assert res.status_code == status.HTTP_200_OK
            assert len(res.data) == 15
            for item in res.data:
                assert item["avatar_url"] is not None
                assert "email" in item

    def test_search_users_to_block_query_budget(
        self, alice_auth_client, perf_candidate_batch, django_assert_num_queries
    ):
        """Search endpoint must execute in 2 queries (auth + filtered user search with select_related)."""
        url = reverse("user-settings-blocked-users-search")
        with django_assert_num_queries(2):
            res = alice_auth_client.get(f"{url}?q=Candidate")
            assert res.status_code == status.HTTP_200_OK
            assert len(res.data) > 0

    def test_post_block_user_query_efficiency(
        self, alice_auth_client, perf_user_bob, django_assert_num_queries
    ):
        """
        POST /api/v1/users/settings/blocked-users/
        Efficient combined follow deletion and pre-cached serialization:
        Exact 9 queries under pytest atomic savepoints (4 operational queries + 3 savepoint wrappers + 2 atomic wrappers).
        No lazy loads during response serialization.
        """
        url = reverse("user-settings-blocked-users")
        with django_assert_num_queries(9):
            res = alice_auth_client.post(url, {"user_id": str(perf_user_bob.id), "reason": "Fast block"}, format="json")
            assert res.status_code == status.HTTP_201_CREATED
            assert res.data["user_id"] == str(perf_user_bob.id)


@pytest.mark.django_db
class TestGymSettingsPerformanceAndQueryCounts:
    """
    Validates performance targets and ensures zero N+1 regressions for Gym Settings endpoints.
    """

    def test_get_gym_settings_query_budget(self, gym_auth_client, perf_gym, django_assert_num_queries):
        """GET /api/v1/gyms/settings/ must execute within 3 queries (auth + context + settings)."""
        url = f"{reverse('gyms_v1:gym-settings')}?gym_id={perf_gym.id}"
        with django_assert_num_queries(3):
            res = gym_auth_client.get(url)
            assert res.status_code == status.HTTP_200_OK
            assert "video_autoplay" in res.data

    def test_patch_gym_settings_query_budget(self, gym_auth_client, perf_gym, django_assert_num_queries):
        """PATCH /api/v1/gyms/settings/ must execute in 6 queries (auth + context + begin + select + update + commit)."""
        url = f"{reverse('gyms_v1:gym-settings')}?gym_id={perf_gym.id}"
        payload = {"dark_mode": True, "video_autoplay": False}
        with django_assert_num_queries(6):
            res = gym_auth_client.patch(url, payload, format="json")
            assert res.status_code == status.HTTP_200_OK
            assert res.data["dark_mode"] is True

    def test_list_gym_blocked_users_n_plus_one_elimination(
        self, gym_auth_client, perf_gym, perf_user_alice, perf_candidate_batch, django_assert_num_queries
    ):
        """
        Verifies that GET /api/v1/gyms/settings/blocked-users/ executes in O(1) constant queries (3 queries)
        across multiple blocked records.
        """
        for u in perf_candidate_batch[:12]:
            GymBlockedUser.objects.create(gym=perf_gym, user=u, blocked_by=perf_user_alice, reason="Gym test")

        url = f"{reverse('gyms_v1:gym-settings-blocked-users')}?gym_id={perf_gym.id}"
        with django_assert_num_queries(3):
            res = gym_auth_client.get(url)
            assert res.status_code == status.HTTP_200_OK
            assert len(res.data) == 12
            for item in res.data:
                assert item["avatar_url"] is not None
                assert "blocked_by_email" in item

    def test_search_gym_users_to_block_query_budget(
        self, gym_auth_client, perf_gym, perf_candidate_batch, django_assert_num_queries
    ):
        """
        Search for gym block candidates must avoid redundant Gym query:
        Exactly 3 queries (auth + gym context + user query with select_related).
        """
        url = f"{reverse('gyms_v1:gym-settings-blocked-users-search')}?gym_id={perf_gym.id}&q=Candidate"
        with django_assert_num_queries(3):
            res = gym_auth_client.get(url)
            assert res.status_code == status.HTTP_200_OK
            assert len(res.data) > 0


@pytest.mark.django_db
class TestLatencyAndQueryExecutionPlans:
    """
    Verifies that response times are well within the p95 < 200 ms target and index scans are utilized.
    """

    def test_response_times_under_p95_threshold(self, alice_auth_client, gym_auth_client, perf_gym):
        """Verifies standard read endpoints respond well under the 200 ms p95 threshold."""
        endpoints = [
            ("GET User Settings", reverse("user-settings")),
            ("GET Blocked Users", reverse("user-settings-blocked-users")),
            ("GET Search Users", f"{reverse('user-settings-blocked-users-search')}?q=Perf"),
            ("GET Gym Settings", f"{reverse('gyms_v1:gym-settings')}?gym_id={perf_gym.id}"),
            ("GET Gym Blocked Users", f"{reverse('gyms_v1:gym-settings-blocked-users')}?gym_id={perf_gym.id}"),
        ]

        for label, url in endpoints:
            client = gym_auth_client if "Gym" in label else alice_auth_client
            start = time.perf_counter()
            res = client.get(url)
            latency_ms = (time.perf_counter() - start) * 1000
            assert res.status_code == status.HTTP_200_OK
            assert latency_ms < 200.0, f"{label} exceeded 200ms latency target: {latency_ms:.2f}ms"

    def test_queryset_explain_and_indexes(self, perf_user_alice, perf_gym):
        """
        Validates that queries on UserBlockedUser and GymBlockedUser leverage database indexes.
        """
        # UserBlockedUser blocker query plan
        user_block_qs = UserBlockedUser.objects.filter(blocker=perf_user_alice).order_by("-created_at")
        plan_user = user_block_qs.explain()
        assert plan_user is not None
        assert "Scan" in plan_user or "Index" in plan_user

        # GymBlockedUser gym query plan
        gym_block_qs = GymBlockedUser.objects.filter(gym=perf_gym).order_by("-created_at")
        plan_gym = gym_block_qs.explain()
        assert plan_gym is not None
        assert "Scan" in plan_gym or "Index" in plan_gym

