import uuid
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym, GymSetting, GymBlockedUser
from apps.gyms.services import create_gym, block_user_for_gym
from apps.access_control.models import Role, Permission, GymStaffAssignment
from apps.access_control.services import seed_default_permissions_and_roles
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    StaffStatus,
    AudienceMessagingEnum,
    AudienceJoiningRequestEnum,
    AudienceMembersVisibilityEnum,
    AudienceFollowingVisibilityEnum,
    PostsAgeRestrictionEnum,
)


@pytest.fixture(autouse=True)
def setup_seeds(db):
    seed_default_permissions_and_roles()


@pytest.fixture
def owner_user(db):
    user = User.objects.create_user(
        email="gym.owner.qa@manygym.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    return user


@pytest.fixture
def other_gym_owner(db):
    user = User.objects.create_user(
        email="other.owner.qa@manygym.com",
        password="SecurePassword123!",
        first_name="Other",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    return user


@pytest.fixture
def candidate_user(db):
    user = User.objects.create_user(
        email="candidate.bob@manygym.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Candidate",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, avatar_url="https://cdn.manygym.com/bob.jpg")
    return user


@pytest.fixture
def third_user(db):
    user = User.objects.create_user(
        email="third.user@manygym.com",
        password="SecurePassword123!",
        first_name="Charlie",
        last_name="Third",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    return user


@pytest.fixture
def staff_readonly_user(db, test_gym):
    user = User.objects.create_user(
        email="staff.ro@manygym.com",
        password="SecurePassword123!",
        first_name="Staff",
        last_name="ReadOnly",
        is_verified=True,
    )
    UserProfile.objects.create(user=user)
    # Assign custom role with only gym_profile:read
    role = Role.objects.create(gym=test_gym, name="ReadOnlyStaff", slug="readonly_staff", is_custom=True)
    perm = Permission.objects.get(scope_code="gym_profile:read")
    role.permissions.add(perm)
    GymStaffAssignment.objects.create(gym=test_gym, user=user, role=role, status=StaffStatus.ACTIVE)
    return user


@pytest.fixture
def auth_client(owner_user):
    tokens = issue_context_token(owner_user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def other_client(other_gym_owner):
    tokens = issue_context_token(other_gym_owner, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def staff_client(staff_readonly_user, test_gym):
    tokens = issue_context_token(staff_readonly_user, context_type=TokenContextType.GYM, gym=test_gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def test_gym(owner_user):
    return create_gym(owner_user=owner_user, name="Iron Fortress Gym")


@pytest.fixture
def other_gym(other_gym_owner):
    return create_gym(owner_user=other_gym_owner, name="Other Gold Gym")


@pytest.mark.django_db
class TestGymSettingsExhaustiveTypeJuggling:
    """1. Test all applicable fields with incorrect data types (Type Juggling)."""

    def test_patch_settings_type_mismatches(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings")

        invalid_type_payloads = [
            # Integer where string expected
            ({"language": 12345}, 400),
            # Array/list where string expected
            ({"language": ["en"]}, 400),
            # Dict/object where string expected
            ({"language": {"code": "en"}}, 400),
            # Boolean where string expected
            ({"language": True}, 400),
            # String where boolean expected
            ({"video_autoplay": "true"}, 400),
            ({"video_autoplay": "1"}, 400),
            ({"video_autoplay": "yes"}, 400),
            ({"dark_mode": "false"}, 400),
            ({"admin_logs_alerts": "true"}, 400),
            ({"issues_alerts": "false"}, 400),
            ({"is_deactivated": "true"}, 400),
            ({"is_published": "false"}, 400),
            ({"is_deleted": "true"}, 400),
            # Integer where boolean expected
            ({"video_autoplay": 1}, 400),
            ({"dark_mode": 0}, 400),
            ({"admin_logs_alerts": 2}, 400),
            ({"issues_alerts": 10}, 400),
            # Float where boolean expected
            ({"video_autoplay": 1.5}, 400),
            ({"dark_mode": 0.0}, 400),
            # List where boolean expected
            ({"video_autoplay": [True]}, 400),
            ({"dark_mode": []}, 400),
            # Dict where boolean expected
            ({"video_autoplay": {"enabled": True}}, 400),
            # Integer where enum string expected
            ({"who_can_message": 999}, 400),
            ({"who_can_send_joining_request": 0}, 400),
            ({"who_can_see_members": 1}, 400),
            ({"who_can_see_following": 2}, 400),
            ({"posts_age_restriction": 18}, 400),
            # List where enum string expected
            ({"who_can_message": ["everyone"]}, 400),
            ({"posts_age_restriction": ["18_plus"]}, 400),
            # Dict where enum string expected
            ({"who_can_message": {"val": "everyone"}}, 400),
        ]

        for payload, expected_status in invalid_type_payloads:
            res = auth_client.patch(f"{url}?gym_id={test_gym.id}", payload, format="json")
            assert res.status_code == expected_status, f"Failed for payload: {payload}, got {res.status_code}: {res.data}"

    def test_block_user_type_mismatches(self, auth_client, test_gym, candidate_user):
        url = reverse("gyms_v1:gym-settings-blocked-users")

        invalid_payloads = [
            # Integer where UUID expected
            {"user_id": 12345},
            # Boolean where UUID expected
            {"user_id": True},
            # Float where UUID expected
            {"user_id": 3.14},
            # List where UUID expected
            {"user_id": [str(candidate_user.id)]},
            # Dict where UUID expected
            {"user_id": {"id": str(candidate_user.id)}},
            # Null where UUID expected
            {"user_id": None},
            # Integer where string reason expected
            {"user_id": str(candidate_user.id), "reason": 12345},
            # Boolean where string reason expected
            {"user_id": str(candidate_user.id), "reason": True},
            # List where string reason expected
            {"user_id": str(candidate_user.id), "reason": ["spam"]},
            # Dict where string reason expected
            {"user_id": str(candidate_user.id), "reason": {"msg": "spam"}},
        ]

        for payload in invalid_payloads:
            res = auth_client.post(f"{url}?gym_id={test_gym.id}", payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Failed for payload: {payload}"

    def test_access_control_action_type_mismatches(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings-access-control")

        invalid_payloads = [
            {"action": 12345},
            {"action": True},
            {"action": 3.14},
            {"action": ["deactivate"]},
            {"action": {"action": "deactivate"}},
            {"action": None},
        ]

        for payload in invalid_payloads:
            res = auth_client.post(f"{url}?gym_id={test_gym.id}", payload, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Failed for payload: {payload}"


@pytest.mark.django_db
class TestGymSettingsBoundaryAndLengthCases:
    """2. Boundary & Length Edge Cases."""

    def test_language_length_boundaries(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings")

        # 1. Exactly 20 chars (max length boundary) -> Should succeed
        twenty_chars = "a" * 20
        res = auth_client.patch(f"{url}?gym_id={test_gym.id}", {"language": twenty_chars}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["language"] == twenty_chars

        # 2. 21 chars (max length + 1) -> Should fail with 400
        twenty_one_chars = "a" * 21
        res_fail = auth_client.patch(f"{url}?gym_id={test_gym.id}", {"language": twenty_one_chars}, format="json")
        assert res_fail.status_code == status.HTTP_400_BAD_REQUEST

        # 3. 10,000+ characters -> Should fail with 400, no 500
        huge_str = "x" * 10000
        res_huge = auth_client.patch(f"{url}?gym_id={test_gym.id}", {"language": huge_str}, format="json")
        assert res_huge.status_code == status.HTTP_400_BAD_REQUEST

    def test_reason_length_boundaries_on_block(self, auth_client, test_gym, candidate_user, third_user):
        url = reverse("gyms_v1:gym-settings-blocked-users")

        # 1. Exactly 255 chars (max_length) -> Should succeed
        reason_255 = "r" * 255
        res = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"user_id": str(candidate_user.id), "reason": reason_255},
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        assert res.data["reason"] == reason_255

        # 2. 256 chars (max_length + 1) -> Should fail with 400
        reason_256 = "r" * 256
        res_fail = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"user_id": str(third_user.id), "reason": reason_256},
            format="json",
        )
        assert res_fail.status_code == status.HTTP_400_BAD_REQUEST

        # 3. 10,000+ chars -> Should fail with 400
        reason_huge = "r" * 15000
        res_huge = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"user_id": str(third_user.id), "reason": reason_huge},
            format="json",
        )
        assert res_huge.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestGymSettingsMissingExtraMalformedFields:
    """3. Missing, Extra & Malformed Fields, Privilege Escalation / Mass Assignment."""

    def test_empty_bodies(self, auth_client, test_gym):
        # Empty PATCH settings -> valid partial update (no-op), returns current settings
        res = auth_client.patch(f"{reverse('gyms_v1:gym-settings')}?gym_id={test_gym.id}", {}, format="json")
        assert res.status_code == status.HTTP_200_OK

        # Empty POST blocked-users -> invalid (missing user_id)
        res_b = auth_client.post(f"{reverse('gyms_v1:gym-settings-blocked-users')}?gym_id={test_gym.id}", {}, format="json")
        assert res_b.status_code == status.HTTP_400_BAD_REQUEST

        # Empty POST access-control -> invalid (missing action)
        res_a = auth_client.post(f"{reverse('gyms_v1:gym-settings-access-control')}?gym_id={test_gym.id}", {}, format="json")
        assert res_a.status_code == status.HTTP_400_BAD_REQUEST

    def test_100_garbage_fields_injection(self, auth_client, test_gym):
        garbage_payload = {f"garbage_field_{i}": f"value_{i}" for i in range(120)}
        garbage_payload["dark_mode"] = True

        res = auth_client.patch(
            f"{reverse('gyms_v1:gym-settings')}?gym_id={test_gym.id}",
            garbage_payload,
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["dark_mode"] is True
        for key in garbage_payload:
            if key != "dark_mode":
                assert key not in res.data

    def test_read_only_and_server_controlled_fields_mass_assignment(self, auth_client, test_gym):
        original_settings = test_gym.settings
        malicious_payload = {
            "id": str(uuid.uuid4()),
            "gym_id": str(uuid.uuid4()),
            "deactivated_at": "2020-01-01T00:00:00Z",
            "deleted_at": "2020-01-01T00:00:00Z",
            "created_at": "2020-01-01T00:00:00Z",
            "updated_at": "2020-01-01T00:00:00Z",
            "language": "es",
        }
        res = auth_client.patch(
            f"{reverse('gyms_v1:gym-settings')}?gym_id={test_gym.id}",
            malicious_payload,
            format="json",
        )
        assert res.status_code == status.HTTP_200_OK
        # ID and gym_id must NOT be altered
        assert res.data["id"] == str(original_settings.id)
        assert res.data["gym_id"] == str(test_gym.id)
        assert res.data["deactivated_at"] is None
        assert res.data["deleted_at"] is None
        assert res.data["language"] == "es"


@pytest.mark.django_db
class TestGymSettingsFormatSpecificInvalidInputs:
    """4. Format-Specific Invalid Inputs (UUIDs, enums, dates)."""

    def test_invalid_uuid_inputs(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings-blocked-users")

        invalid_uuids = [
            "not-a-uuid",
            "12345",
            "g7b48312-d922-4416-bc57-22f3068593a1",  # Invalid hex char 'g'
            "0000-0000-0000",
            "e7b48312_d922_4416_bc57_22f3068593a1",  # Underscores
            "",
            "   ",
        ]
        for bad_uuid in invalid_uuids:
            res = auth_client.post(f"{url}?gym_id={test_gym.id}", {"user_id": bad_uuid}, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_existent_uuid_user_block_returns_404(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings-blocked-users")
        random_uuid = str(uuid.uuid4())
        res = auth_client.post(f"{url}?gym_id={test_gym.id}", {"user_id": random_uuid}, format="json")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_invalid_enums_rejected(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings")

        invalid_enum_payloads = [
            {"who_can_message": "unknown_value"},
            {"who_can_message": "EVERYONE"},  # uppercase
            {"who_can_send_joining_request": "all"},
            {"who_can_see_members": "public"},
            {"who_can_see_following": "nobody"},
            {"posts_age_restriction": "21_plus"},
            {"posts_age_restriction": "under_18"},
        ]
        for p in invalid_enum_payloads:
            res = auth_client.patch(f"{url}?gym_id={test_gym.id}", p, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_access_control_actions_rejected(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings-access-control")

        invalid_actions = [
            "destroy",
            "nuke",
            "drop",
            "DELETE",
            "DEACTIVATE",
            "",
            "   ",
            "123",
        ]
        for act in invalid_actions:
            res = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": act}, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestGymSettingsQueryParametersAndSearch:
    """5. Query Parameters, Filters, Search & Injection Testing."""

    def test_missing_or_invalid_gym_id_param(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings")

        # 1. Missing gym_id query param and no gym token context
        res_missing = auth_client.get(url)
        assert res_missing.status_code == status.HTTP_400_BAD_REQUEST

        # 2. Invalid UUID format
        for bad_id in ["not-a-uuid", "123", "abc-xyz", "null", "undefined"]:
            res_bad = auth_client.get(f"{url}?gym_id={bad_id}")
            assert res_bad.status_code == status.HTTP_404_NOT_FOUND

        # 3. Non-existent valid UUID
        res_not_found = auth_client.get(f"{url}?gym_id={uuid.uuid4()}")
        assert res_not_found.status_code == status.HTTP_404_NOT_FOUND

    def test_search_users_to_block_adversarial_queries(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings-blocked-users-search")

        adversarial_searches = [
            # SQL Injection attempts
            "' OR 1=1 --",
            "\" OR \"\"=\"",
            "'; DROP TABLE users; --",
            "1' UNION SELECT NULL, NULL, NULL --",
            # XSS attempts
            "<script>alert(1)</script>",
            "<img src=x onerror=alert('xss')>",
            "javascript:alert(1)",
            # Path traversal
            "../../../../etc/passwd",
            # Unicode, Emojis, RTL
            "🏋️‍♂️ 🔥 🇧🇩 日本語 עִבְרִית",
            # Special chars
            "!@#$%^&*()_+{}|:\"<>?~`-=[]\\;',./",
            # Empty and whitespace
            "",
            "    ",
            "\t\n\r",
            # Very long string (10,000 characters)
            "A" * 10000,
        ]

        for q in adversarial_searches:
            res = auth_client.get(url, {"gym_id": str(test_gym.id), "q": q})
            assert res.status_code == status.HTTP_200_OK, f"Crashed on query: {q[:30]}..."
            assert isinstance(res.data, list)


@pytest.mark.django_db
class TestGymSettingsAuthenticationAndPermissions:
    """6 & 7. Authentication, Authorization, Role & Scopes."""

    def test_unauthenticated_requests_denied(self, test_gym):
        unauth_client = APIClient()

        endpoints = [
            ("GET", reverse("gyms_v1:gym-settings")),
            ("PATCH", reverse("gyms_v1:gym-settings")),
            ("GET", reverse("gyms_v1:gym-settings-blocked-users")),
            ("POST", reverse("gyms_v1:gym-settings-blocked-users")),
            ("GET", reverse("gyms_v1:gym-settings-blocked-users-search")),
            ("POST", reverse("gyms_v1:gym-settings-access-control")),
        ]

        for method, ep in endpoints:
            handler = getattr(unauth_client, method.lower())
            res = handler(f"{ep}?gym_id={test_gym.id}")
            assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Failed on {method} {ep}"

    def test_malformed_and_invalid_tokens_rejected(self, test_gym):
        client = APIClient()
        bad_headers = [
            "Bearer invalid_token_12345",
            "Bearer ",
            "Token abcdef",
            "Basic YWxhZGRpbjpvcGVuc2VzYW1l",
            "Bearer null",
        ]

        for auth_h in bad_headers:
            client.credentials(HTTP_AUTHORIZATION=auth_h)
            res = client.get(f"{reverse('gyms_v1:gym-settings')}?gym_id={test_gym.id}")
            assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_staff_with_only_read_scope_cannot_edit(self, staff_client, test_gym, candidate_user):
        # 1. GET settings is allowed with gym_profile:read
        res_get = staff_client.get(f"{reverse('gyms_v1:gym-settings')}?gym_id={test_gym.id}")
        assert res_get.status_code == status.HTTP_200_OK

        # 2. PATCH settings requires gym_profile:edit -> 403 Forbidden
        res_patch = staff_client.patch(
            f"{reverse('gyms_v1:gym-settings')}?gym_id={test_gym.id}",
            {"dark_mode": True},
            format="json",
        )
        assert res_patch.status_code == status.HTTP_403_FORBIDDEN

        # 3. POST blocked users requires gym_profile:edit -> 403 Forbidden
        res_block = staff_client.post(
            f"{reverse('gyms_v1:gym-settings-blocked-users')}?gym_id={test_gym.id}",
            {"user_id": str(candidate_user.id)},
            format="json",
        )
        assert res_block.status_code == status.HTTP_403_FORBIDDEN

        # 4. POST access control requires gym_profile:edit -> 403 Forbidden
        res_act = staff_client.post(
            f"{reverse('gyms_v1:gym-settings-access-control')}?gym_id={test_gym.id}",
            {"action": "deactivate"},
            format="json",
        )
        assert res_act.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestGymSettingsIDORAndCrossTenantIsolation:
    """8. IDOR & Cross-Gym Data Isolation."""

    def test_cross_tenant_settings_isolation(self, auth_client, other_client, test_gym, other_gym):
        settings_url = reverse("gyms_v1:gym-settings")

        # auth_client owns test_gym, other_client owns other_gym

        # 1. auth_client cannot read other_gym settings
        res1 = auth_client.get(f"{settings_url}?gym_id={other_gym.id}")
        assert res1.status_code == status.HTTP_403_FORBIDDEN

        # 2. auth_client cannot modify other_gym settings
        res2 = auth_client.patch(
            f"{settings_url}?gym_id={other_gym.id}",
            {"language": "fr"},
            format="json",
        )
        assert res2.status_code == status.HTTP_403_FORBIDDEN

        # 3. other_client cannot modify test_gym settings
        res3 = other_client.patch(
            f"{settings_url}?gym_id={test_gym.id}",
            {"dark_mode": True},
            format="json",
        )
        assert res3.status_code == status.HTTP_403_FORBIDDEN

    def test_cross_tenant_blocking_isolation(self, auth_client, other_client, test_gym, other_gym, candidate_user):
        block_url = reverse("gyms_v1:gym-settings-blocked-users")

        # 1. other_client cannot block a user on test_gym
        res = other_client.post(
            f"{block_url}?gym_id={test_gym.id}",
            {"user_id": str(candidate_user.id)},
            format="json",
        )
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # 2. Block candidate_user on test_gym
        res_ok = auth_client.post(
            f"{block_url}?gym_id={test_gym.id}",
            {"user_id": str(candidate_user.id), "reason": "Test Gym Block"},
            format="json",
        )
        assert res_ok.status_code == status.HTTP_201_CREATED

        # 3. other_client cannot unblock candidate_user from test_gym
        detail_url = reverse("gyms_v1:gym-settings-blocked-user-detail", kwargs={"user_id": candidate_user.id})
        res_unblock_other = other_client.delete(f"{detail_url}?gym_id={test_gym.id}")
        assert res_unblock_other.status_code == status.HTTP_403_FORBIDDEN

        # 4. other_client attempting to unblock candidate_user on other_gym (where they are NOT blocked) -> 404
        res_unblock_other_gym = other_client.delete(f"{detail_url}?gym_id={other_gym.id}")
        assert res_unblock_other_gym.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestGymSettingsBusinessLogicAndStateTransitions:
    """9. Business Logic & State Transitions."""

    def test_cannot_block_gym_owner(self, auth_client, test_gym, owner_user):
        url = reverse("gyms_v1:gym-settings-blocked-users")
        res = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"user_id": str(owner_user.id)},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "owner cannot be blocked" in str(res.data)

    def test_blocking_same_user_twice_is_idempotent(self, auth_client, test_gym, candidate_user):
        url = reverse("gyms_v1:gym-settings-blocked-users")

        # First block
        res1 = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"user_id": str(candidate_user.id), "reason": "First"},
            format="json",
        )
        assert res1.status_code == status.HTTP_201_CREATED

        # Second block on same user -> Should succeed idempotently, not 500 or duplicate key crash
        res2 = auth_client.post(
            f"{url}?gym_id={test_gym.id}",
            {"user_id": str(candidate_user.id), "reason": "Second"},
            format="json",
        )
        assert res2.status_code == status.HTTP_201_CREATED
        assert GymBlockedUser.objects.filter(gym=test_gym, user=candidate_user).count() == 1

    def test_unblocking_user_twice_returns_404(self, auth_client, test_gym, candidate_user):
        block_user_for_gym(gym=test_gym, user_id=str(candidate_user.id))

        detail_url = reverse("gyms_v1:gym-settings-blocked-user-detail", kwargs={"user_id": candidate_user.id})

        # First unblock -> 200 OK
        res1 = auth_client.delete(f"{detail_url}?gym_id={test_gym.id}")
        assert res1.status_code == status.HTTP_200_OK

        # Second unblock -> 404 Not Found (no 500)
        res2 = auth_client.delete(f"{detail_url}?gym_id={test_gym.id}")
        assert res2.status_code == status.HTTP_404_NOT_FOUND

    def test_access_control_cyclic_transitions(self, auth_client, test_gym):
        url = reverse("gyms_v1:gym-settings-access-control")

        # Deactivate -> Reactivate -> Deactivate
        auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "deactivate"}, format="json")
        test_gym.settings.refresh_from_db()
        assert test_gym.settings.is_deactivated is True
        assert test_gym.settings.deactivated_at is not None

        auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "reactivate"}, format="json")
        test_gym.settings.refresh_from_db()
        assert test_gym.settings.is_deactivated is False
        assert test_gym.settings.deactivated_at is None

        # Repeat action: Reactivate again when already active -> idempotent, no error
        res_repeat = auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "reactivate"}, format="json")
        assert res_repeat.status_code == status.HTTP_200_OK
        assert res_repeat.data["is_deactivated"] is False

        # Unpublish -> Publish -> Repeat Publish
        auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "unpublish"}, format="json")
        test_gym.settings.refresh_from_db()
        assert test_gym.settings.is_published is False
        assert test_gym.settings.unpublished_at is not None

        auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "publish"}, format="json")
        test_gym.settings.refresh_from_db()
        assert test_gym.settings.is_published is True
        assert test_gym.settings.unpublished_at is None

        # Delete -> Restore -> Repeat Restore
        auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "delete"}, format="json")
        test_gym.settings.refresh_from_db()
        assert test_gym.settings.is_deleted is True
        assert test_gym.settings.deleted_at is not None

        auth_client.post(f"{url}?gym_id={test_gym.id}", {"action": "restore"}, format="json")
        test_gym.settings.refresh_from_db()
        assert test_gym.settings.is_deleted is False
        assert test_gym.settings.deleted_at is None


@pytest.mark.django_db
class TestGymSettingsHTTPMethodValidation:
    """10. Unsupported HTTP Methods."""

    def test_unsupported_methods_return_405(self, auth_client, test_gym, candidate_user):
        url_settings = reverse("gyms_v1:gym-settings")
        url_blocked = reverse("gyms_v1:gym-settings-blocked-users")
        url_search = reverse("gyms_v1:gym-settings-blocked-users-search")
        url_action = reverse("gyms_v1:gym-settings-access-control")
        url_detail = reverse("gyms_v1:gym-settings-blocked-user-detail", kwargs={"user_id": candidate_user.id})

        unsupported = [
            # Settings: Only GET and PATCH allowed
            (auth_client.post, f"{url_settings}?gym_id={test_gym.id}"),
            (auth_client.put, f"{url_settings}?gym_id={test_gym.id}"),
            (auth_client.delete, f"{url_settings}?gym_id={test_gym.id}"),
            # Blocked list: Only GET and POST allowed
            (auth_client.put, f"{url_blocked}?gym_id={test_gym.id}"),
            (auth_client.patch, f"{url_blocked}?gym_id={test_gym.id}"),
            (auth_client.delete, f"{url_blocked}?gym_id={test_gym.id}"),
            # Search: Only GET allowed
            (auth_client.post, f"{url_search}?gym_id={test_gym.id}"),
            (auth_client.put, f"{url_search}?gym_id={test_gym.id}"),
            (auth_client.delete, f"{url_search}?gym_id={test_gym.id}"),
            # Access Control: Only POST allowed
            (auth_client.get, f"{url_action}?gym_id={test_gym.id}"),
            (auth_client.put, f"{url_action}?gym_id={test_gym.id}"),
            (auth_client.delete, f"{url_action}?gym_id={test_gym.id}"),
            # Detail: Only DELETE allowed
            (auth_client.get, f"{url_detail}?gym_id={test_gym.id}"),
            (auth_client.post, f"{url_detail}?gym_id={test_gym.id}"),
            (auth_client.put, f"{url_detail}?gym_id={test_gym.id}"),
            (auth_client.patch, f"{url_detail}?gym_id={test_gym.id}"),
        ]

        for method_fn, endpoint in unsupported:
            res = method_fn(endpoint)
            assert res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, f"Expected 405 on {endpoint}, got {res.status_code}"
