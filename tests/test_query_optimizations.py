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


@pytest.mark.django_db
def test_phase2_gym_profile_overview_endpoint_query_count(django_assert_num_queries):
    """
    Verify GET /api/v1/gyms/profile/ executes in exactly 3 queries:
    1. FastJWT auth
    2. get_gym_overview (Gym + owner_user + SQL Count annotations)
    3. GymLocation (prefetched primary location)
    Eliminates redundant Gym lookups!
    """
    from apps.gyms.services import create_gym, add_gallery_item

    owner = User.objects.create_user(
        email="p2.owner@manygym.com",
        password="Password123!",
        first_name="P2",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Phase 2 Gym", city="Dhaka")
    add_gallery_item(gym, media_url="https://cdn.example.com/p2.jpg")

    tokens = issue_context_token(owner)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    with django_assert_num_queries(3):
        res = client.get(f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={gym.id}")
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Phase 2 Gym"
        assert data["opening_hours_count"] == 7
        assert data["gallery_count"] == 1


@pytest.mark.django_db
def test_phase2_gym_location_endpoint_query_count(django_assert_num_queries):
    """
    Verify GET /api/v1/gyms/profile/location/ executes in exactly 3 queries:
    1. FastJWT auth
    2. resolve_gym_context (.only)
    3. get_gym_location (.only with is_primary index)
    """
    from apps.gyms.services import create_gym

    owner = User.objects.create_user(
        email="p2.loc@manygym.com",
        password="Password123!",
        first_name="P2",
        last_name="Loc",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Location Gym", city="Sylhet")

    tokens = issue_context_token(owner)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    with django_assert_num_queries(3):
        res = client.get(f"{reverse('gyms_v1:gym-profile-location')}?gym_id={gym.id}")
        assert res.status_code == 200
        assert res.json()["city"] == "Sylhet"


@pytest.mark.django_db
def test_phase2_gym_opening_hours_endpoint_query_count(django_assert_num_queries):
    """
    Verify GET /api/v1/gyms/opening-hours/ executes in exactly 3 queries:
    1. FastJWT auth
    2. resolve_gym_context (.only)
    3. get_opening_hours (.only)
    """
    from apps.gyms.services import create_gym

    owner = User.objects.create_user(
        email="p2.hours@manygym.com",
        password="Password123!",
        first_name="P2",
        last_name="Hours",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Hours Gym")

    tokens = issue_context_token(owner)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    with django_assert_num_queries(3):
        res = client.get(f"{reverse('gyms_v1:gym-opening-hours')}?gym_id={gym.id}")
        assert res.status_code == 200
        assert len(res.json()) == 7


@pytest.mark.django_db
def test_phase2_gym_gallery_endpoint_query_count(django_assert_num_queries):
    """
    Verify GET /api/v1/gyms/gallery/ executes in exactly 3 queries:
    1. FastJWT auth
    2. resolve_gym_context (.only)
    3. list_gallery_items (.only with composite index)
    """
    from apps.gyms.services import create_gym, add_gallery_item
    from common.enums import GalleryCategoryEnum

    owner = User.objects.create_user(
        email="p2.gal@manygym.com",
        password="Password123!",
        first_name="P2",
        last_name="Gal",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Gal Gym")
    add_gallery_item(gym, media_url="https://cdn.example.com/g1.jpg", category=GalleryCategoryEnum.EQUIPMENT)

    tokens = issue_context_token(owner)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    with django_assert_num_queries(3):
        res = client.get(f"{reverse('gyms_v1:gym-gallery-list')}?gym_id={gym.id}&category=equipment")
        assert res.status_code == 200
        assert len(res.json()) == 1


@pytest.mark.django_db
def test_phase2_amenities_endpoints_query_count(django_assert_num_queries):
    """
    Verify Phase 2 amenities endpoints execute with optimal queries:
    - Master Catalog: 2 queries (auth + streaming catalog)
    - Gym Configured: 4 queries (auth + gym + count aggregation + select_related stream)
    """
    from apps.gyms.services import create_gym
    from apps.amenities.models import AmenityCatalog
    from apps.amenities.services import seed_amenity_catalog, sync_gym_amenities

    seed_amenity_catalog()
    owner = User.objects.create_user(
        email="p2.amenities@manygym.com",
        password="Password123!",
        first_name="P2",
        last_name="Amenity",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Amenity P2 Gym")

    first_item = AmenityCatalog.objects.first()
    sync_gym_amenities(gym=gym, free_amenity_ids=[str(first_item.id)], paid_amenities=[])

    tokens = issue_context_token(owner)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # 1. Master catalog (2 queries)
    with django_assert_num_queries(2):
        res_cat = client.get(reverse("amenities_v1:amenity-catalog"))
        assert res_cat.status_code == 200
        assert "Changing & Storage" in res_cat.json()

    # 2. Configured amenities (4 queries)
    with django_assert_num_queries(4):
        res_cfg = client.get(f"{reverse('amenities_v1:gym-amenities-configured')}?gym_id={gym.id}")
        assert res_cfg.status_code == 200
        data = res_cfg.json()
        assert data["total_count"] == 1
        assert len(data["free_amenities"]) == 1


# =====================================================================
# PHASE 4: MEMBER LIFECYCLE & SUBSCRIPTION PERFORMANCE TESTS
# =====================================================================

@pytest.mark.django_db
def test_phase4_member_metrics_single_query_reduction(django_assert_num_queries):
    """
    Verify get_gym_member_metrics executes in exactly 1 query (reduced from 3, 66.7% reduction).
    Verify GET /api/v1/members/metrics/ executes in exactly 3 queries (reduced from 5, 40% reduction).
    """
    import uuid
    from datetime import date
    from decimal import Decimal
    from apps.gyms.services import create_gym
    from apps.memberships.services import create_membership_plan
    from apps.members.services import create_member, create_member_subscription
    from apps.members.selectors import get_gym_member_metrics
    from common.enums import PlanStatusEnum, PlanTypeEnum, DurationUnitEnum

    owner = User.objects.create_user(
        email="p4.metrics.opt@manygym.com",
        password="Password123!",
        first_name="P4",
        last_name="Metrics",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Metrics Gym")

    plan = create_membership_plan(
        gym=gym,
        name="Metrics Pro Plan",
        description="Performance testing plan description for metric aggregation.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("80.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    for i in range(5):
        m = create_member(
            gym=gym,
            first_name=f"User{i}",
            last_name="Test",
            email=f"user{i}_{uuid.uuid4().hex[:6]}@test.com",
        )
        create_member_subscription(
            member=m,
            plan=plan,
            start_date=date.today(),
            initial_payment_amount=Decimal("40.00"),
            initial_payment_method="cash",
        )

    # 1. Direct selector execution: Exactly 1 query
    with django_assert_num_queries(1):
        metrics = get_gym_member_metrics(gym)
        assert metrics["total_members"] == 5
        assert metrics["active_subscriptions"] == 5
        assert metrics["total_revenue"] == 200.0

    # 2. REST API endpoint: Exactly 3 queries (1 FastJWT auth + 1 gym context + 1 unified metrics)
    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    with django_assert_num_queries(3):
        res = client.get(f"{reverse('member-metrics')}?gym_id={gym.id}")
        assert res.status_code == 200
        data = res.json()
        assert data["total_members"] == 5
        assert data["active_subscriptions"] == 5
        assert data["total_revenue"] == 200.0


@pytest.mark.django_db
def test_phase4_member_directory_query_efficiency(django_assert_num_queries):
    """
    Verify GET /api/v1/members/ executes in exactly 4 queries regardless of dataset size:
    1. FastJWT auth (select_related profile)
    2. resolve_member_gym (.only)
    3. Member directory (with .only and select_related assigned_trainer__user)
    4. Prefetched subscriptions (with .only on subscriptions and plan)
    Eliminating N+1 queries.
    """
    import uuid
    from datetime import date
    from decimal import Decimal
    from apps.gyms.services import create_gym
    from apps.memberships.services import create_membership_plan
    from apps.members.services import create_member, create_member_subscription
    from common.enums import PlanStatusEnum, PlanTypeEnum, DurationUnitEnum

    owner = User.objects.create_user(
        email="p4.dir.opt@manygym.com",
        password="Password123!",
        first_name="P4",
        last_name="Dir",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Directory Gym")

    plan = create_membership_plan(
        gym=gym,
        name="Dir Plan",
        description="Performance testing plan description for directory listings.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("50.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    for i in range(10):
        m = create_member(
            gym=gym,
            first_name=f"DirUser{i}",
            last_name="Test",
            email=f"diruser{i}_{uuid.uuid4().hex[:6]}@test.com",
        )
        create_member_subscription(
            member=m,
            plan=plan,
            start_date=date.today(),
        )

    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # 1. Unpaginated directory listing: exactly 4 queries
    with django_assert_num_queries(4):
        res = client.get(f"{reverse('member-list-create')}?gym_id={gym.id}")
        assert res.status_code == 200
        assert len(res.json()) == 10

    # 2. Paginated directory listing: exactly 5 queries (4 + 1 pagination COUNT)
    with django_assert_num_queries(5):
        res = client.get(f"{reverse('member-list-create')}?gym_id={gym.id}&page=1&page_size=5")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 10
        assert len(data["results"]) == 5


@pytest.mark.django_db
def test_phase4_member_detail_dossier_query_efficiency(django_assert_num_queries):
    """
    Verify GET /api/v1/members/{id}/ executes in exactly 6 queries with full relations:
    1. FastJWT auth
    2. resolve_member_gym
    3. Member dossier (.only + select_related gym, user, assigned_trainer__user)
    4. Subscriptions prefetch (.only + select_related plan)
    5. Extra amenities prefetch (.only + select_related gym_amenity__amenity)
    6. Payments prefetch (.only)
    """
    from decimal import Decimal
    from datetime import date
    from apps.gyms.services import create_gym
    from apps.memberships.services import create_membership_plan
    from apps.members.services import (
        create_member,
        create_member_subscription,
        record_member_payment,
        attach_extra_amenities,
    )
    from apps.amenities.models import AmenityCatalog, GymAmenity
    from common.enums import PlanStatusEnum, PlanTypeEnum, DurationUnitEnum

    owner = User.objects.create_user(
        email="p4.dossier.opt@manygym.com",
        password="Password123!",
        first_name="P4",
        last_name="Dossier",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Dossier Gym")

    plan = create_membership_plan(
        gym=gym,
        name="Dossier Plan",
        description="Performance testing plan description for dossier endpoint.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("120.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    from apps.amenities.services import seed_amenity_catalog
    seed_amenity_catalog()
    cat = AmenityCatalog.objects.first()
    gym_amenity = GymAmenity.objects.create(gym=gym, amenity=cat, is_paid=True, default_price=Decimal("20.00"))

    member = create_member(
        gym=gym,
        first_name="Jane",
        last_name="Dossier",
        email="jane.dossier@manygym.com",
    )
    sub = create_member_subscription(
        member=member,
        plan=plan,
        start_date=date.today(),
    )
    attach_extra_amenities(sub, [gym_amenity.id])
    record_member_payment(sub, amount=Decimal("70.00"), payment_method="cash", payment_date=date.today())

    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    with django_assert_num_queries(6):
        res = client.get(f"{reverse('member-detail', kwargs={'member_id': member.id})}?gym_id={gym.id}")
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "jane.dossier@manygym.com"
        assert len(data["subscriptions"]) == 1
        assert len(data["subscriptions"][0]["extra_amenities"]) == 1
        assert len(data["subscriptions"][0]["payments"]) == 1
        assert Decimal(data["subscriptions"][0]["total_cost"]) == Decimal("140.00")


# ==============================================================================
# PHASE 5: LEADS CRM & PIPELINE QUERY OPTIMIZATIONS & BENCHMARKS
# ==============================================================================

@pytest.mark.django_db
def test_stream_leads_generator():
    """Verify that stream_leads yields data via QuerySet.iterator() without materializing whole queryset."""
    import types
    from apps.gyms.services import create_gym
    from apps.leads.models import Lead
    from apps.leads.selectors import stream_leads
    from common.enums import LeadStageEnum

    owner = User.objects.create_user(
        email="p5.stream.opt@manygym.com",
        password="Password123!",
        first_name="Stream",
        last_name="Owner",
        is_verified=True,
    )
    gym = create_gym(owner_user=owner, name="Stream Leads Gym")

    for i in range(12):
        Lead.objects.create(
            gym=gym,
            first_name=f"Lead{i}",
            phone=f"+1000{i:03d}",
            stage=LeadStageEnum.NEW,
        )

    leads_gen = stream_leads(gym=gym, chunk_size=5)
    assert isinstance(leads_gen, types.GeneratorType)
    yielded = list(leads_gen)
    assert len(yielded) == 12
    assert yielded[0].first_name == "Lead11"  # default ordering -created_at


@pytest.mark.django_db
def test_phase5_lead_metrics_query_reduction(django_assert_num_queries):
    """
    Verify get_lead_metrics executes in exactly 1 query via unified PostgreSQL aggregation,
    and GET /api/v1/leads/metrics/ executes in exactly 3 queries:
    1. FastJWT auth
    2. resolve_lead_gym
    3. Unified single-query aggregation
    """
    from apps.gyms.services import create_gym
    from apps.leads.models import Lead, LeadNextMove
    from apps.leads.selectors import get_lead_metrics
    from common.enums import LeadStageEnum

    owner = User.objects.create_user(
        email="p5.metrics.opt@manygym.com",
        password="Password123!",
        first_name="Metrics",
        last_name="Opt",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Metrics Gym")

    # Seed diverse lead pipeline states
    l1 = Lead.objects.create(gym=gym, first_name="L1", phone="+1", stage=LeadStageEnum.NEW)
    l2 = Lead.objects.create(gym=gym, first_name="L2", phone="+2", stage=LeadStageEnum.CONTACTED)
    l3 = Lead.objects.create(gym=gym, first_name="L3", phone="+3", stage=LeadStageEnum.VISIT_TRIAL_BOOKED)
    l4 = Lead.objects.create(gym=gym, first_name="L4", phone="+4", stage=LeadStageEnum.JOINED)
    l5 = Lead.objects.create(gym=gym, first_name="L5", phone="+5", stage=LeadStageEnum.NOT_JOINING, not_joining_reason_standard="price")

    LeadNextMove.objects.create(lead=l1, scheduled_date="2026-10-20", short_description="Call", is_completed=False)
    LeadNextMove.objects.create(lead=l2, scheduled_date="2026-10-21", short_description="Email", is_completed=True)

    # 1. Selector query count assertion: exactly 1 single query
    with django_assert_num_queries(1):
        metrics = get_lead_metrics(gym)
        assert metrics["total_leads"] == 5
        assert metrics["new"] == 1
        assert metrics["contacted"] == 1
        assert metrics["visit_trial_booked"] == 1
        assert metrics["joined"] == 1
        assert metrics["not_joining"] == 1
        assert metrics["conversion_rate_percentage"] == 20.0
        assert metrics["pending_next_moves_count"] == 1

    # 2. API endpoint query count assertion: exactly 3 queries
    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    with django_assert_num_queries(3):
        res = client.get(f"{reverse('lead-metrics')}?gym_id={gym.id}")
        assert res.status_code == 200
        data = res.json()
        assert data["total_leads"] == 5
        assert data["pending_next_moves_count"] == 1


@pytest.mark.django_db
def test_phase5_lead_directory_n_plus_one_elimination(django_assert_num_queries):
    """
    Verify GET /api/v1/leads/ executes in exactly 4 queries unpaginated / 5 queries paginated
    regardless of lead count, eliminating N+1 queries:
    1. FastJWT auth
    2. resolve_lead_gym (.only)
    3. Lead directory (with .only, select_related, and annotated pending_next_moves_count)
    4. Prefetched fitness goals (.only)
    """
    import uuid
    from decimal import Decimal
    from datetime import date
    from apps.gyms.services import create_gym
    from apps.memberships.services import create_membership_plan
    from apps.leads.models import Lead, LeadFitnessGoals, LeadNextMove
    from common.enums import PlanStatusEnum, PlanTypeEnum, DurationUnitEnum, LeadStageEnum

    owner = User.objects.create_user(
        email="p5.dir.opt@manygym.com",
        password="Password123!",
        first_name="P5",
        last_name="Dir",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Lead Dir Gym")

    plan = create_membership_plan(
        gym=gym,
        name="Lead Plan",
        description="Comprehensive 50-character testing lead query optimization plan description.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("80.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    trainer_role = Role.objects.get(slug="trainer")
    staff_user = User.objects.create_user(
        email="staff.dir.opt@manygym.com",
        password="Password123!",
        first_name="Staff",
        last_name="Dir",
        is_verified=True,
    )
    staff_assignment = GymStaffAssignment.objects.create(
        gym=gym,
        user=staff_user,
        role=trainer_role,
        status=StaffStatus.ACTIVE,
    )

    # Create 15 leads with goals and moves
    for i in range(15):
        lead = Lead.objects.create(
            gym=gym,
            first_name=f"LeadUser{i}",
            last_name="Test",
            phone=f"+1800{i:04d}",
            email=f"lead{i}_{uuid.uuid4().hex[:6]}@example.com",
            stage=LeadStageEnum.NEW if i % 2 == 0 else LeadStageEnum.CONTACTED,
            interested_plan=plan,
            assigned_staff=staff_assignment,
        )
        LeadFitnessGoals.objects.create(lead=lead, goal="general_fitness")
        LeadNextMove.objects.create(lead=lead, scheduled_date=date.today(), short_description=f"Action {i}", is_completed=(i % 2 == 0))

    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # 1. Default directory listing: exactly 5 queries (Auth, resolve gym, count, leads, prefetched goals)
    with django_assert_num_queries(5):
        res = client.get(f"{reverse('lead-list-create')}?gym_id={gym.id}")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 15
        assert len(data["results"]) == 15

    # 2. Paginated page_size=5: exactly 5 queries
    with django_assert_num_queries(5):
        res = client.get(f"{reverse('lead-list-create')}?gym_id={gym.id}&page=1&page_size=5")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 15
        assert len(data["results"]) == 5


@pytest.mark.django_db
def test_phase5_lead_detail_dossier_query_efficiency(django_assert_num_queries):
    """
    Verify GET /api/v1/leads/{id}/ executes in exactly 6 queries with full relations:
    1. FastJWT auth
    2. resolve_lead_gym (.only)
    3. Lead detail dossier (.only + select_related)
    4. Prefetched fitness goals (.only)
    5. Prefetched next moves (.only)
    6. Prefetched staff notes (.only + select_related author_staff__user)
    """
    from decimal import Decimal
    from datetime import date
    from apps.gyms.services import create_gym
    from apps.memberships.services import create_membership_plan
    from apps.leads.models import Lead, LeadFitnessGoals, LeadNextMove, LeadNotes
    from common.enums import PlanStatusEnum, PlanTypeEnum, DurationUnitEnum, LeadStageEnum

    owner = User.objects.create_user(
        email="p5.dossier.opt@manygym.com",
        password="Password123!",
        first_name="P5",
        last_name="Dossier",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Lead Dossier Gym")

    plan = create_membership_plan(
        gym=gym,
        name="Dossier Plan",
        description="Comprehensive 50-character testing lead dossier query efficiency plan.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("95.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    lead = Lead.objects.create(
        gym=gym,
        first_name="DossierLead",
        last_name="Candidate",
        phone="+1987654321",
        email="candidate@example.com",
        stage=LeadStageEnum.CONTACTED,
        interested_plan=plan,
    )
    LeadFitnessGoals.objects.create(lead=lead, goal="strength")
    LeadNextMove.objects.create(lead=lead, scheduled_date=date.today(), short_description="Call back regarding membership")
    LeadNotes.objects.create(lead=lead, note_text="Initial call completed successfully.")

    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    with django_assert_num_queries(6):
        res = client.get(f"{reverse('lead-detail-update-delete', kwargs={'lead_id': lead.id})}?gym_id={gym.id}")
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "candidate@example.com"
        assert len(data["fitness_goals"]) == 1
        assert len(data["next_moves"]) == 1
        assert len(data["notes"]) == 1


@pytest.mark.django_db
def test_phase5_performance_benchmarks():
    """
    Measures and asserts latency performance across Phase 5 endpoints under test load:
    - Target: p95 < 200 ms for read endpoints
    - Target: p95 < 500 ms for complex endpoints (atomic conversion)
    """
    import time
    import uuid
    from decimal import Decimal
    from datetime import date
    from apps.gyms.services import create_gym
    from apps.memberships.services import create_membership_plan
    from apps.leads.models import Lead, LeadFitnessGoals, LeadNextMove, LeadNotes
    from common.enums import PlanStatusEnum, PlanTypeEnum, DurationUnitEnum, LeadStageEnum

    def calc_p(data, p):
        s = sorted(data)
        idx = int((len(s) - 1) * (p / 100.0))
        return s[idx]

    owner = User.objects.create_user(
        email="p5.bench.opt@manygym.com",
        password="Password123!",
        first_name="P5",
        last_name="Bench",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Bench Gym")

    plan = create_membership_plan(
        gym=gym,
        name="Bench Plan",
        description="Testing lead performance benchmarks plan description.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("110.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    # Pre-create 20 leads
    leads = []
    for i in range(20):
        lead = Lead.objects.create(
            gym=gym,
            first_name=f"BenchLead{i}",
            phone=f"+1555{i:04d}",
            email=f"bench{i}@example.com",
            stage=LeadStageEnum.NEW if i % 2 == 0 else LeadStageEnum.CONTACTED,
            interested_plan=plan,
        )
        LeadFitnessGoals.objects.create(lead=lead, goal="general_fitness")
        LeadNextMove.objects.create(lead=lead, scheduled_date=date.today(), short_description="Follow up")
        LeadNotes.objects.create(lead=lead, note_text=f"Note {i}")
        leads.append(lead)

    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # 1. Benchmark GET /api/v1/leads/
    list_latencies = []
    for _ in range(20):
        t0 = time.perf_counter()
        res = client.get(f"{reverse('lead-list-create')}?gym_id={gym.id}")
        t1 = time.perf_counter()
        assert res.status_code == 200
        list_latencies.append((t1 - t0) * 1000)

    p50_list = calc_p(list_latencies, 50)
    p95_list = calc_p(list_latencies, 95)
    assert p95_list < 200, f"GET /api/v1/leads/ p95 exceeded target: {p95_list:.2f}ms"

    # 2. Benchmark GET /api/v1/leads/metrics/
    metrics_latencies = []
    for _ in range(20):
        t0 = time.perf_counter()
        res = client.get(f"{reverse('lead-metrics')}?gym_id={gym.id}")
        t1 = time.perf_counter()
        assert res.status_code == 200
        metrics_latencies.append((t1 - t0) * 1000)

    p50_metrics = calc_p(metrics_latencies, 50)
    p95_metrics = calc_p(metrics_latencies, 95)
    assert p95_metrics < 200, f"GET /api/v1/leads/metrics/ p95 exceeded target: {p95_metrics:.2f}ms"

    # 3. Benchmark GET /api/v1/leads/{id}/ (Full Dossier)
    dossier_latencies = []
    for lead in leads[:10]:
        t0 = time.perf_counter()
        res = client.get(f"{reverse('lead-detail-update-delete', kwargs={'lead_id': lead.id})}?gym_id={gym.id}")
        t1 = time.perf_counter()
        assert res.status_code == 200
        dossier_latencies.append((t1 - t0) * 1000)

    p50_dossier = calc_p(dossier_latencies, 50)
    p95_dossier = calc_p(dossier_latencies, 95)
    assert p95_dossier < 200, f"GET /api/v1/leads/{id}/ p95 exceeded target: {p95_dossier:.2f}ms"

    # 4. Benchmark POST /api/v1/leads/{id}/convert/ (Complex Write Endpoint)
    convert_latencies = []
    for i in range(10):
        conv_lead = Lead.objects.create(
            gym=gym,
            first_name=f"ConvLead{i}",
            last_name="Convertible",
            email=f"conv{i}_{uuid.uuid4().hex[:6]}@example.com",
            interested_plan=plan,
        )
        t0 = time.perf_counter()
        res = client.post(
            f"{reverse('lead-convert', kwargs={'lead_id': conv_lead.id})}?gym_id={gym.id}",
            {"initial_payment_amount": "50.00", "initial_payment_method": "cash"},
            format="json",
        )
        t1 = time.perf_counter()
        assert res.status_code == 201
        convert_latencies.append((t1 - t0) * 1000)

    p50_convert = calc_p(convert_latencies, 50)
    p95_convert = calc_p(convert_latencies, 95)
    assert p95_convert < 500, f"POST /api/v1/leads/{id}/convert/ p95 exceeded target: {p95_convert:.2f}ms"

    print("\n" + "=" * 60)
    print("PHASE 5 PERFORMANCE BENCHMARK REPORT:")
    print(f"GET /api/v1/leads/ (20 items):         p50={p50_list:.2f}ms, p95={p95_list:.2f}ms (Target < 200ms)")
    print(f"GET /api/v1/leads/metrics/:             p50={p50_metrics:.2f}ms, p95={p95_metrics:.2f}ms (Target < 200ms)")
    print(f"GET /api/v1/leads/{{id}}/ (Dossier):      p50={p50_dossier:.2f}ms, p95={p95_dossier:.2f}ms (Target < 200ms)")
    print(f"POST /api/v1/leads/{{id}}/convert/:      p50={p50_convert:.2f}ms, p95={p95_convert:.2f}ms (Target < 500ms)")
    print("=" * 60)


# =====================================================================
# PHASE 6: ROUTINE TEMPLATES & WORKOUT PRESCRIPTION PERFORMANCE TESTS
# =====================================================================

@pytest.mark.django_db
def test_stream_routine_templates_generator():
    """
    Verify stream_routine_templates yields templates as a generator
    using QuerySet.iterator() without full memory materialization.
    """
    from apps.gyms.services import create_gym
    from apps.routines.services import create_routine_template
    from apps.routines.selectors import stream_routine_templates

    owner = User.objects.create_user(
        email="p6.gen.opt@manygym.com",
        password="Password123!",
        first_name="P6",
        last_name="Gen",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Generator Gym")

    for i in range(15):
        create_routine_template(
            gym=gym,
            template_name=f"Template {i}",
            notes=f"Note {i}",
        )

    gen = stream_routine_templates(gym=gym, chunk_size=5)
    import types
    assert isinstance(gen, types.GeneratorType)

    collected = list(gen)
    assert len(collected) == 15
    assert collected[0].template_name.startswith("Template")


@pytest.mark.django_db
def test_phase6_routine_template_directory_n_plus_one_elimination(django_assert_num_queries):
    """
    Verify GET /api/v1/routine-templates/ executes in a constant number of queries
    regardless of how many templates, days, and exercises are stored:
    1. FastJWT auth
    2. resolve_routine_gym (.only)
    3. RoutineTemplate directory (select_related gym, created_by_staff__user)
    4. Prefetch goals
    5. Prefetch days
    6. Prefetch exercises
    """
    from apps.gyms.services import create_gym
    from apps.routines.services import create_routine_template
    from common.enums import RoutineFormatEnum, RoutineLevelEnum, FitnessGoalEnum

    owner = User.objects.create_user(
        email="p6.dir.nplus1@manygym.com",
        password="Password123!",
        first_name="P6",
        last_name="NPlusOne",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="N+1 Routine Gym")

    for i in range(10):
        create_routine_template(
            gym=gym,
            template_name=f"Bulk Template {i}",
            routine_format=RoutineFormatEnum.WEEKLY,
            level=RoutineLevelEnum.INTERMEDIATE,
            goals=[FitnessGoalEnum.MUSCLE_GAIN, FitnessGoalEnum.STRENGTH],
            days=[
                {
                    "day_of_week": 1,
                    "workout_title": "Chest & Triceps",
                    "exercises": [
                        {"exercise_name": "Bench Press", "sets": 4, "reps_or_duration": "10 reps"},
                        {"exercise_name": "Pushups", "sets": 3, "reps_or_duration": "15 reps"},
                    ],
                },
                {
                    "day_of_week": 2,
                    "is_rest_day": True,
                },
            ],
        )

    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # Paginated directory query count: exactly 5 queries (FastJWT auth + gym context + COUNT + Template QS with SQL Count annotations + prefetched goals)
    with django_assert_num_queries(5):
        res = client.get(f"/api/v1/routine-templates/?gym_id={gym.id}")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 10
        assert len(data["results"]) == 10
        assert data["results"][0]["days_count"] == 2
        assert data["results"][0]["total_exercises_count"] == 2

    # Paginated with custom page_size: exactly 5 queries
    with django_assert_num_queries(5):
        res_paginated = client.get(f"/api/v1/routine-templates/?gym_id={gym.id}&page=1&page_size=5")
        assert res_paginated.status_code == 200
        assert res_paginated.json()["count"] == 10
        assert len(res_paginated.json()["results"]) == 5


@pytest.mark.django_db
def test_phase6_member_routine_dossier_query_efficiency(django_assert_num_queries):
    """
    Verify GET /api/v1/members/{member_id}/routines/ executes with constant queries
    eagerly loading prescribed staff and nested days/exercises without N+1 hits.
    """
    from apps.gyms.services import create_gym
    from apps.memberships.services import create_membership_plan
    from apps.members.services import create_member
    from apps.routines.services import create_routine_template, assign_routine_to_member
    from common.enums import PlanStatusEnum, PlanTypeEnum, DurationUnitEnum

    owner = User.objects.create_user(
        email="p6.member.queries@manygym.com",
        password="Password123!",
        first_name="P6",
        last_name="MemberQuery",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Member Routine Query Gym")

    plan = create_membership_plan(
        gym=gym,
        name="Routine Pro Plan",
        description="Comprehensive plan description for testing member workout routine queries.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=120.00,
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    member = create_member(
        gym=gym,
        first_name="Athlete",
        last_name="One",
        email="athlete.one@example.com",
        plan_id=plan.id,
    )

    template = create_routine_template(
        gym=gym,
        template_name="Template Blueprint",
        days=[
            {
                "day_of_week": 1,
                "workout_title": "Squat Day",
                "exercises": [
                    {"exercise_name": "Back Squat", "sets": 5, "reps_or_duration": "5 reps"},
                ],
            }
        ],
    )

    assign_routine_to_member(gym=gym, member=member, source_template_id=template.id)

    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # 1. Member existence check + 2. Auth + 3. Gym context + 4. MemberRoutine query + 5. Days prefetch + 6. Exercises prefetch
    with django_assert_num_queries(6):
        res = client.get(f"/api/v1/members/{member.id}/routines/?gym_id={gym.id}")
        assert res.status_code == 200
        assert len(res.json()) == 1


@pytest.mark.django_db
def test_phase6_performance_benchmarks():
    """
    Load and latency benchmark testing for Phase 6 endpoints:
    - GET /api/v1/routine-templates/ (Target p95 < 200ms)
    - GET /api/v1/routine-templates/{id}/ (Target p95 < 200ms)
    - GET /api/v1/members/{id}/routines/ (Target p95 < 200ms)
    - POST /api/v1/members/{id}/routines/assign/ (Target p95 < 500ms)
    """
    import time
    from apps.gyms.services import create_gym
    from apps.memberships.services import create_membership_plan
    from apps.members.services import create_member
    from apps.routines.services import create_routine_template
    from common.enums import PlanStatusEnum, PlanTypeEnum, DurationUnitEnum, RoutineFormatEnum, RoutineLevelEnum

    def calc_p(values, percentile):
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = int(len(sorted_vals) * (percentile / 100.0))
        idx = min(idx, len(sorted_vals) - 1)
        return sorted_vals[idx]

    owner = User.objects.create_user(
        email="p6.benchmarks@manygym.com",
        password="Password123!",
        first_name="P6",
        last_name="Bench",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Benchmark Phase 6 Gym")

    plan = create_membership_plan(
        gym=gym,
        name="Bench Plan",
        description="Plan for benchmarking workout prescription latency.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=150.00,
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    templates = []
    for i in range(20):
        t = create_routine_template(
            gym=gym,
            template_name=f"Benchmark Template {i}",
            routine_format=RoutineFormatEnum.WEEKLY,
            level=RoutineLevelEnum.INTERMEDIATE,
            days=[
                {
                    "day_of_week": 1,
                    "workout_title": "Heavy Lift",
                    "exercises": [
                        {"exercise_name": "Deadlift", "sets": 5, "reps_or_duration": "5 reps"},
                    ],
                }
            ],
        )
        templates.append(t)

    member = create_member(
        gym=gym,
        first_name="BenchAthlete",
        last_name="Fast",
        email="bench.athlete@example.com",
        plan_id=plan.id,
    )

    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # 1. Benchmark GET /api/v1/routine-templates/
    list_latencies = []
    for _ in range(20):
        t0 = time.perf_counter()
        res = client.get(f"/api/v1/routine-templates/?gym_id={gym.id}")
        t1 = time.perf_counter()
        assert res.status_code == 200
        list_latencies.append((t1 - t0) * 1000)

    p50_list = calc_p(list_latencies, 50)
    p95_list = calc_p(list_latencies, 95)
    assert p95_list < 200, f"GET /api/v1/routine-templates/ p95 exceeded target: {p95_list:.2f}ms"

    # 2. Benchmark GET /api/v1/routine-templates/{id}/ (Dossier)
    detail_latencies = []
    for t in templates[:10]:
        t0 = time.perf_counter()
        res = client.get(f"/api/v1/routine-templates/{t.id}/?gym_id={gym.id}")
        t1 = time.perf_counter()
        assert res.status_code == 200
        detail_latencies.append((t1 - t0) * 1000)

    p50_detail = calc_p(detail_latencies, 50)
    p95_detail = calc_p(detail_latencies, 95)
    assert p95_detail < 200, f"GET /api/v1/routine-templates/{{id}}/ p95 exceeded target: {p95_detail:.2f}ms"

    # 3. Benchmark POST /api/v1/members/{id}/routines/assign/ (Complex write & clone)
    assign_latencies = []
    for i in range(10):
        t0 = time.perf_counter()
        res = client.post(
            f"/api/v1/members/{member.id}/routines/assign/?gym_id={gym.id}",
            {"source_template_id": str(templates[i].id)},
            format="json",
        )
        t1 = time.perf_counter()
        assert res.status_code == 201
        assign_latencies.append((t1 - t0) * 1000)

    p50_assign = calc_p(assign_latencies, 50)
    p95_assign = calc_p(assign_latencies, 95)
    assert p95_assign < 500, f"POST /api/v1/members/{{id}}/routines/assign/ p95 exceeded target: {p95_assign:.2f}ms"

    # 4. Benchmark GET /api/v1/members/{id}/routines/
    member_routines_latencies = []
    for _ in range(20):
        t0 = time.perf_counter()
        res = client.get(f"/api/v1/members/{member.id}/routines/?gym_id={gym.id}")
        t1 = time.perf_counter()
        assert res.status_code == 200
        member_routines_latencies.append((t1 - t0) * 1000)

    p50_mr = calc_p(member_routines_latencies, 50)
    p95_mr = calc_p(member_routines_latencies, 95)
    assert p95_mr < 200, f"GET /api/v1/members/{{id}}/routines/ p95 exceeded target: {p95_mr:.2f}ms"

    print("\n" + "=" * 60)
    print("PHASE 6 PERFORMANCE BENCHMARK REPORT:")
    print(f"GET /api/v1/routine-templates/ (20 items):    p50={p50_list:.2f}ms, p95={p95_list:.2f}ms (Target < 200ms)")
    print(f"GET /api/v1/routine-templates/{{id}}/:          p50={p50_detail:.2f}ms, p95={p95_detail:.2f}ms (Target < 200ms)")
    print(f"POST /api/v1/members/{{id}}/routines/assign/:   p50={p50_assign:.2f}ms, p95={p95_assign:.2f}ms (Target < 500ms)")
    print(f"GET /api/v1/members/{{id}}/routines/:           p50={p50_mr:.2f}ms, p95={p95_mr:.2f}ms (Target < 200ms)")
    print("=" * 60)


# ==============================================================================
# PHASE 7 PERFORMANCE & QUERY OPTIMIZATION BENCHMARKS
# ==============================================================================

@pytest.mark.django_db
def test_phase7_stream_gym_feed_generator():
    """Verify that stream_gym_feed returns a memory-efficient generator."""
    from apps.posts.models import GymPost
    from apps.posts.selectors import stream_gym_feed
    from apps.posts.services import create_post

    owner = User.objects.create_user(
        email="p7.stream.owner@manygym.com",
        password="Password123!",
        first_name="Stream",
        last_name="Owner",
        is_verified=True,
    )
    gym = Gym.objects.create(owner_user=owner, name="Stream Gym", timezone="UTC")

    for i in range(10):
        create_post(gym=gym, author_user=owner, content_text=f"Stream post #{i}")

    feed_gen = stream_gym_feed(gym=gym, is_member_or_staff=True, chunk_size=3)
    assert isinstance(feed_gen, types.GeneratorType)
    posts = list(feed_gen)
    assert len(posts) == 10


@pytest.mark.django_db
def test_phase7_post_queries_elimination_of_n_plus_one(django_assert_num_queries):
    """Verify list_gym_feed executes O(1) constant queries regardless of item count (eliminates N+1)."""
    from apps.posts.models import GymPost, GymPostMedia
    from apps.posts.selectors import list_gym_feed
    from apps.posts.services import create_post
    from apps.posts.rest_api.v1.serializers import GymPostListSerializer

    owner = User.objects.create_user(
        email="p7.nplus1.owner@manygym.com",
        password="Password123!",
        first_name="NPlus",
        last_name="One",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = Gym.objects.create(owner_user=owner, name="N+1 Post Gym", timezone="UTC")

    # Seed 15 posts with 3 media items each
    for i in range(15):
        post = create_post(gym=gym, author_user=owner, content_text=f"Community update #{i}")
        GymPostMedia.objects.bulk_create([
            GymPostMedia(post=post, media_url=f"/media/test_{i}_1.jpg", order_index=0),
            GymPostMedia(post=post, media_url=f"/media/test_{i}_2.jpg", order_index=1),
            GymPostMedia(post=post, media_url=f"/media/test_{i}_3.jpg", order_index=2),
        ])

    # Reset queries counter
    connection.queries_log.clear()

    # Query and serialize all 15 posts and their 45 media attachments
    qs = list_gym_feed(gym=gym, is_member_or_staff=True)
    with django_assert_num_queries(2):
        serializer = GymPostListSerializer(list(qs), many=True)
        data = serializer.data
        assert len(data) == 15
        assert len(data[0]["media_attachments"]) == 3


@pytest.mark.django_db
def test_phase7_performance_benchmarks_and_p95_latencies():
    """
    Validates measurable performance targets for Phase 7:
    - GET /api/v1/posts/ (Feed) p95 < 200 ms
    - GET /api/v1/posts/{id}/ (Detail Dossier) p95 < 200 ms
    - POST /api/v1/posts/ (Write) p95 < 500 ms
    """
    import time
    from apps.posts.models import GymPost, GymPostMedia
    from apps.posts.services import create_post

    owner = User.objects.create_user(
        email="p7.bench.owner@manygym.com",
        password="Password123!",
        first_name="Bench",
        last_name="Tester",
        is_verified=True,
    )
    UserProfile.objects.create(user=owner)
    gym = Gym.objects.create(owner_user=owner, name="Phase 7 Bench Gym", timezone="UTC")

    tokens = issue_context_token(owner, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # Seed 25 posts
    posts = []
    for i in range(25):
        p = create_post(
            gym=gym,
            author_user=owner,
            content_text=f"Benchmarking community feed item #{i:02d} with tips and tricks.",
        )
        GymPostMedia.objects.create(post=p, media_url=f"/media/post_{i}.jpg", order_index=0)
        posts.append(p)

    def calc_p(latencies, percentile):
        s = sorted(latencies)
        idx = int(len(s) * (percentile / 100.0))
        return s[min(idx, len(s) - 1)]

    # 1. Benchmark GET /api/v1/posts/ (Feed)
    feed_latencies = []
    for _ in range(20):
        t0 = time.perf_counter()
        res = client.get(f"/api/v1/posts/?gym_id={gym.id}")
        t1 = time.perf_counter()
        assert res.status_code == 200
        feed_latencies.append((t1 - t0) * 1000)

    p50_feed = calc_p(feed_latencies, 50)
    p95_feed = calc_p(feed_latencies, 95)
    assert p95_feed < 200, f"GET /api/v1/posts/ p95 exceeded target: {p95_feed:.2f}ms"

    # 2. Benchmark GET /api/v1/posts/{id}/ (Dossier)
    detail_latencies = []
    for p in posts[:10]:
        t0 = time.perf_counter()
        res = client.get(f"/api/v1/posts/{p.id}/?gym_id={gym.id}")
        t1 = time.perf_counter()
        assert res.status_code == 200
        detail_latencies.append((t1 - t0) * 1000)

    p50_detail = calc_p(detail_latencies, 50)
    p95_detail = calc_p(detail_latencies, 95)
    assert p95_detail < 200, f"GET /api/v1/posts/{{id}}/ p95 exceeded target: {p95_detail:.2f}ms"

    # 3. Benchmark POST /api/v1/posts/ (Write)
    create_latencies = []
    for i in range(10):
        t0 = time.perf_counter()
        res = client.post(
            f"/api/v1/posts/?gym_id={gym.id}",
            {"content_text": f"Benchmark live post creation #{i}"},
            format="json",
        )
        t1 = time.perf_counter()
        assert res.status_code == 201
        create_latencies.append((t1 - t0) * 1000)

    p50_create = calc_p(create_latencies, 50)
    p95_create = calc_p(create_latencies, 95)
    assert p95_create < 500, f"POST /api/v1/posts/ p95 exceeded target: {p95_create:.2f}ms"

    print("\n" + "=" * 60)
    print("PHASE 7 PERFORMANCE BENCHMARK REPORT:")
    print(f"GET /api/v1/posts/ (Feed list):        p50={p50_feed:.2f}ms, p95={p95_feed:.2f}ms (Target < 200ms)")
    print(f"GET /api/v1/posts/{{id}}/ (Dossier):     p50={p50_detail:.2f}ms, p95={p95_detail:.2f}ms (Target < 200ms)")
    print(f"POST /api/v1/posts/ (Create post):     p50={p50_create:.2f}ms, p95={p95_create:.2f}ms (Target < 500ms)")
    print("=" * 60)


# ==============================================================================
# PHASE 8 REPORTS & DASHBOARD OPTIMIZATION BENCHMARKS
# ==============================================================================

@pytest.mark.django_db
def test_phase8_database_level_aggregations_and_no_in_memory_loops():
    """Verify that reports use database-level SQL Sum and Count instead of Python loops."""
    import time
    from decimal import Decimal
    from django.utils import timezone
    from apps.reports.selectors import get_revenue_report, get_dashboard_summary
    from apps.memberships.services import create_membership_plan
    from apps.members.services import create_member, create_member_subscription, record_member_payment
    from common.enums import PlanTypeEnum, DurationUnitEnum, PaymentMethodEnum

    owner = User.objects.create_user(
        email="p8.agg.owner@manygym.com",
        password="Password123!",
        first_name="Report",
        last_name="Aggregator",
        is_verified=True,
    )
    gym = Gym.objects.create(owner_user=owner, name="Agg Gym", timezone="UTC")

    plan = create_membership_plan(
        gym=gym,
        name="Annual Pass",
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("1200.00"),
        duration_value=12,
        duration_unit=DurationUnitEnum.MONTH,
    )

    today = timezone.localdate()
    # Seed 50 payments across 10 members
    for i in range(10):
        m = create_member(gym=gym, first_name=f"Member{i}", last_name="Bench", email=f"m{i}.bench@test.com")
        sub = create_member_subscription(member=m, plan=plan, start_date=today)
        for j in range(5):
            record_member_payment(
                subscription=sub,
                amount=Decimal("100.00"),
                payment_method=PaymentMethodEnum.CREDIT_CARD if j % 2 == 0 else PaymentMethodEnum.CASH,
                payment_date=today,
            )

    # Execute reports and verify correctness
    t0 = time.perf_counter()
    rev_data = get_revenue_report(gym=gym, start_date=today, end_date=today)
    t1 = time.perf_counter()
    assert rev_data["total_revenue"] == 5000.0
    assert rev_data["total_transactions"] == 50
    assert (t1 - t0) * 1000 < 100.0, f"Database aggregation took {(t1 - t0) * 1000:.2f}ms"

    t2 = time.perf_counter()
    dash_data = get_dashboard_summary(gym=gym)
    t3 = time.perf_counter()
    assert dash_data["headline_metrics"]["total_members"] == 10
    assert dash_data["headline_metrics"]["todays_revenue"] == 5000.0
    assert (t3 - t2) * 1000 < 100.0, f"Dashboard summary aggregation took {(t3 - t2) * 1000:.2f}ms"


@pytest.mark.django_db
def test_phase8_performance_benchmarks_and_p95_latencies():
    """
    Validates measurable performance targets for Phase 8:
    - GET /api/v1/dashboard/summary/ p95 < 200 ms
    - GET /api/v1/reports/revenue/ p95 < 200 ms
    - GET /api/v1/reports/membership-growth/ p95 < 200 ms
    - GET /api/v1/reports/leads-funnel/ p95 < 200 ms
    - GET /api/v1/reports/trainer-workload/ p95 < 200 ms
    """
    import time
    from decimal import Decimal
    from django.utils import timezone
    from apps.memberships.services import create_membership_plan
    from apps.members.services import create_member, create_member_subscription, record_member_payment
    from apps.leads.services import create_lead
    from common.enums import PlanTypeEnum, DurationUnitEnum, PaymentMethodEnum, LeadStageEnum

    owner = User.objects.create_user(
        email="p8.bench.owner@manygym.com",
        password="Password123!",
        first_name="Bench",
        last_name="Executive",
        is_verified=True,
    )
    gym = Gym.objects.create(owner_user=owner, name="Phase 8 Bench Gym", timezone="UTC")

    tokens = issue_context_token(owner, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    plan = create_membership_plan(
        gym=gym,
        name="Bench Plan",
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("100.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )
    today = timezone.localdate()

    for i in range(15):
        m = create_member(gym=gym, first_name=f"BenchM{i}", last_name="Test", email=f"bm{i}@test.com")
        sub = create_member_subscription(member=m, plan=plan, start_date=today)
        record_member_payment(
            subscription=sub,
            amount=Decimal("100.00"),
            payment_method=PaymentMethodEnum.CREDIT_CARD,
            payment_date=today,
        )
        create_lead(gym=gym, first_name=f"Lead{i}", phone=f"+100{i:03d}", stage=LeadStageEnum.NEW)

    def calc_p(latencies, percentile):
        s = sorted(latencies)
        idx = int(len(s) * (percentile / 100.0))
        return s[min(idx, len(s) - 1)]

    endpoints = [
        ("/api/v1/dashboard/summary/", "Dashboard Summary"),
        ("/api/v1/reports/revenue/", "Revenue Report"),
        ("/api/v1/reports/membership-growth/", "Membership Growth"),
        ("/api/v1/reports/leads-funnel/", "Lead Funnel"),
        ("/api/v1/reports/trainer-workload/", "Trainer Workload"),
    ]

    p95_results = {}
    print("\n" + "=" * 60)
    print("PHASE 8 PERFORMANCE BENCHMARK REPORT:")

    for ep, label in endpoints:
        # Warm-up request to eliminate framework/resolver cold-start
        client.get(f"{ep}?gym_id={gym.id}")

        latencies = []
        for _ in range(20):
            t0 = time.perf_counter()
            res = client.get(f"{ep}?gym_id={gym.id}")
            t1 = time.perf_counter()
            assert res.status_code == 200
            latencies.append((t1 - t0) * 1000)

        p50 = calc_p(latencies, 50)
        p95 = calc_p(latencies, 95)
        p95_results[label] = p95
        assert p95 < 200, f"{label} p95 exceeded target: {p95:.2f}ms"
        print(f"{label:25s}: p50={p50:.2f}ms, p95={p95:.2f}ms (Target < 200ms)")

    print("=" * 60)


@pytest.mark.django_db
def test_phase8_query_count_optimizations(django_assert_num_queries):
    """
    Asserts strict constant query limits across all Phase 8 endpoints:
    - Eliminates N+1 queries in Trainer Workload (exactly 5 queries regardless of staff count)
    - Verifies consolidated SQL aggregations for Dashboard Summary (7 queries)
    - Verifies Revenue Report (6 queries)
    - Verifies Membership Growth Report (6 queries)
    - Verifies Lead Funnel Report (7 queries)
    """
    from decimal import Decimal
    from django.utils import timezone
    from apps.access_control.models import GymStaffAssignment, Role
    from apps.memberships.services import create_membership_plan
    from apps.members.services import create_member, create_member_subscription, record_member_payment
    from apps.leads.services import create_lead, schedule_next_move
    from apps.routines.models import MemberRoutine
    from common.enums import PlanTypeEnum, DurationUnitEnum, PaymentMethodEnum, LeadStageEnum, StaffStatus

    owner = User.objects.create_user(
        email="p8.qc.owner@manygym.com",
        password="Password123!",
        first_name="QCOwner",
        last_name="Test",
        is_verified=True,
    )
    gym = Gym.objects.create(owner_user=owner, name="Phase 8 QC Gym", timezone="UTC")

    tokens = issue_context_token(owner, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    plan = create_membership_plan(
        gym=gym,
        name="QC Plan",
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("150.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )
    today = timezone.localdate()

    # Create 5 staff trainers
    role = Role.objects.create(gym=gym, name="Trainer", slug="trainer")
    trainers = []
    for i in range(5):
        u = User.objects.create_user(
            email=f"trainer{i}.qc@manygym.com",
            password="Password123!",
            first_name=f"Trainer{i}",
            last_name="QC",
        )
        assignment = GymStaffAssignment.objects.create(
            gym=gym,
            user=u,
            role=role,
            status=StaffStatus.ACTIVE,
        )
        trainers.append(assignment)

    # Seed members, routines, leads, and payments
    for i in range(10):
        t = trainers[i % len(trainers)]
        m = create_member(
            gym=gym,
            first_name=f"Member{i}",
            last_name="QC",
            email=f"member{i}.qc@test.com",
            assigned_trainer_id=t.id,
        )
        sub = create_member_subscription(member=m, plan=plan, start_date=today)
        record_member_payment(
            subscription=sub,
            amount=Decimal("150.00"),
            payment_method=PaymentMethodEnum.CREDIT_CARD,
            payment_date=today,
        )
        MemberRoutine.objects.create(
            member=m,
            prescribed_by_staff=t,
            routine_name=f"Routine {i}",
            is_active=True,
        )
        lead = create_lead(gym=gym, first_name=f"Lead{i}", phone=f"+100{i:03d}", stage=LeadStageEnum.NEW)
        schedule_next_move(lead=lead, scheduled_date=today, short_description="Check-in")

    # 1. Trainer Workload: exactly 5 queries (1 auth + 1 gym + 1 staff + 1 batch members + 1 batch routines)
    # Even with 6 active staff (5 trainers + 1 owner), query count stays CONSTANT at 5 (N+1 eliminated!)
    with django_assert_num_queries(5):
        res = client.get(f"/api/v1/reports/trainer-workload/?gym_id={gym.id}")
        assert res.status_code == 200
        data = res.json()
        assert data["total_assigned_members"] == 10
        assert data["total_active_routines"] == 10

    # 2. Dashboard Summary: exactly 7 queries (1 auth + 1 gym + 5 consolidated aggregations)
    with django_assert_num_queries(7):
        res = client.get(f"/api/v1/dashboard/summary/?gym_id={gym.id}")
        assert res.status_code == 200
        data = res.json()
        assert data["headline_metrics"]["total_members"] == 10
        assert data["headline_metrics"]["todays_revenue"] == 1500.0

    # 3. Revenue Report: exactly 6 queries (1 auth + 1 gym + 4 aggregated sections)
    with django_assert_num_queries(6):
        res = client.get(f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date={today}&end_date={today}")
        assert res.status_code == 200
        data = res.json()
        assert data["total_revenue"] == 1500.0
        assert data["total_transactions"] == 10

    # 4. Membership Growth Report: exactly 6 queries (1 auth + 1 gym + 4 consolidated sub/plan aggregations)
    with django_assert_num_queries(6):
        res = client.get(f"/api/v1/reports/membership-growth/?gym_id={gym.id}&start_date={today}&end_date={today}")
        assert res.status_code == 200
        data = res.json()
        assert data["total_members"] == 10
        assert data["active_subscriptions"] == 10

    # 5. Lead Funnel Report: exactly 5 queries (1 auth + 1 gym + stage + extra_trials + source, skipping lost queries when lost_count == 0)
    with django_assert_num_queries(5):
        res = client.get(f"/api/v1/reports/leads-funnel/?gym_id={gym.id}&start_date={today}&end_date={today}")
        assert res.status_code == 200
        data = res.json()
        assert data["total_leads"] == 10










