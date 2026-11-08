import uuid
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym
from apps.gyms.services import create_gym
from apps.enquiries.models import Enquiry
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, EnquiryTypeEnum, EnquiryStatusEnum


@pytest.fixture
def auth_user(db):
    user = User.objects.create_user(
        email="enquiry_admin@example.com",
        password="SecurePassword123!",
        first_name="Admin",
        last_name="Staff",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def registered_user(db):
    user = User.objects.create_user(
        email="member_john@example.com",
        password="SecurePassword123!",
        first_name="John",
        last_name="Doe",
        is_verified=True,
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.avatar_url = "https://cdn.manygym.com/avatars/john.jpg"
    profile.save()
    return user


@pytest.fixture
def auth_client(auth_user):
    token = issue_context_token(user=auth_user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def gym_instance(auth_user):
    return create_gym(
        owner_user=auth_user,
        name="Powerhouse Gym",
        short_description="Top fitness club with state of the art equipment and spa facilities." * 2,
    )


class TestEnquiryCRUDLifecycle:
    """
    Tests complete lifecycle of Enquiries Menu feature:
    - Create new Enquiry (with email/phone rules, manygym user, type, status, notes)
    - List of Enquiry (with search and status/type filters)
    - View an Enquiry
    - Update an Enquiry
    - Delete an Enquiry
    """

    def test_create_enquiry_with_email_only(self, auth_client):
        payload = {
            "first_name": "Sarah",
            "last_name": "Connor",
            "email": "sarah.connor@example.com",
            "type": "GENERAL_INQUIRY",
            "status": "NEW",
            "summary": "Inquiring about personal trainer availability on weekends.",
            "notes": ["Customer prefers morning workouts"],
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["first_name"] == "Sarah"
        assert data["last_name"] == "Connor"
        assert data["email"] == "sarah.connor@example.com"
        assert data["phone"] is None
        assert data["type"] == "GENERAL_INQUIRY"
        assert data["status"] == "NEW"
        assert data["summary"] == "Inquiring about personal trainer availability on weekends."
        assert len(data["notes"]) == 1
        assert data["notes"][0] == "Customer prefers morning workouts"

        # Verify persisted in database
        enquiry = Enquiry.objects.get(id=data["id"])
        assert enquiry.first_name == "Sarah"
        assert enquiry.email == "sarah.connor@example.com"

    def test_create_enquiry_with_phone_only(self, auth_client):
        payload = {
            "first_name": "David",
            "last_name": "Beckham",
            "phone": "+1234567890",
            "type": "CALLBACK_REQUEST",
            "status": "NEW",
            "summary": "Please call back after 4 PM.",
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["phone"] == "+1234567890"
        assert data["email"] is None
        assert data["type"] == "CALLBACK_REQUEST"

    def test_create_enquiry_with_manygym_user_and_gym(self, auth_client, registered_user, gym_instance):
        payload = {
            "first_name": "John",
            "last_name": "Doe",
            "email": registered_user.email,
            "manygym_user_id": str(registered_user.id),
            "gym_id": str(gym_instance.id),
            "type": "SPECIAL_REQUEST",
            "status": "CONTACTED",
            "summary": "Requesting group discount for 5 colleagues.",
            "notes": ["Initial phone call completed", "Sent group discount brochure"],
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["manygym_user"] is not None
        assert data["manygym_user"]["user_id"] == str(registered_user.id)
        assert data["manygym_user"]["email"] == registered_user.email
        assert data["manygym_user"]["full_name"] == "John Doe"
        assert data["manygym_user"]["avatar_url"] == "https://cdn.manygym.com/avatars/john.jpg"
        assert data["gym_id"] == str(gym_instance.id)
        assert data["gym_name"] == "Powerhouse Gym"
        assert len(data["notes"]) == 2

    def test_create_enquiry_missing_both_email_and_phone_fails(self, auth_client):
        payload = {
            "first_name": "No",
            "last_name": "Contact",
            "summary": "This must fail because contact info is absent.",
        }
        res = auth_client.post("/api/v1/enquiries/", data=payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        data = res.json()
        assert "email" in str(data).lower() or "phone" in str(data).lower()

    def test_create_enquiry_missing_first_or_last_name_fails(self, auth_client):
        # Missing last_name
        res1 = auth_client.post(
            "/api/v1/enquiries/",
            data={"first_name": "OnlyFirst", "email": "only@example.com"},
            format="json",
        )
        assert res1.status_code == status.HTTP_400_BAD_REQUEST

        # Missing first_name
        res2 = auth_client.post(
            "/api/v1/enquiries/",
            data={"last_name": "OnlyLast", "email": "only@example.com"},
            format="json",
        )
        assert res2.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_enquiries_with_filters_and_search(self, auth_client):
        # Create 3 enquiries with distinct types and statuses
        auth_client.post(
            "/api/v1/enquiries/",
            data={
                "first_name": "Alice",
                "last_name": "Smith",
                "email": "alice.smith@example.com",
                "type": "COMPLAINT",
                "status": "NEW",
                "summary": "Locker room heating issue",
            },
            format="json",
        )
        auth_client.post(
            "/api/v1/enquiries/",
            data={
                "first_name": "Bob",
                "last_name": "Jones",
                "phone": "+4412345678",
                "type": "EMERGENCY",
                "status": "CONTACTED",
                "summary": "Lost keycard emergency",
            },
            format="json",
        )
        auth_client.post(
            "/api/v1/enquiries/",
            data={
                "first_name": "Charlie",
                "last_name": "Brown",
                "email": "charlie@example.com",
                "type": "GENERAL_INQUIRY",
                "status": "BOOKED",
                "summary": "Annual membership booked",
            },
            format="json",
        )

        # Helper to extract items whether paginated or raw list
        def get_items(res):
            data = res.json()
            return data.get("results", data) if isinstance(data, dict) else data

        # 1. Unfiltered list -> at least 3 items
        res_all = auth_client.get("/api/v1/enquiries/")
        assert res_all.status_code == status.HTTP_200_OK
        items_all = get_items(res_all)
        assert len(items_all) >= 3

        # 2. Filter by status: 'NEW'
        res_new = auth_client.get("/api/v1/enquiries/?status=NEW")
        assert res_new.status_code == status.HTTP_200_OK
        items_new = get_items(res_new)
        assert len(items_new) >= 1
        assert all(item["status"] == "NEW" for item in items_new)

        # 3. Filter by type: 'COMPLAINT'
        res_complaint = auth_client.get("/api/v1/enquiries/?type=COMPLAINT")
        assert res_complaint.status_code == status.HTTP_200_OK
        items_complaint = get_items(res_complaint)
        assert len(items_complaint) >= 1
        assert all(item["type"] == "COMPLAINT" for item in items_complaint)

        # 4. Search by term 'heating'
        res_search = auth_client.get("/api/v1/enquiries/?search=heating")
        assert res_search.status_code == status.HTTP_200_OK
        items_search = get_items(res_search)
        assert len(items_search) == 1
        assert items_search[0]["first_name"] == "Alice"

    def test_view_enquiry_by_id(self, auth_client):
        create_res = auth_client.post(
            "/api/v1/enquiries/",
            data={
                "first_name": "Emily",
                "last_name": "Clark",
                "email": "emily@example.com",
                "summary": "Yoga class schedule request",
            },
            format="json",
        )
        enquiry_id = create_res.json()["id"]

        # View detail
        view_res = auth_client.get(f"/api/v1/enquiries/{enquiry_id}/")
        assert view_res.status_code == status.HTTP_200_OK
        assert view_res.json()["id"] == enquiry_id
        assert view_res.json()["first_name"] == "Emily"

    def test_view_nonexistent_enquiry_returns_404(self, auth_client):
        random_id = uuid.uuid4()
        res = auth_client.get(f"/api/v1/enquiries/{random_id}/")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_update_enquiry_status_and_fields(self, auth_client):
        create_res = auth_client.post(
            "/api/v1/enquiries/",
            data={
                "first_name": "Marcus",
                "last_name": "Aurelius",
                "email": "marcus@rome.com",
                "status": "NEW",
                "notes": ["Initial inquiry received"],
            },
            format="json",
        )
        enquiry_id = create_res.json()["id"]

        # Update status from NEW to CONTACTED, then to VISIT, then BOOKED
        update_res = auth_client.patch(
            f"/api/v1/enquiries/{enquiry_id}/",
            data={
                "status": "CONTACTED",
                "append_note": "Spoke on phone, scheduled tour for Friday.",
                "summary": "Customer visiting gym this Friday.",
            },
            format="json",
        )
        assert update_res.status_code == status.HTTP_200_OK
        data = update_res.json()
        assert data["status"] == "CONTACTED"
        assert data["summary"] == "Customer visiting gym this Friday."
        assert len(data["notes"]) == 2
        assert "scheduled tour" in data["notes"][1]

        # Transition to VISIT
        res_visit = auth_client.patch(
            f"/api/v1/enquiries/{enquiry_id}/",
            data={"status": "VISIT"},
            format="json",
        )
        assert res_visit.json()["status"] == "VISIT"

        # Transition to BOOKED
        res_booked = auth_client.patch(
            f"/api/v1/enquiries/{enquiry_id}/",
            data={"status": "BOOKED"},
            format="json",
        )
        assert res_booked.json()["status"] == "BOOKED"

    def test_add_note_via_dedicated_endpoint(self, auth_client):
        create_res = auth_client.post(
            "/api/v1/enquiries/",
            data={
                "first_name": "Rachel",
                "last_name": "Green",
                "email": "rachel@friends.com",
            },
            format="json",
        )
        enquiry_id = create_res.json()["id"]

        note_res = auth_client.post(
            f"/api/v1/enquiries/{enquiry_id}/notes/",
            data={"note_text": "Prefers morning Zumba classes."},
            format="json",
        )
        assert note_res.status_code == status.HTTP_200_OK
        assert len(note_res.json()["notes"]) == 1
        assert note_res.json()["notes"][0] == "Prefers morning Zumba classes."

    def test_delete_enquiry_success(self, auth_client):
        create_res = auth_client.post(
            "/api/v1/enquiries/",
            data={
                "first_name": "Temporary",
                "last_name": "Enquiry",
                "email": "temp@example.com",
            },
            format="json",
        )
        enquiry_id = create_res.json()["id"]
        assert Enquiry.objects.filter(id=enquiry_id).exists()

        # Delete
        del_res = auth_client.delete(f"/api/v1/enquiries/{enquiry_id}/")
        assert del_res.status_code == status.HTTP_200_OK
        assert not Enquiry.objects.filter(id=enquiry_id).exists()

        # Second delete returns 404
        del_res_2 = auth_client.delete(f"/api/v1/enquiries/{enquiry_id}/")
        assert del_res_2.status_code == status.HTTP_404_NOT_FOUND
