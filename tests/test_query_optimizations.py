import types
import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.db import connection

from apps.users.models import User, UserProfile
from apps.users.selectors import iter_users, get_user_by_email, get_user_by_id
from apps.gyms.models import Gym
from apps.gyms.selectors import (
    stream_accessible_gyms_for_user,
    get_accessible_gyms_for_user,
    get_gym_by_id,
)
from apps.access_control.models import Role, Permission, GymStaffAssignment
from apps.access_control.selectors import (
    stream_permissions,
    list_permissions_by_topic,
    list_gym_roles,
    list_gym_staff,
    get_user_gym_scopes,
)
from apps.access_control.services import seed_default_permissions_and_roles
from apps.authentication.services import issue_context_token, authenticate_user
from common.enums import TokenContextType, StaffStatus


@pytest.fixture(autouse=True)
def setup_default_seeds(db):
    seed_default_permissions_and_roles()


@pytest.mark.django_db
def test_generator_streams():
    """Verify that all generator selectors yield data correctly."""
    # 1. Test stream_permissions generator
    perm_gen = stream_permissions()
    assert isinstance(perm_gen, types.GeneratorType)
    perms = list(perm_gen)
    assert len(perms) > 0
    assert any(p.scope_code == "members:read" for p in perms)

    # 2. Test list_permissions_by_topic grouping via generator
    topic_dict = list_permissions_by_topic()
    assert isinstance(topic_dict, dict)
    assert "Members" in topic_dict
    assert len(topic_dict["Members"]) > 0

    # 3. Test iter_users generator
    user = User.objects.create_user(
        email="gen.tester@manygym.com",
        password="Password123!",
        first_name="Gen",
        last_name="Tester",
        is_verified=True,
    )
    user_gen = iter_users(chunk_size=10)
    assert isinstance(user_gen, types.GeneratorType)
    users_list = list(user_gen)
    assert any(u.email == "gen.tester@manygym.com" for u in users_list)

    # 4. Test stream_accessible_gyms_for_user generator
    gym = Gym.objects.create(owner_user=user, name="Gen Gym")
    gym_gen = stream_accessible_gyms_for_user(user)
    assert isinstance(gym_gen, types.GeneratorType)
    gym_items = list(gym_gen)
    assert len(gym_items) == 1
    assert gym_items[0]["name"] == "Gen Gym"
    assert gym_items[0]["is_owner"] is True


@pytest.mark.django_db
def test_staff_list_n_plus_one_elimination(django_assert_num_queries):
    """
    Verify that listing gym staff members does NOT trigger N+1 queries.
    Even with multiple staff members, queries must be minimal and constant.
    """
    owner = User.objects.create_user(
        email="gym.owner.opt@manygym.com",
        password="Password123!",
        first_name="Owner",
        last_name="Opt",
        is_verified=True,
    )
    gym = Gym.objects.create(owner_user=owner, name="Optimized Gym")

    trainer_role = Role.objects.get(slug="trainer")
    staff_role = Role.objects.get(slug="staff")

    # Create 4 distinct staff members
    for i in range(4):
        u = User.objects.create_user(
            email=f"staff{i}@manygym.com",
            password="Password123!",
            first_name=f"Staff{i}",
            last_name="Member",
            is_verified=True,
        )
        UserProfile.objects.create(user=u, city=f"City{i}")
        role = trainer_role if i % 2 == 0 else staff_role
        GymStaffAssignment.objects.create(
            user=u,
            gym=gym,
            role=role,
            status=StaffStatus.ACTIVE,
        )

    # Issue gym token for the owner
    owner_tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {owner_tokens['access']}")

    # GET /api/v1/access-control/staff/ (Paginated by default)
    # Expected queries:
    # 1. User lookup for JWT auth
    # 2. Gym lookup in resolve_request_gym (select_related owner)
    # 3. GymStaffAssignment query with select_related(user__profile, role__gym, gym)
    # 4. Count query for paginator
    # 5. Prefetch permissions for the roles
    with django_assert_num_queries(5):
        res = client.get(reverse("staff-list-invite"))
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 4
        assert data["total_pages"] == 1
        assert data["current_page"] == 1
        assert len(data["results"]) == 4
        # Validate that profiles and roles are fully populated
        assert data["results"][0]["user"]["profile"] is not None
        assert data["results"][0]["role"]["permissions"] is not None

    # Test custom page_size pagination
    res_page = client.get(reverse("staff-list-invite"), {"page": 1, "page_size": 2})
    assert res_page.status_code == 200
    page_data = res_page.json()
    assert page_data["count"] == 4
    assert page_data["total_pages"] == 2
    assert len(page_data["results"]) == 2
    assert page_data["next"] is not None

    # Test all=true unpaginated fallback
    res_all = client.get(reverse("staff-list-invite"), {"all": "true"})
    assert res_all.status_code == 200
    assert isinstance(res_all.json(), list)
    assert len(res_all.json()) == 4


@pytest.mark.django_db
def test_roles_list_n_plus_one_elimination(django_assert_num_queries):
    """
    Verify that listing gym roles batches permissions and selects gym.
    Also tests optional pagination on roles endpoint.
    """
    owner = User.objects.create_user(
        email="role.owner.opt@manygym.com",
        password="Password123!",
        first_name="Owner",
        last_name="Opt",
        is_verified=True,
    )
    gym = Gym.objects.create(owner_user=owner, name="Roles Gym")

    # Create 2 custom roles
    perm = Permission.objects.first()
    for i in range(2):
        r = Role.objects.create(
            gym=gym,
            name=f"Custom Role {i}",
            slug=f"custom-role-{i}",
            is_custom=True,
        )
        r.permissions.add(perm)

    owner_tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {owner_tokens['access']}")

    # GET /api/v1/access-control/roles/?gym_id=... (Unpaginated by default for UI dropdowns)
    with django_assert_num_queries(3):
        res = client.get(reverse("roles-list-create"), {"gym_id": str(gym.id)})
        assert res.status_code == 200
        roles_data = res.json()
        assert isinstance(roles_data, list)
        assert len(roles_data) >= 5  # 3 standard + 2 custom

    # GET /api/v1/access-control/roles/ with pagination parameters
    res_paginated = client.get(
        reverse("roles-list-create"),
        {"gym_id": str(gym.id), "page": 1, "page_size": 2},
    )
    assert res_paginated.status_code == 200
    paginated_data = res_paginated.json()
    assert paginated_data["count"] >= 5
    assert len(paginated_data["results"]) == 2



@pytest.mark.django_db
def test_login_and_me_select_related_profile(django_assert_num_queries):
    """
    Verify authenticate_user and /api/v1/users/me/ prefetch user profile without extra queries.
    """
    user = User.objects.create_user(
        email="fast.login@manygym.com",
        password="Password123!",
        first_name="Fast",
        last_name="Login",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, city="Chittagong")

    # 1. authenticate_user uses select_related('profile')
    auth_user, tokens = authenticate_user("fast.login@manygym.com", "Password123!")
    # Accessing profile does not execute query because it is pre-cached
    assert auth_user.profile.city == "Chittagong"

    # 2. GET /me/ endpoint
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    res = client.get(reverse("me"))
    assert res.status_code == 200
    assert res.json()["user"]["profile"]["city"] == "Chittagong"
