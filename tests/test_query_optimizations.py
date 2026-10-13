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

    # 2. GET /me/ endpoint with FastJWTAuthentication
    # Expected queries:
    # 1. FastJWT: User select_related profile
    # 2. stream_accessible_gyms: owned gyms
    # 3. stream_accessible_gyms: staff assignments
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    with django_assert_num_queries(3):
        res = client.get(reverse("me"))
        assert res.status_code == 200
        assert res.json()["user"]["profile"]["city"] == "Chittagong"


@pytest.mark.django_db
def test_gym_overview_query_optimization(django_assert_num_queries):
    """
    Verify get_gym_overview and GymDetailSerializer use select_related,
    prefetch_related, and Count annotations to eliminate N+1 queries.
    """
    from apps.gyms.services import create_gym, add_gallery_item
    from apps.gyms.selectors import get_gym_overview
    from apps.gyms.rest_api.v1.serializers import GymDetailSerializer

    owner = User.objects.create_user(
        email="gym.owner.opt@manygym.com",
        password="Password123!",
        first_name="Opt",
        last_name="Owner",
        is_verified=True,
    )
    gym = create_gym(owner_user=owner, name="Optimized Gym", city="Austin")
    add_gallery_item(gym, media_url="https://cdn.example.com/img1.jpg")
    add_gallery_item(gym, media_url="https://cdn.example.com/img2.jpg")

    # Fetching overview with annotations & prefetched primary location
    # Expect: 1 query for Gym + owner + Count annotations, 1 query for prefetched locations
    with django_assert_num_queries(2):
        gym_loaded = get_gym_overview(str(gym.id))
        data = GymDetailSerializer(gym_loaded).data
        assert data["opening_hours_count"] == 7
        assert data["gallery_count"] == 2
        assert data["location"]["city"] is not None


@pytest.mark.django_db
def test_amenities_stream_and_aggregations():
    """
    Verify get_gym_configured_amenities uses generator streaming, select_related,
    and single SQL count aggregation.
    """
    from apps.amenities.models import AmenityCatalog, GymAmenity
    from apps.amenities.services import seed_amenity_catalog, sync_gym_amenities
    from apps.amenities.selectors import get_gym_configured_amenities, stream_gym_configured_amenities
    from apps.gyms.services import create_gym

    seed_amenity_catalog()
    owner = User.objects.create_user(
        email="amenity.opt@manygym.com",
        password="Password123!",
        first_name="Amenity",
        last_name="Opt",
        is_verified=True,
    )
    gym = create_gym(owner_user=owner, name="Amenity Fast Gym")

    items = list(AmenityCatalog.objects.all()[:4])
    sync_gym_amenities(
        gym=gym,
        free_amenity_ids=[str(items[0].id), str(items[1].id)],
        paid_amenities=[
            {"amenity_id": str(items[2].id), "default_price": "10.00"},
            {"amenity_id": str(items[3].id), "default_price": "20.00"},
        ],
    )

    # 1. Verify stream generator
    stream_gen = stream_gym_configured_amenities(str(gym.id))
    assert isinstance(stream_gen, types.GeneratorType)
    streamed_items = list(stream_gen)
    assert len(streamed_items) == 4

    # 2. Verify aggregated result
    configured = get_gym_configured_amenities(str(gym.id))
    assert configured["total_count"] == 4
    assert len(configured["free_amenities"]) == 2
    assert len(configured["paid_amenities"]) == 2


@pytest.mark.django_db
def test_user_gym_scopes_single_query(django_assert_num_queries):
    """
    Verify get_user_gym_scopes executes in exactly ONE SQL query across staff assignments,
    roles, and permissions using joins instead of iterating in Python.
    """
    owner = User.objects.create_user(
        email="scope.owner@manygym.com",
        password="Password123!",
        first_name="Scope",
        last_name="Owner",
        is_verified=True,
    )
    gym = Gym.objects.create(owner_user=owner, name="Scope Gym")

    staff_user = User.objects.create_user(
        email="staff.user@manygym.com",
        password="Password123!",
        first_name="Staff",
        last_name="Member",
        is_verified=True,
    )

    trainer_role = Role.objects.get(slug="trainer")
    GymStaffAssignment.objects.create(
        user=staff_user,
        gym=gym,
        role=trainer_role,
        status=StaffStatus.ACTIVE,
    )

    # Must execute exactly 1 query with DISTINCT values_list join
    with django_assert_num_queries(1):
        scopes = get_user_gym_scopes(staff_user, gym)
        assert isinstance(scopes, list)
        assert len(scopes) > 0
        assert "members:read" in scopes


