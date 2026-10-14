import uuid
import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APIClient
from apps.users.models import User
from apps.gyms.models import Gym
from apps.amenities.models import AmenityCatalog, GymAmenity
from apps.memberships.models import MembershipPlan, PlanIncludedAmenities
from common.enums import (
    TokenContextType,
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    PaymentScheduleEnum,
    AmenityGroupEnum,
)
from apps.authentication.services import issue_context_token


def get_auth_client(user: User, context_type: str = TokenContextType.GYM, gym: Gym = None):
    client = APIClient()
    tokens = issue_context_token(user, context_type=context_type, gym=gym)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client, tokens


@pytest.mark.django_db
def test_create_time_based_membership_plan():
    """
    Test Step 1-5 creation of a time-based membership plan.
    Live look: $69.99 for 3 Months.
    """
    owner = User.objects.create_user(email="plan.owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Alpha Fitness")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    # Seed an amenity for bundling
    catalog_item = AmenityCatalog.objects.create(name="Sauna", group_name=AmenityGroupEnum.WELLNESS_AND_RECOVERY)
    gym_amenity = GymAmenity.objects.create(gym=gym, amenity=catalog_item, is_paid=False)

    payload = {
        "name": "Gold 3-Month Membership",
        "description": "Comprehensive gym access with full weight room, cardio section, and complimentary recovery sauna.",
        "plan_status": "draft",
        "plan_type": "time_based",
        "price": "69.99",
        "duration_value": 3,
        "duration_unit": "month",
        "joining_fee": "25.00",
        "payment_schedule": "full_payment",
        "cancellation_policy": "30 days prior written notice required.",
        "refund_policy": "Non-refundable after 14 days.",
        "included_amenity_ids": [str(gym_amenity.id)],
    }

    url = reverse("membership-plans-list-create")
    res = client.post(url, payload, format="json")
    assert res.status_code == 201
    data = res.data

    assert data["name"] == "Gold 3-Month Membership"
    assert data["plan_type"] == "time_based"
    assert data["price"] == "69.99"
    assert data["duration_value"] == 3
    assert data["duration_unit"] == "month"
    assert data["duration_display"] == "3 Months"
    assert data["joining_fee"] == "25.00"
    assert data["payment_schedule"] == "full_payment"
    assert len(data["included_amenities"]) == 1
    assert data["included_amenities"][0]["name"] == "Sauna"
    assert data["included_amenities"][0]["is_free"] is True


@pytest.mark.django_db
def test_create_session_based_membership_plan():
    """
    Test creation of a session-based membership plan.
    Live look: $105.00 for 10 Sessions.
    """
    owner = User.objects.create_user(email="session.owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Yoga Studio")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    payload = {
        "name": "Yoga 10-Pack",
        "description": "Access to 10 yoga studio sessions valid for 6 months from purchase date across all classes.",
        "plan_status": "active",
        "plan_type": "session_based",
        "price": "105.00",
        "duration_value": 10,
        "duration_unit": "session",
        "joining_fee": "0.00",
        "payment_schedule": "full_payment",
    }

    url = reverse("membership-plans-list-create")
    res = client.post(url, payload, format="json")
    assert res.status_code == 201
    data = res.data

    assert data["plan_type"] == "session_based"
    assert data["duration_value"] == 10
    assert data["duration_unit"] == "session"
    assert data["duration_display"] == "10 Sessions"
    assert data["price"] == "105.00"
    assert data["plan_status"] == "active"


