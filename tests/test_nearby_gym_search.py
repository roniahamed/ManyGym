import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User
from apps.gyms.models import Gym, GymLocation, GymOpeningHours, GymFollow, GymBlockedUser
from apps.gyms.services import (
    create_gym,
    update_gym_location,
    apply_access_control_action,
    block_user_for_gym,
)
from apps.gyms.services.geo_services import (
    get_redis_client,
    REDIS_GEO_KEY,
    warm_gym_geo_cache,
)
from apps.amenities.models import AmenityCatalog, GymAmenity
from apps.memberships.models import MembershipPlan
from common.enums import (
    GymTypeEnum,
    GymGenderRequired,
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    AmenityGroupEnum,
)


@pytest.fixture
def owner_user(db):
    return User.objects.create_user(
        email="gym.owner@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Owner",
        is_verified=True,
    )


@pytest.fixture
def member_user(db):
    return User.objects.create_user(
        email="member.bob@example.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Member",
        is_verified=True,
    )


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def seed_gyms(db, owner_user):
    """
    Creates 3 test gyms with varied geographical locations:
    - Gym A: Dhanmondi, Dhaka (23.7465, 90.3760) -> Strength & Bodybuilding
    - Gym B: Uttara, Dhaka (23.8759, 90.3795) (~14.4 km north) -> Functional Fitness
    - Gym C: Gazipur (23.9999, 90.4203) (~28.5 km north) -> Yoga & Pilates
    """
    desc = (
        "A premier fitness institution dedicated to empowering members with elite equipment, "
        "world-class training guidance, and high-quality coaching programs across all experience levels."
    )

    gym_a = create_gym(
        owner_user=owner_user,
        name="Titan Strength Club",
        primary_type=GymTypeEnum.STRENGTH_BODYBUILDING,
        short_description=desc,
        address="House 12, Road 7, Dhanmondi",
        latitude=23.7465,
        longitude=90.3760,
        city="Dhaka",
        country="Bangladesh",
    )

    gym_b = create_gym(
        owner_user=owner_user,
        name="Uttara Functional Arena",
        primary_type=GymTypeEnum.FUNCTIONAL_FITNESS,
        short_description=desc,
        address="Sector 3, Uttara",
        latitude=23.8759,
        longitude=90.3795,
        city="Dhaka",
        country="Bangladesh",
    )

    gym_c = create_gym(
        owner_user=owner_user,
        name="Gazipur Wellness Studio",
        primary_type=GymTypeEnum.YOGA_PILATES_STUDIO,
        short_description=desc,
        address="Chowrasta, Gazipur",
        latitude=23.9999,
        longitude=90.4203,
        city="Gazipur",
        country="Bangladesh",
    )

    # Attach an amenity to Gym A
    catalog_item = AmenityCatalog.objects.create(
        name="Infrared Sauna",
        group_name=AmenityGroupEnum.WELLNESS_AND_RECOVERY,
    )
    GymAmenity.objects.create(
        gym=gym_a,
        amenity=catalog_item,
        is_paid=False,
    )

    # Attach an active plan to Gym A
    MembershipPlan.objects.create(
        gym=gym_a,
        name="Monthly Gold Pass",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("49.99"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    # Warm Redis GEO
    warm_gym_geo_cache()

    return gym_a, gym_b, gym_c


@pytest.mark.django_db
class TestNearbyGymSearch:

    def test_search_nearby_gyms_within_20km_radius(self, api_client, seed_gyms):
        """
        User at Dhanmondi (23.7465, 90.3760) searches with default 20 km radius.
        Titan (0 km) and Uttara (~14.4 km) must be returned; Gazipur (~28.5 km) must be excluded.
        Results must be ordered by distance ascending.
        """
        gym_a, gym_b, gym_c = seed_gyms
        url = reverse("gyms_v1:gym-nearby-search")

        response = api_client.get(url, {
            "latitude": 23.7465,
            "longitude": 90.3760,
            # radius defaults to 20 km
        })

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "results" in data
        results = data["results"]

        # Exactly Gym A and Gym B
        returned_ids = [r["id"] for r in results]
        assert str(gym_a.id) in returned_ids
        assert str(gym_b.id) in returned_ids
        assert str(gym_c.id) not in returned_ids

        # Sorted nearest first
        assert returned_ids[0] == str(gym_a.id)
        assert returned_ids[1] == str(gym_b.id)

        # Distance verification
        assert results[0]["distance_km"] <= 0.1
        assert 13.0 <= results[1]["distance_km"] <= 16.0
        assert results[0]["is_open_now"] is not None
        assert "Infrared Sauna" in results[0]["amenities_preview"]

    def test_search_nearby_gyms_custom_radius(self, api_client, seed_gyms):
        """
        With radius=5 km, only Gym A should appear.
        With radius=35 km, all 3 gyms should appear.
        """
        gym_a, gym_b, gym_c = seed_gyms
        url = reverse("gyms_v1:gym-nearby-search")

        # 5 km radius
        r5 = api_client.get(url, {
            "latitude": 23.7465,
            "longitude": 90.3760,
            "radius": 5.0,
        })
        assert r5.status_code == status.HTTP_200_OK
        ids5 = [r["id"] for r in r5.json()["results"]]
        assert ids5 == [str(gym_a.id)]

        # 35 km radius
        r35 = api_client.get(url, {
            "latitude": 23.7465,
            "longitude": 90.3760,
            "radius": 35.0,
        })
        assert r35.status_code == status.HTTP_200_OK
        ids35 = [r["id"] for r in r35.json()["results"]]
        assert len(ids35) == 3
        assert ids35 == [str(gym_a.id), str(gym_b.id), str(gym_c.id)]

    def test_search_by_category_filter(self, api_client, seed_gyms):
        """
        Filtering by category='functional_fitness_gym' returns only Gym B.
        """
        gym_a, gym_b, gym_c = seed_gyms
        url = reverse("gyms_v1:gym-nearby-search")

        response = api_client.get(url, {
            "latitude": 23.7465,
            "longitude": 90.3760,
            "radius": 35.0,
            "category": GymTypeEnum.FUNCTIONAL_FITNESS,
        })
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == str(gym_b.id)
        assert results[0]["primary_type"] == GymTypeEnum.FUNCTIONAL_FITNESS

    def test_search_by_city_without_coordinates(self, api_client, seed_gyms):
        """
        Search by city='Dhaka' without coordinates:
        Returns Gym A and Gym B with distance_km=null.
        """
        gym_a, gym_b, gym_c = seed_gyms
        url = reverse("gyms_v1:gym-nearby-search")

        response = api_client.get(url, {"city": "Dhaka"})
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        returned_ids = {r["id"] for r in results}
        assert str(gym_a.id) in returned_ids
        assert str(gym_b.id) in returned_ids
        assert str(gym_c.id) not in returned_ids

        # distance_km should be null when searched without coordinates
        for r in results:
            assert r["distance_km"] is None

    def test_search_by_keyword(self, api_client, seed_gyms):
        """Keyword search matches name or address."""
        gym_a, gym_b, gym_c = seed_gyms
        url = reverse("gyms_v1:gym-nearby-search")

        response = api_client.get(url, {"search": "Titan"})
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == str(gym_a.id)

    def test_redis_cache_flush_triggers_postgresql_fallback(self, api_client, seed_gyms):
        """
        When Redis GEO cache is flushed or unavailable, selector must fallback
        to PostgreSQL spherical distance query and warm Redis back up.
        """
        gym_a, gym_b, gym_c = seed_gyms
        r_client = get_redis_client()
        r_client.delete(REDIS_GEO_KEY)

        url = reverse("gyms_v1:gym-nearby-search")
        response = api_client.get(url, {
            "latitude": 23.7465,
            "longitude": 90.3760,
            "radius": 20.0,
        })
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        returned_ids = [r["id"] for r in results]
        assert returned_ids == [str(gym_a.id), str(gym_b.id)]

        # Verify Redis GEO was re-warmed
        cached_count = r_client.zcard(REDIS_GEO_KEY)
        assert cached_count >= 2

    def test_deactivated_or_unpublished_gym_excluded_from_search(self, api_client, seed_gyms, owner_user):
        """
        When a gym is unpublished or deactivated, it must be purged from Redis GEO
        and excluded from search results.
        """
        gym_a, gym_b, gym_c = seed_gyms
        apply_access_control_action(gym_b, "unpublish", user=owner_user)

        url = reverse("gyms_v1:gym-nearby-search")
        response = api_client.get(url, {
            "latitude": 23.7465,
            "longitude": 90.3760,
            "radius": 20.0,
        })
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert str(gym_a.id) in ids
        assert str(gym_b.id) not in ids

    def test_blocked_user_cannot_see_gym_in_search(self, api_client, seed_gyms, owner_user, member_user):
        """
        A user who has been blocked by Gym A cannot discover Gym A in nearby search.
        """
        gym_a, gym_b, gym_c = seed_gyms
        block_user_for_gym(gym=gym_a, user_id=str(member_user.id), blocked_by_user=owner_user)

        api_client.force_authenticate(user=member_user)
        url = reverse("gyms_v1:gym-nearby-search")
        response = api_client.get(url, {
            "latitude": 23.7465,
            "longitude": 90.3760,
            "radius": 20.0,
        })
        assert response.status_code == status.HTTP_200_OK
        ids = [r["id"] for r in response.json()["results"]]
        assert str(gym_a.id) not in ids
        assert str(gym_b.id) in ids

    def test_validation_errors_for_invalid_coordinates(self, api_client):
        """
        Rejects latitude without longitude, out-of-bounds coordinates, and invalid radius.
        """
        url = reverse("gyms_v1:gym-nearby-search")

        # Latitude without longitude
        r1 = api_client.get(url, {"latitude": 23.7465})
        assert r1.status_code == status.HTTP_400_BAD_REQUEST

        # Out-of-bounds latitude (>90)
        r2 = api_client.get(url, {"latitude": 95.0, "longitude": 90.0})
        assert r2.status_code == status.HTTP_400_BAD_REQUEST

        # Negative radius
        r3 = api_client.get(url, {"latitude": 23.7465, "longitude": 90.3760, "radius": -5.0})
        assert r3.status_code == status.HTTP_400_BAD_REQUEST

        # Radius too large (>500)
        r4 = api_client.get(url, {"latitude": 23.7465, "longitude": 90.3760, "radius": 600.0})
        assert r4.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_public_gym_details(self, api_client, seed_gyms, member_user):
        """
        Retrieves full public view of a gym including locations, hours, amenities,
        membership plans, and social statistics.
        """
        gym_a, gym_b, gym_c = seed_gyms
        GymFollow.objects.create(user=member_user, gym=gym_a)

        api_client.force_authenticate(user=member_user)
        url = reverse("gyms_v1:gym-public-detail", kwargs={"gym_id": gym_a.id})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == str(gym_a.id)
        assert data["name"] == "Titan Strength Club"
        assert data["location"]["city"] == "Dhaka"
        assert "today_status" in data
        assert "operating_hours" in data
        assert len(data["operating_hours"]) == 7
        assert data["amenities"]["total_count"] >= 1
        assert len(data["membership_plans"]) >= 1
        assert data["membership_plans"][0]["name"] == "Monthly Gold Pass"
        assert data["social"]["followers_count"] == 1
        assert data["social"]["is_following"] is True

    def test_get_public_gym_details_nonexistent_or_deleted(self, api_client, seed_gyms, owner_user):
        """
        Non-existent UUID or unpublished gym returns 404 for public users.
        """
        import uuid
        gym_a, gym_b, gym_c = seed_gyms

        # Non-existent
        url_fake = reverse("gyms_v1:gym-public-detail", kwargs={"gym_id": uuid.uuid4()})
        assert api_client.get(url_fake).status_code == status.HTTP_404_NOT_FOUND

        # Unpublished
        apply_access_control_action(gym_c, "unpublish", user=owner_user)
        url_c = reverse("gyms_v1:gym-public-detail", kwargs={"gym_id": gym_c.id})
        assert api_client.get(url_c).status_code == status.HTTP_404_NOT_FOUND
