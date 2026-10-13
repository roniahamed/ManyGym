import pytest
from decimal import Decimal
from rest_framework import status
from rest_framework.test import APIClient
from django.urls import reverse

from apps.users.models import User
from apps.gyms.services import create_gym
from apps.amenities.models import AmenityCatalog, GymAmenity
from apps.amenities.services import seed_amenity_catalog
from apps.access_control.models import Role
from apps.access_control.services import seed_default_permissions_and_roles
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType


@pytest.fixture(autouse=True)
def setup_amenities_and_rbac(db):
    seed_amenity_catalog()
    seed_default_permissions_and_roles()


@pytest.fixture
def gym_owner(db):
    return User.objects.create_user(
        email="gymowner.amenities@example.com",
        password="Password123!",
        first_name="Alice",
        last_name="Owner",
        is_verified=True,
    )


@pytest.fixture
def auth_client(gym_owner):
    tokens = issue_context_token(gym_owner, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def sample_gym(gym_owner):
    return create_gym(owner_user=gym_owner, name="Olympus Fitness Center")


@pytest.mark.django_db
class TestAmenitiesSystem:

    def test_amenity_catalog_grouped_retrieval(self, auth_client):
        url = reverse("amenities_v1:amenity-catalog")
        res = auth_client.get(url)
        assert res.status_code == status.HTTP_200_OK

        catalog = res.data
        # Verify all 7 categories
        assert "Changing & Storage" in catalog
        assert "Wellness & Recovery" in catalog
        assert "Comfort & Convenience" in catalog
        assert "Food & Drink" in catalog
        assert "Parking & Transport" in catalog
        assert "Accessibility" in catalog
        assert "Family Facilities" in catalog

        # Verify items inside
        wellness_items = [item["name"] for item in catalog["Wellness & Recovery"]]
        assert "Sauna" in wellness_items
        assert "Steam room" in wellness_items

    def test_gym_configured_amenities_initial_empty(self, auth_client, sample_gym):
        url = reverse("amenities_v1:gym-amenities-configured")
        res = auth_client.get(f"{url}?gym_id={sample_gym.id}")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["total_count"] == 0
        assert len(res.data["free_amenities"]) == 0
        assert len(res.data["paid_amenities"]) == 0

    def test_sync_gym_amenities_success(self, auth_client, sample_gym):
        sync_url = reverse("amenities_v1:gym-amenities-sync")

        # Pick 2 catalog items for free, 1 for paid
        free_item_1 = AmenityCatalog.objects.get(name="Wi-Fi")
        free_item_2 = AmenityCatalog.objects.get(name="Showers")
        paid_item = AmenityCatalog.objects.get(name="Personal lockers")

        payload = {
            "free_amenity_ids": [str(free_item_1.id), str(free_item_2.id)],
            "paid_amenities": [
                {
                    "amenity_id": str(paid_item.id),
                    "default_price": "15.00",
                }
            ],
        }

        res = auth_client.put(f"{sync_url}?gym_id={sample_gym.id}", payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["free_count"] == 2
        assert res.data["paid_count"] == 1

        # Verify retrieval matches
        conf_url = reverse("amenities_v1:gym-amenities-configured")
        res_conf = auth_client.get(f"{conf_url}?gym_id={sample_gym.id}")
        assert res_conf.status_code == status.HTTP_200_OK
        assert res_conf.data["total_count"] == 3
        free_names = [a["name"] for a in res_conf.data["free_amenities"]]
        assert "Wi-Fi" in free_names
        assert "Showers" in free_names

        paid_names = [a["name"] for a in res_conf.data["paid_amenities"]]
        assert "Personal lockers" in paid_names
        assert res_conf.data["paid_amenities"][0]["default_price"] == "15.00"

    def test_sync_gym_amenities_replaces_and_clears(self, auth_client, sample_gym):
        sync_url = reverse("amenities_v1:gym-amenities-sync")
        conf_url = reverse("amenities_v1:gym-amenities-configured")

        # 1. Setup initial amenities
        item1 = AmenityCatalog.objects.get(name="Wi-Fi")
        item2 = AmenityCatalog.objects.get(name="Parking")
        auth_client.put(
            f"{sync_url}?gym_id={sample_gym.id}",
            {"free_amenity_ids": [str(item1.id), str(item2.id)], "paid_amenities": []},
            format="json",
        )
        assert GymAmenity.objects.filter(gym=sample_gym).count() == 2

        # 2. Resync with only 1 item (item1 removed, item3 added as paid)
        item3 = AmenityCatalog.objects.get(name="Cafe")
        res2 = auth_client.put(
            f"{sync_url}?gym_id={sample_gym.id}",
            {
                "free_amenity_ids": [str(item2.id)],
                "paid_amenities": [{"amenity_id": str(item3.id), "default_price": "8.50"}],
            },
            format="json",
        )
        assert res2.status_code == status.HTTP_200_OK
        assert GymAmenity.objects.filter(gym=sample_gym).count() == 2
        assert not GymAmenity.objects.filter(gym=sample_gym, amenity=item1).exists()

        # 3. Empty sync clears all amenities
        res_clear = auth_client.put(
            f"{sync_url}?gym_id={sample_gym.id}",
            {"free_amenity_ids": [], "paid_amenities": []},
            format="json",
        )
        assert res_clear.status_code == status.HTTP_200_OK
        assert res_clear.data["free_count"] == 0
        assert res_clear.data["paid_count"] == 0
        assert GymAmenity.objects.filter(gym=sample_gym).count() == 0

    def test_sync_gym_amenities_mutual_exclusion_violation(self, auth_client, sample_gym):
        """
        Crucial Business Rule: An amenity CANNOT be both free and paid simultaneously.
        """
        sync_url = reverse("amenities_v1:gym-amenities-sync")
        sauna = AmenityCatalog.objects.get(name="Sauna")

        payload = {
            "free_amenity_ids": [str(sauna.id)],
            "paid_amenities": [
                {
                    "amenity_id": str(sauna.id),
                    "default_price": "10.00",
                }
            ],
        }

        res = auth_client.put(f"{sync_url}?gym_id={sample_gym.id}", payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        error_msg = str(res.data)
        assert "Mutual exclusion violation" in error_msg
        assert "Sauna" in error_msg

    def test_sync_gym_amenities_invalid_price_zero_or_negative(self, auth_client, sample_gym):
        sync_url = reverse("amenities_v1:gym-amenities-sync")
        lockers = AmenityCatalog.objects.get(name="Personal lockers")

        # Zero price for paid amenity should fail
        payload_zero = {
            "free_amenity_ids": [],
            "paid_amenities": [{"amenity_id": str(lockers.id), "default_price": "0.00"}],
        }
        res_zero = auth_client.put(f"{sync_url}?gym_id={sample_gym.id}", payload_zero, format="json")
        assert res_zero.status_code == status.HTTP_400_BAD_REQUEST

        # Negative price for paid amenity should fail
        payload_neg = {
            "free_amenity_ids": [],
            "paid_amenities": [{"amenity_id": str(lockers.id), "default_price": "-5.00"}],
        }
        res_neg = auth_client.put(f"{sync_url}?gym_id={sample_gym.id}", payload_neg, format="json")
        assert res_neg.status_code == status.HTTP_400_BAD_REQUEST

    def test_sync_gym_amenities_invalid_amenity_id(self, auth_client, sample_gym):
        sync_url = reverse("amenities_v1:gym-amenities-sync")
        fake_uuid = "00000000-0000-0000-0000-000000000000"

        payload = {
            "free_amenity_ids": [fake_uuid],
            "paid_amenities": [],
        }

        res = auth_client.put(f"{sync_url}?gym_id={sample_gym.id}", payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid amenity catalog IDs provided" in str(res.data)

    def test_rbac_staff_permission_for_amenities(self, sample_gym, gym_owner):
        # 1. Staff user with Administrator role (has gym_profile:edit and gym_profile:read)
        admin_user = User.objects.create_user(
            email="manager@example.com",
            password="Password123!",
            first_name="Admin",
            last_name="Manager",
            is_verified=True,
        )
        admin_role = Role.objects.get(slug="administrator")
        from apps.access_control.models import GymStaffAssignment
        from common.enums import StaffStatus
        GymStaffAssignment.objects.create(
            user=admin_user,
            gym=sample_gym,
            role=admin_role,
            status=StaffStatus.ACTIVE,
        )

        admin_client = APIClient()
        # Switch context to gym
        from apps.authentication.services import switch_gym_context
        admin_context = switch_gym_context(admin_user, str(sample_gym.id))
        admin_client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_context['access']}")

        # Administrator can sync amenities
        sync_url = reverse("amenities_v1:gym-amenities-sync")
        wifi = AmenityCatalog.objects.get(name="Wi-Fi")
        res_sync = admin_client.put(
            sync_url,
            {"free_amenity_ids": [str(wifi.id)], "paid_amenities": []},
            format="json",
        )
        assert res_sync.status_code == status.HTTP_200_OK

        # 2. Staff user with Trainer role (only has routines:assign, does NOT have gym_profile:edit)
        trainer_user = User.objects.create_user(
            email="trainer@example.com",
            password="Password123!",
            first_name="Trainer",
            last_name="Tom",
            is_verified=True,
        )
        trainer_role = Role.objects.get(slug="trainer")
        GymStaffAssignment.objects.create(
            user=trainer_user,
            gym=sample_gym,
            role=trainer_role,
            status=StaffStatus.ACTIVE,
        )

        trainer_context = switch_gym_context(trainer_user, str(sample_gym.id))
        trainer_client = APIClient()
        trainer_client.credentials(HTTP_AUTHORIZATION=f"Bearer {trainer_context['access']}")

        # Trainer cannot sync amenities -> 403 Forbidden
        res_trainer_sync = trainer_client.put(
            sync_url,
            {"free_amenity_ids": [str(wifi.id)], "paid_amenities": []},
            format="json",
        )
        assert res_trainer_sync.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthorized_user_cannot_sync_amenities(self, sample_gym):
        unauth_user = User.objects.create_user(
            email="intruder@example.com",
            password="Password123!",
            first_name="Intruder",
            last_name="Eve",
            is_verified=True,
        )
        tokens = issue_context_token(unauth_user, context_type=TokenContextType.PERSONAL)
        unauth_client = APIClient()
        unauth_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        sync_url = reverse("amenities_v1:gym-amenities-sync")
        res = unauth_client.put(f"{sync_url}?gym_id={sample_gym.id}", {"free_amenity_ids": []}, format="json")
        assert res.status_code == status.HTTP_403_FORBIDDEN