@pytest.mark.django_db
def test_plan_description_min_length_validation():
    """
    Enforces minimum 50 characters on description if provided.
    """
    owner = User.objects.create_user(email="desc.tester@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Desc Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    url = reverse("membership-plans-list-create")
    bad_payload = {
        "name": "Short Desc Plan",
        "description": "Too short description.",  # < 50 chars
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 1,
        "duration_unit": "month",
    }
    res = client.post(url, bad_payload, format="json")
    assert res.status_code == 400
    assert "at least 50 characters" in str(res.data)


@pytest.mark.django_db
def test_plan_type_and_duration_unit_invariants():
    """
    Validates that:
    - time_based plans cannot use 'session' duration_unit
    - session_based plans must use 'session' duration_unit
    """
    owner = User.objects.create_user(email="invariant.tester@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Invariant Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)
    url = reverse("membership-plans-list-create")

    # Time-based with 'session' -> rejected
    res = client.post(url, {
        "name": "Invalid Time Plan",
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 1,
        "duration_unit": "session",
    }, format="json")
    assert res.status_code == 400
    assert "duration unit must be one of: day, week, month" in str(res.data)

    # Session-based with 'month' -> rejected
    res = client.post(url, {
        "name": "Invalid Session Plan",
        "plan_type": "session_based",
        "price": "50.00",
        "duration_value": 10,
        "duration_unit": "month",
    }, format="json")
    assert res.status_code == 400
    assert "duration unit must be 'session'" in str(res.data)


@pytest.mark.django_db
def test_installments_payment_schedule_validation():
    """
    If payment_schedule is 'instalments', installment_schedule_config must be provided.
    """
    owner = User.objects.create_user(email="install.tester@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Installment Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)
    url = reverse("membership-plans-list-create")

    # Instalments without config -> rejected
    res = client.post(url, {
        "name": "Annual Installments Plan",
        "plan_type": "time_based",
        "price": "600.00",
        "duration_value": 12,
        "duration_unit": "month",
        "payment_schedule": "instalments",
    }, format="json")
    assert res.status_code == 400
    assert "installment_schedule_config" in str(res.data).lower()

    # Instalments with config -> accepted
    res_ok = client.post(url, {
        "name": "Annual Installments Plan",
        "plan_type": "time_based",
        "price": "600.00",
        "duration_value": 12,
        "duration_unit": "month",
        "payment_schedule": "instalments",
        "installment_schedule_config": {
            "frequency": "monthly",
            "number_of_payments": 12,
            "amount_per_installment": "50.00",
        },
    }, format="json")
    assert res_ok.status_code == 201
    assert res_ok.data["payment_schedule"] == "instalments"
    assert res_ok.data["installment_schedule_config"]["number_of_payments"] == 12


@pytest.mark.django_db
def test_cross_tenant_amenity_bundling_rejected():
    """
    Ensures a gym cannot bundle an amenity belonging to another gym into its plan.
    """
    owner1 = User.objects.create_user(email="owner1@manygym.com", password="Password123!", is_verified=True)
    gym1 = Gym.objects.create(owner_user=owner1, name="Gym 1")

    owner2 = User.objects.create_user(email="owner2@manygym.com", password="Password123!", is_verified=True)
    gym2 = Gym.objects.create(owner_user=owner2, name="Gym 2")

    cat = AmenityCatalog.objects.create(name="Towel Service", group_name=AmenityGroupEnum.CHANGING_AND_STORAGE)
    gym2_amenity = GymAmenity.objects.create(gym=gym2, amenity=cat, is_paid=False)

    client1, _ = get_auth_client(owner1, context_type=TokenContextType.GYM, gym=gym1)
    url = reverse("membership-plans-list-create")

    res = client1.post(url, {
        "name": "Cross Tenant Plan",
        "plan_type": "time_based",
        "price": "40.00",
        "duration_value": 1,
        "duration_unit": "month",
        "included_amenity_ids": [str(gym2_amenity.id)],
    }, format="json")
    assert res.status_code == 400
    assert "do not belong to this gym" in str(res.data)


@pytest.mark.django_db
def test_plan_status_transitions():
    """
    Tests state machine transitions:
    - draft -> active
    - active -> archived
    - archived -> active
    - archived -> draft (rejected)
    """
    owner = User.objects.create_user(email="status.tester@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Status Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    create_url = reverse("membership-plans-list-create")
    res = client.post(create_url, {
        "name": "Lifecycle Plan",
        "plan_type": "time_based",
        "price": "50.00",
        "duration_value": 1,
        "duration_unit": "month",
        "plan_status": "draft",
    }, format="json")
    assert res.status_code == 201
    plan_id = res.data["id"]
    status_url = reverse("membership-plan-status", kwargs={"plan_id": plan_id})

    # 1. Draft -> Active
    res_active = client.post(status_url, {"plan_status": "active"}, format="json")
    assert res_active.status_code == 200
    assert res_active.data["plan_status"] == "active"

    # 2. Active -> Archived
    res_archived = client.post(status_url, {"plan_status": "archived"}, format="json")
    assert res_archived.status_code == 200
    assert res_archived.data["plan_status"] == "archived"

    # 3. Archived -> Draft (Rejected)
    res_bad = client.post(status_url, {"plan_status": "draft"}, format="json")
    assert res_bad.status_code == 400
    assert "cannot be reverted back to draft" in str(res_bad.data)

    # 4. Archived -> Active (Allowed)
    res_reactivate = client.post(status_url, {"plan_status": "active"}, format="json")
    assert res_reactivate.status_code == 200
    assert res_reactivate.data["plan_status"] == "active"


@pytest.mark.django_db
def test_update_plan_and_sync_amenities():
    """
    Tests PATCH update and PUT amenity sync endpoints.
    """
    owner = User.objects.create_user(email="update.tester@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Update Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    cat1 = AmenityCatalog.objects.create(name="Wifi", group_name=AmenityGroupEnum.COMFORT_AND_CONVENIENCE)
    cat2 = AmenityCatalog.objects.create(name="Locker", group_name=AmenityGroupEnum.CHANGING_AND_STORAGE)
    a1 = GymAmenity.objects.create(gym=gym, amenity=cat1, is_paid=False)
    a2 = GymAmenity.objects.create(gym=gym, amenity=cat2, is_paid=True, default_price=Decimal("15.00"))

    create_url = reverse("membership-plans-list-create")
    res = client.post(create_url, {
        "name": "Original Plan Name",
        "plan_type": "time_based",
        "price": "30.00",
        "duration_value": 1,
        "duration_unit": "month",
        "included_amenity_ids": [str(a1.id)],
    }, format="json")
    plan_id = res.data["id"]

    # 1. PATCH update name and price
    detail_url = reverse("membership-plan-detail", kwargs={"plan_id": plan_id})
    patch_res = client.patch(detail_url, {
        "name": "Updated Plan Name",
        "price": "35.00",
    }, format="json")
    assert patch_res.status_code == 200
    assert patch_res.data["name"] == "Updated Plan Name"
    assert patch_res.data["price"] == "35.00"

    # 2. PUT sync amenities: replace a1 with a2
    sync_url = reverse("membership-plan-amenities-sync", kwargs={"plan_id": plan_id})
    sync_res = client.put(sync_url, {
        "amenity_ids": [str(a2.id)],
    }, format="json")
    assert sync_res.status_code == 200
    assert len(sync_res.data["included_amenities"]) == 1
    assert sync_res.data["included_amenities"][0]["id"] == str(a2.id)
    assert sync_res.data["included_amenities"][0]["name"] == "Locker"
    assert sync_res.data["included_amenities"][0]["is_free"] is False


@pytest.mark.django_db
def test_filter_and_search_plans():
    """
    Tests filtering by status, type, and keyword search.
    """
    owner = User.objects.create_user(email="filter.tester@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Filter Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    url = reverse("membership-plans-list-create")
    # Create 3 plans
    client.post(url, {
        "name": "Bronze Month Plan",
        "plan_type": "time_based",
        "price": "30.00",
        "duration_value": 1,
        "duration_unit": "month",
        "plan_status": "draft",
    }, format="json")

    client.post(url, {
        "name": "Silver Year Plan",
        "plan_type": "time_based",
        "price": "300.00",
        "duration_value": 12,
        "duration_unit": "month",
        "plan_status": "active",
    }, format="json")

    client.post(url, {
        "name": "Pilates 5-Session Pack",
        "plan_type": "session_based",
        "price": "80.00",
        "duration_value": 5,
        "duration_unit": "session",
        "plan_status": "active",
    }, format="json")

    # 1. Filter by plan_status=active -> 2
    res_active = client.get(f"{url}?plan_status=active")
    assert res_active.status_code == 200
    assert len(res_active.data) == 2

    # 2. Filter by plan_type=session_based -> 1
    res_sessions = client.get(f"{url}?plan_type=session_based")
    assert res_sessions.status_code == 200
    assert len(res_sessions.data) == 1
    assert res_sessions.data[0]["name"] == "Pilates 5-Session Pack"

    # 3. Search by 'Silver' -> 1
    res_search = client.get(f"{url}?search=Silver")
    assert res_search.status_code == 200
    assert len(res_search.data) == 1
    assert res_search.data[0]["name"] == "Silver Year Plan"


@pytest.mark.django_db
def test_tenant_isolation_on_plans():
    """
    Ensures Gym B cannot view or modify Gym A's membership plans.
    """
    owner_a = User.objects.create_user(email="owner_a@manygym.com", password="Password123!", is_verified=True)
    gym_a = Gym.objects.create(owner_user=owner_a, name="Gym A")

    owner_b = User.objects.create_user(email="owner_b@manygym.com", password="Password123!", is_verified=True)
    gym_b = Gym.objects.create(owner_user=owner_b, name="Gym B")

    plan_a = MembershipPlan.objects.create(
        gym=gym_a,
        name="Gym A Secret Plan",
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("100.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    client_b, _ = get_auth_client(owner_b, context_type=TokenContextType.GYM, gym=gym_b)
    detail_url = reverse("membership-plan-detail", kwargs={"plan_id": plan_a.id})

    # Gym B GET -> 404
    get_res = client_b.get(detail_url)
    assert get_res.status_code == 404

    # Gym B PATCH -> 404
    patch_res = client_b.patch(detail_url, {"price": "10.00"}, format="json")
    assert patch_res.status_code == 404

    # Gym B DELETE -> 404
    delete_res = client_b.delete(detail_url)
    assert delete_res.status_code == 404


@pytest.mark.django_db
def test_delete_and_archive_plan():
    """
    Tests draft deletion and active archiving.
    """
    owner = User.objects.create_user(email="del.tester@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Del Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    create_url = reverse("membership-plans-list-create")
    res_draft = client.post(create_url, {
        "name": "Draft To Delete",
        "plan_type": "time_based",
        "price": "20.00",
        "duration_value": 1,
        "duration_unit": "month",
        "plan_status": "draft",
    }, format="json")
    draft_id = res_draft.data["id"]

    del_url = reverse("membership-plan-detail", kwargs={"plan_id": draft_id})
    del_res = client.delete(del_url)
    assert del_res.status_code == 200
    assert not MembershipPlan.objects.filter(id=draft_id).exists()


@pytest.mark.django_db
def test_membership_plans_query_efficiency(django_assert_num_queries):
    """
    Ensures listing membership plans with their included amenities has NO N+1 query issue.
    Query count remains constant regardless of the number of plans and bundled amenities.
    """
    owner = User.objects.create_user(email="nplusone.plans@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Efficient Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    # Create 5 catalog items and gym amenities
    gym_amenities = []
    for i in range(5):
        cat = AmenityCatalog.objects.create(name=f"Amenity {i}", group_name=AmenityGroupEnum.WELLNESS_AND_RECOVERY)
        gym_amenities.append(GymAmenity.objects.create(gym=gym, amenity=cat, is_paid=False))

    # Create 5 plans, each with 3 bundled amenities
    for i in range(5):
        plan = MembershipPlan.objects.create(
            gym=gym,
            name=f"Plan {i}",
            plan_type=PlanTypeEnum.TIME_BASED,
            price=Decimal("50.00"),
            duration_value=1,
            duration_unit=DurationUnitEnum.MONTH,
            plan_status=PlanStatusEnum.ACTIVE,
        )
        for ga in gym_amenities[:3]:
            PlanIncludedAmenities.objects.create(plan=plan, gym_amenity=ga)

    url = reverse("membership-plans-list-create")

    # Efficient query count: exactly 4 queries
    # 1. Auth user lookup (FastJWT select_related profile)
    # 2. Gym lookup
    # 3. MembershipPlan list query with Count annotation and .only()
    # 4. PlanIncludedAmenities prefetch (inner join with GymAmenity + AmenityCatalog via select_related)
    with django_assert_num_queries(4):
        res = client.get(url)
        assert res.status_code == 200
        assert len(res.data) == 5


@pytest.mark.django_db
def test_membership_plans_pagination():
    """
    Ensures pagination works correctly when query parameters are supplied,
    preventing unbounded dataset returns.
    """
    owner = User.objects.create_user(email="page.plans@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Paged Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    for i in range(7):
        MembershipPlan.objects.create(
            gym=gym,
            name=f"Paged Plan {i}",
            plan_type=PlanTypeEnum.TIME_BASED,
            price=Decimal("49.99"),
            duration_value=1,
            duration_unit=DurationUnitEnum.MONTH,
            plan_status=PlanStatusEnum.ACTIVE,
        )

    url = reverse("membership-plans-list-create")
    res = client.get(f"{url}?page=1&page_size=3")
    assert res.status_code == 200
    assert "results" in res.data
    assert res.data["count"] == 7
    assert len(res.data["results"]) == 3
    assert res.data["next"] is not None


@pytest.mark.django_db
def test_membership_plans_database_aggregations_metrics(django_assert_num_queries):
    """
    Tests single-query DB-level aggregation for gym plan metrics (Count, Avg, Min, Max).
    """
    owner = User.objects.create_user(email="metrics.plans@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Metrics Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    # 2 active, 1 draft, 1 archived
    MembershipPlan.objects.create(gym=gym, name="P1", plan_type=PlanTypeEnum.TIME_BASED, price=Decimal("20.00"), duration_value=1, duration_unit=DurationUnitEnum.MONTH, plan_status=PlanStatusEnum.ACTIVE)
    MembershipPlan.objects.create(gym=gym, name="P2", plan_type=PlanTypeEnum.SESSION_BASED, price=Decimal("60.00"), duration_value=5, duration_unit=DurationUnitEnum.SESSION, plan_status=PlanStatusEnum.ACTIVE)
    MembershipPlan.objects.create(gym=gym, name="P3", plan_type=PlanTypeEnum.TIME_BASED, price=Decimal("10.00"), duration_value=1, duration_unit=DurationUnitEnum.MONTH, plan_status=PlanStatusEnum.DRAFT)
    MembershipPlan.objects.create(gym=gym, name="P4", plan_type=PlanTypeEnum.TIME_BASED, price=Decimal("30.00"), duration_value=1, duration_unit=DurationUnitEnum.MONTH, plan_status=PlanStatusEnum.ARCHIVED)

    url = reverse("membership-plans-metrics")
    # 1. Auth user, 2. Gym lookup, 3. Single aggregated SQL query
    with django_assert_num_queries(3):
        res = client.get(url)
        assert res.status_code == 200

    data = res.data
    assert data["total_plans"] == 4
    assert data["active_plans"] == 2
    assert data["draft_plans"] == 1
    assert data["archived_plans"] == 1
    assert data["time_based_plans"] == 3
    assert data["session_based_plans"] == 1
    assert data["min_price"] == 10.0
    assert data["max_price"] == 60.0
    assert data["avg_price"] == 30.0


@pytest.mark.django_db
def test_stream_gym_plans_iterator():
    """
    Tests streaming gym plans using QuerySet.iterator() to prevent full materialization in memory.
    """
    from apps.memberships.selectors import stream_gym_plans

    owner = User.objects.create_user(email="stream.plans@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Stream Gym")

    for i in range(10):
        MembershipPlan.objects.create(
            gym=gym,
            name=f"Stream Plan {i}",
            plan_type=PlanTypeEnum.TIME_BASED,
            price=Decimal(f"{10 + i}.00"),
            duration_value=1,
            duration_unit=DurationUnitEnum.MONTH,
            plan_status=PlanStatusEnum.ACTIVE,
        )

    stream = stream_gym_plans(gym, chunk_size=5)
    plans = list(stream)
    assert len(plans) == 10
    assert plans[0].name == "Stream Plan 9"  # ordered by -created_at

