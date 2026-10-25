import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from apps.users.models import User
from apps.gyms.models import Gym
from apps.access_control.models import Role, Permission, GymStaffAssignment
from apps.access_control.services import seed_default_permissions_and_roles
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType


@pytest.fixture(autouse=True)
def setup_rbac_seeds(db):
    seed_default_permissions_and_roles()


@pytest.mark.django_db
def test_context_switching_and_dynamic_rbac_scoping():
    client = APIClient()

    # 1. Setup Owner and Staff Users
    owner = User.objects.create_user(
        email="gym.owner@manygym.com",
        password="Password123!",
        first_name="Owner",
        last_name="Alice",
        is_verified=True,
    )

    staff_user = User.objects.create_user(
        email="trainer.bob@manygym.com",
        password="Password123!",
        first_name="Bob",
        last_name="Smith",
        is_verified=True,
    )

    unrelated_user = User.objects.create_user(
        email="stranger@other.com",
        password="Password123!",
        first_name="Stranger",
        last_name="Joe",
        is_verified=True,
    )

    # 2. Owner creates a Gym
    gym = Gym.objects.create(
        owner_user=owner,
        name="Apex Fitness Club",
    )

    # 3. Owner switches context to Gym -> Gets full scopes
    owner_tokens = issue_context_token(owner, context_type=TokenContextType.PERSONAL)
    owner_client = APIClient()
    owner_client.credentials(HTTP_AUTHORIZATION=f"Bearer {owner_tokens['access']}")

    switch_to_gym_res = owner_client.post(reverse("switch-context"), {
        "context_type": "gym",
        "gym_id": str(gym.id),
    })
    assert switch_to_gym_res.status_code == 200
    gym_token_data = switch_to_gym_res.data["tokens"]
    assert gym_token_data["context_type"] == "gym"
    assert gym_token_data["gym_id"] == str(gym.id)
    # Owner should have full scopes
    assert "members:read" in gym_token_data["scopes"]
    assert "people_roles:manage" in gym_token_data["scopes"]

    # 4. Unrelated user tries to switch context to this gym -> Rejected 401 UnauthorizedContext
    stranger_tokens = issue_context_token(unrelated_user, context_type=TokenContextType.PERSONAL)
    stranger_client = APIClient()
    stranger_client.credentials(HTTP_AUTHORIZATION=f"Bearer {stranger_tokens['access']}")

    unauthorized_switch_res = stranger_client.post(reverse("switch-context"), {
        "context_type": "gym",
        "gym_id": str(gym.id),
    })
    assert unauthorized_switch_res.status_code == 401

    # 5. Owner invites staff member with "Trainer" role
    trainer_role = Role.objects.get(slug="trainer")
    owner_client.credentials(HTTP_AUTHORIZATION=f"Bearer {gym_token_data['access']}")

    invite_res = owner_client.post(reverse("staff-list-invite"), {
        "email": staff_user.email,
        "role_id": str(trainer_role.id),
    })
    assert invite_res.status_code == 201

    # 6. Now staff user can switch context to this gym and receives only Trainer scopes!
    staff_tokens = issue_context_token(staff_user, context_type=TokenContextType.PERSONAL)
    staff_client = APIClient()
    staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {staff_tokens['access']}")

    staff_switch_res = staff_client.post(reverse("switch-context"), {
        "context_type": "gym",
        "gym_id": str(gym.id),
    })
    assert staff_switch_res.status_code == 200
    staff_gym_tokens = staff_switch_res.data["tokens"]
    assert "routines:assign" in staff_gym_tokens["scopes"]
    # Trainer does NOT have people_roles:manage scope
    assert "people_roles:manage" not in staff_gym_tokens["scopes"]

    # 7. Trainer tries to create a role -> Rejected 403 Forbidden
    staff_client.credentials(HTTP_AUTHORIZATION=f"Bearer {staff_gym_tokens['access']}")
    forbidden_role_res = staff_client.post(reverse("roles-list-create"), {
        "name": "Super Admin Custom",
    })
    assert forbidden_role_res.status_code == 403

    # 8. Owner creates a custom role with specific scopes
    read_members_perm = Permission.objects.get(scope_code="members:read")
    create_role_res = owner_client.post(reverse("roles-list-create"), {
        "name": "Front Desk Associate",
        "description": "Custom role for reception desk",
        "permission_ids": [str(read_members_perm.id)],
    })
    assert create_role_res.status_code == 201
    assert create_role_res.data["name"] == "Front Desk Associate"
    assert create_role_res.data["is_custom"] is True


@pytest.mark.django_db
def test_permissions_list_endpoint():
    user = User.objects.create_user(
        email="test.perms@manygym.com",
        password="Password123!",
        first_name="Test",
        last_name="User",
        is_verified=True,
    )
    tokens = issue_context_token(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    res = client.get(reverse("permissions-list"))
    assert res.status_code == 200
    data = res.json()
    assert "Studio" in data
    assert "Members" in data
    assert "People & Roles" in data


@pytest.mark.django_db
def test_me_endpoint_in_gym_context_sorting_and_profile_picture():
    owner = User.objects.create_user(
        email="multi.owner@manygym.com",
        password="Password123!",
        first_name="Multi",
        last_name="Owner",
        is_verified=True,
    )
    gym1 = Gym.objects.create(
        name="First Gym",
        owner_user=owner,
        primary_type="crossfit_box",
        profile_picture_url="https://cdn.manygym.com/gym1.jpg",
    )
    gym2 = Gym.objects.create(
        name="Second Gym",
        owner_user=owner,
        primary_type="powerlifting_gym",
        profile_picture_url="https://cdn.manygym.com/gym2.jpg",
    )

    # 1. In Personal context:
    p_tokens = issue_context_token(owner, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {p_tokens['access']}")
    res_p = client.get(reverse("me"))
    assert res_p.status_code == 200
    assert res_p.data["current_context"]["type"] == "personal"
    assert res_p.data["current_context"]["gym_id"] is None
    assert res_p.data["current_context"]["gym_name"] is None
    assert res_p.data["current_context"]["profile_picture_url"] is None
    assert len(res_p.data["accessible_gyms"]) == 2

    # 2. Switch to Second Gym context:
    switch_res = client.post(reverse("switch-context"), {
        "context_type": "gym",
        "gym_id": str(gym2.id),
    })
    assert switch_res.status_code == 200
    gym2_token = switch_res.data["tokens"]["access"]

    # 3. Call GET /me/ in Second Gym context:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {gym2_token}")
    res_g2 = client.get(reverse("me"))
    assert res_g2.status_code == 200
    ctx = res_g2.data["current_context"]
    assert ctx["type"] == "gym"
    assert str(ctx["gym_id"]) == str(gym2.id)
    assert ctx["gym_name"] == "Second Gym"
    assert ctx["profile_picture_url"] == "https://cdn.manygym.com/gym2.jpg"

    # Verify sorting: Second Gym MUST be at index 0 (top of accessible_gyms list)
    acc = res_g2.data["accessible_gyms"]
    assert len(acc) == 2
    assert str(acc[0]["gym_id"]) == str(gym2.id)
    assert acc[0]["name"] == "Second Gym"
    assert str(acc[1]["gym_id"]) == str(gym1.id)
    assert acc[1]["name"] == "First Gym"