@pytest.mark.django_db
def test_gym_selectors_field_projections(django_assert_num_queries):
    """
    Verify get_gym_location, get_opening_hours, and list_gallery_items execute
    targeted queries with field projections (.only).
    """
    from apps.gyms.services import create_gym, add_gallery_item
    from apps.gyms.selectors import get_gym_location, get_opening_hours, list_gallery_items
    from common.enums import GalleryCategoryEnum

    owner = User.objects.create_user(
        email="projections@manygym.com",
        password="Password123!",
        first_name="Proj",
        last_name="User",
        is_verified=True,
    )
    gym = create_gym(owner_user=owner, name="Projection Gym", city="Dhaka")
    add_gallery_item(gym, media_url="https://cdn.example.com/pic1.jpg", category=GalleryCategoryEnum.EQUIPMENT)
    add_gallery_item(gym, media_url="https://cdn.example.com/pic2.jpg", category=GalleryCategoryEnum.WORKOUT_AREAS)

    # 1. get_gym_location executes exactly 1 query
    with django_assert_num_queries(1):
        loc = get_gym_location(str(gym.id))
        assert loc is not None
        assert loc.city == "Dhaka"
        assert loc.is_primary is True

    # 2. get_opening_hours executes exactly 1 query
    with django_assert_num_queries(1):
        hours = list(get_opening_hours(str(gym.id)))
        assert len(hours) == 7

    # 3. list_gallery_items executes exactly 1 query
    with django_assert_num_queries(1):
        items = list(list_gallery_items(str(gym.id)))
        assert len(items) == 2

    # 4. list_gallery_items with category executes exactly 1 query
    with django_assert_num_queries(1):
        filtered_items = list(list_gallery_items(str(gym.id), category=GalleryCategoryEnum.EQUIPMENT))
        assert len(filtered_items) == 1
        assert filtered_items[0].category == GalleryCategoryEnum.EQUIPMENT


@pytest.mark.django_db
def test_permissions_list_endpoint_query_count(django_assert_num_queries):
    """
    Verify GET /api/v1/access-control/permissions/ executes in exactly 2 queries:
    1. FastJWT auth (user + profile)
    2. Single streaming permission fetch
    """
    user = User.objects.create_user(
        email="perm.tester@manygym.com",
        password="Password123!",
        first_name="Perm",
        last_name="Tester",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    tokens = issue_context_token(user)

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    with django_assert_num_queries(2):
        res = client.get(reverse("permissions-list"))
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, dict)
        assert len(data) > 0


@pytest.mark.django_db
def test_switch_context_query_efficiency(django_assert_num_queries):
    """
    Verify POST /api/v1/auth/switch-context/ executes with optimal query count:
    1. FastJWT user lookup
    2. Gym lookup (select_related owner)
    3. Distinct scopes values_list query
    4. AuthToken insert
    (Skips redundant staff assignment search since user is owner).
    """
    owner = User.objects.create_user(
        email="ctx.owner@manygym.com",
        password="Password123!",
        first_name="Ctx",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = Gym.objects.create(owner_user=owner, name="Context Gym")

    base_tokens = issue_context_token(owner)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {base_tokens['access']}")

    with django_assert_num_queries(4):
        res = client.post(
            reverse("switch-context"),
            {"context_type": TokenContextType.GYM, "gym_id": str(gym.id)},
        )
        assert res.status_code == 200
        assert res.json()["tokens"]["context_type"] == TokenContextType.GYM
        assert res.json()["tokens"]["gym_id"] == str(gym.id)



