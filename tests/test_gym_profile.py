import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User
from apps.gyms.models import Gym, GymLocation, GymOpeningHours, GymGallery
from apps.gyms.services import create_gym
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, GalleryCategoryEnum, MediaTypeEnum


@pytest.fixture
def test_user(db):
    return User.objects.create_user(
        email="gym.owner@example.com",
        password="SecurePassword123!",
        first_name="John",
        last_name="Doe",
        is_verified=True,
    )


@pytest.fixture
def auth_client(test_user):
    tokens = issue_context_token(test_user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def gym_with_owner(test_user):
    return create_gym(owner_user=test_user, name="Iron Paradise Fitness")


@pytest.mark.django_db
class TestGymProfileFlow:

    def test_gym_creation_with_default_location_and_hours(self, auth_client, test_user):
        url = reverse("gyms_v1:gym-create")
        payload = {
            "name": "Titan Gym & Fitness",
            "address": "123 Muscle Boulevard",
            "city": "Austin",
            "postal_code": "78701",
            "country": "USA",
            "latitude": "30.26720000",
            "longitude": "-97.74310000",
        }
        res = auth_client.post(url, payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        data = res.data
        assert data["name"] == "Titan Gym & Fitness"
        assert "id" in data

        gym_id = data["id"]
        gym = Gym.objects.get(id=gym_id)
        assert gym.owner_user == test_user

        # Verify location created
        location = GymLocation.objects.get(gym=gym)
        assert location.city == "Austin"
        assert float(location.latitude) == pytest.approx(30.2672)

        # Verify default 7 days opening hours created
        hours = GymOpeningHours.objects.filter(gym=gym)
        assert hours.count() == 7

    def test_overview_update_enforces_min_120_chars(self, auth_client, gym_with_owner):
        url = reverse("gyms_v1:gym-profile-overview")

        # 1. Edge Case: Short description under 120 chars must fail
        short_desc = "Short description under 120 characters."
        res = auth_client.patch(
            f"{url}?gym_id={gym_with_owner.id}",
            {"short_description": short_desc},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "at least 120 characters" in str(res.data)

        # 2. Valid description >= 120 chars
        valid_desc = (
            "Iron Paradise Fitness is a premier fitness center dedicated to strength training, "
            "functional conditioning, high-performance coaching, and personal wellness goals."
        )
        assert len(valid_desc) >= 120

        res_valid = auth_client.patch(
            f"{url}?gym_id={gym_with_owner.id}",
            {
                "name": "Iron Paradise Elite",
                "short_description": valid_desc,
            },
            format="json",
        )
        assert res_valid.status_code == status.HTTP_200_OK
        assert res_valid.data["name"] == "Iron Paradise Elite"
        assert res_valid.data["short_description"] == valid_desc

    def test_location_update(self, auth_client, gym_with_owner):
        url = reverse("gyms_v1:gym-profile-location")
        payload = {
            "address": "999 Oak Ridge Lane",
            "city": "Dallas",
            "postal_code": "75001",
            "country": "USA",
            "latitude": "32.77670000",
            "longitude": "-96.79700000",
        }
        res = auth_client.patch(f"{url}?gym_id={gym_with_owner.id}", payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["city"] == "Dallas"
        assert float(res.data["latitude"]) == pytest.approx(32.7767)

    def test_opening_hours_bulk_update_and_edge_cases(self, auth_client, gym_with_owner):
        url = reverse("gyms_v1:gym-opening-hours")

        # 1. Valid bulk update
        payload = {
            "hours": [
                {"day_of_week": 0, "start_time": "05:00:00", "end_time": "23:00:00", "is_closed": False},
                {"day_of_week": 1, "start_time": "05:00:00", "end_time": "23:00:00", "is_closed": False},
                {"day_of_week": 2, "start_time": "05:00:00", "end_time": "23:00:00", "is_closed": False},
                {"day_of_week": 3, "start_time": "05:00:00", "end_time": "23:00:00", "is_closed": False},
                {"day_of_week": 4, "start_time": "05:00:00", "end_time": "23:00:00", "is_closed": False},
                {"day_of_week": 5, "start_time": "07:00:00", "end_time": "21:00:00", "is_closed": False},
                {"day_of_week": 6, "start_time": None, "end_time": None, "is_closed": True},
            ]
        }
        res = auth_client.put(f"{url}?gym_id={gym_with_owner.id}", payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data) == 7

        sunday = [h for h in res.data if h["day_of_week"] == 6][0]
        assert sunday["is_closed"] is True
        assert sunday["start_time"] is None

        # 2. Edge Case: start_time >= end_time must fail with 400
        invalid_payload = {
            "hours": [
                {"day_of_week": 0, "start_time": "22:00:00", "end_time": "08:00:00", "is_closed": False},
            ]
        }
        res_invalid = auth_client.put(f"{url}?gym_id={gym_with_owner.id}", invalid_payload, format="json")
        assert res_invalid.status_code == status.HTTP_400_BAD_REQUEST

    def test_gallery_crud_and_reorder(self, auth_client, gym_with_owner):
        list_url = reverse("gyms_v1:gym-gallery-list")

        # 1. Add gallery item
        res_upload = auth_client.post(
            f"{list_url}?gym_id={gym_with_owner.id}",
            {
                "media_url": "https://cdn.manygym.com/equipment-1.jpg",
                "media_type": MediaTypeEnum.PICTURE,
                "category": GalleryCategoryEnum.EQUIPMENT,
                "caption": "State of the art dumbbells",
            },
            format="json",
        )
        assert res_upload.status_code == status.HTTP_201_CREATED
        item1_id = res_upload.data["id"]

        res_upload2 = auth_client.post(
            f"{list_url}?gym_id={gym_with_owner.id}",
            {
                "media_url": "https://cdn.manygym.com/interior-1.jpg",
                "media_type": MediaTypeEnum.PICTURE,
                "category": GalleryCategoryEnum.INTERIOR_DECOR,
                "caption": "Main workout floor",
            },
            format="json",
        )
        assert res_upload2.status_code == status.HTTP_201_CREATED
        item2_id = res_upload2.data["id"]

        # 2. Filter gallery by category
        res_filter = auth_client.get(
            f"{list_url}?gym_id={gym_with_owner.id}&category={GalleryCategoryEnum.EQUIPMENT}"
        )
        assert res_filter.status_code == status.HTTP_200_OK
        assert len(res_filter.data) == 1
        assert res_filter.data[0]["id"] == item1_id

        # 3. Reorder items
        reorder_url = reverse("gyms_v1:gym-gallery-reorder")
        res_reorder = auth_client.patch(
            f"{reorder_url}?gym_id={gym_with_owner.id}",
            {
                "items": [
                    {"id": item2_id, "order_index": 0},
                    {"id": item1_id, "order_index": 1},
                ]
            },
            format="json",
        )
        assert res_reorder.status_code == status.HTTP_200_OK

        item2 = GymGallery.objects.get(id=item2_id)
        assert item2.order_index == 0
        item1 = GymGallery.objects.get(id=item1_id)
        assert item1.order_index == 1

        # 4. Delete gallery item
        delete_url = reverse("gyms_v1:gym-gallery-detail", kwargs={"item_id": item1_id})
        res_del = auth_client.delete(f"{delete_url}?gym_id={gym_with_owner.id}")
        assert res_del.status_code == status.HTTP_200_OK
        assert not GymGallery.objects.filter(id=item1_id).exists()

    def test_unauthorized_user_permission_denied(self, gym_with_owner):
        # Create unrelated user
        other_user = User.objects.create_user(
            email="other@user.com",
            password="OtherPassword123!",
            first_name="Jane",
            last_name="Smith",
            is_verified=True,
        )
        tokens = issue_context_token(other_user, context_type=TokenContextType.PERSONAL)
        unauth_client = APIClient()
        unauth_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        url = reverse("gyms_v1:gym-profile-overview")
        valid_desc = "Valid description" * 10
        res = unauth_client.patch(
            f"{url}?gym_id={gym_with_owner.id}",
            {"short_description": valid_desc},
            format="json",
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN
