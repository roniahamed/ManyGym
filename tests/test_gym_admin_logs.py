import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.utils import timezone

from apps.users.models import User
from apps.gyms.models import Gym, GymAdminLog
from apps.gyms.services import (
    create_gym,
    log_admin_action,
    apply_access_control_action,
    block_user_for_gym,
)
from apps.gyms.selectors import (
    list_admin_logs,
    get_admin_log_by_id,
    get_admin_logs_metrics,
)
from apps.access_control.services import (
    seed_default_permissions_and_roles,
    invite_staff_member,
)
from apps.access_control.models import Role
from apps.posts.services.post_services import create_post
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    AdminLogCategory,
    AdminLogActionType,
)


@pytest.fixture
def owner_user(db):
    return User.objects.create_user(
        email="sarah.ahmed@example.com",
        password="SecurePassword123!",
        first_name="Sarah",
        last_name="Ahmed",
        is_verified=True,
    )


@pytest.fixture
def second_user(db):
    return User.objects.create_user(
        email="karim.hasan@example.com",
        password="SecurePassword123!",
        first_name="Karim",
        last_name="Hasan",
        is_verified=True,
    )


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        email="rafi.islam@example.com",
        password="SecurePassword123!",
        first_name="Rafi",
        last_name="Islam",
        is_verified=True,
    )


@pytest.fixture
def unauthorized_user(db):
    return User.objects.create_user(
        email="unauthorized@example.com",
        password="SecurePassword123!",
        first_name="Eve",
        last_name="Hacker",
        is_verified=True,
    )


@pytest.fixture
def test_gym(owner_user):
    return create_gym(owner_user=owner_user, name="Metro Fitness Club")


@pytest.fixture
def auth_client(owner_user):
    tokens = issue_context_token(owner_user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client


@pytest.fixture
def unauth_client():
    return APIClient()


@pytest.mark.django_db
class TestGymAdminLogs:

    def test_log_admin_action_service_and_model(self, test_gym, owner_user):
        """Tests manual logging of administrative actions matching UI prompt specification."""
        log_entry = log_admin_action(
            gym=test_gym,
            actor=owner_user,
            action="Updated page information",
            action_type=AdminLogActionType.UPDATE_PAGE_INFO,
            details="Changed the page description",
            category=AdminLogCategory.GYM_PROFILE,
            target_type="gym",
            target_id=str(test_gym.id),
        )

        assert log_entry is not None
        assert log_entry.actor == owner_user
        assert log_entry.actor_name == "Sarah Ahmed"
        assert log_entry.actor_email == "sarah.ahmed@example.com"
        assert log_entry.action == "Updated page information"
        assert log_entry.details == "Changed the page description"
        assert log_entry.category == AdminLogCategory.GYM_PROFILE
        assert log_entry.formatted_date_time != ""
        assert "Sarah Ahmed" in str(log_entry)

    def test_list_admin_logs_filtering_and_search(self, test_gym, owner_user, second_user):
        """Tests selector query filters across category, action_type, actor, and search."""
        log_admin_action(
            gym=test_gym,
            actor=owner_user,
            action="Updated page information",
            action_type=AdminLogActionType.UPDATE_PAGE_INFO,
            details="Changed the page description",
            category=AdminLogCategory.GYM_PROFILE,
        )
        log_admin_action(
            gym=test_gym,
            actor=second_user,
            action="Published a post",
            action_type=AdminLogActionType.PUBLISH_POST,
            details="“Our new collection is here”",
            category=AdminLogCategory.POSTS,
        )
        log_admin_action(
            gym=test_gym,
            actor=owner_user,
            action="Added an admin",
            action_type=AdminLogActionType.ADD_ADMIN,
            details="Added Rafi as Editor",
            category=AdminLogCategory.ACCESS_CONTROL,
        )

        # 1. Total logs
        logs, total, pages = list_admin_logs(gym=test_gym)
        assert total == 3
        assert len(logs) == 3

        # 2. Filter by category
        posts_logs, posts_total, _ = list_admin_logs(gym=test_gym, category=AdminLogCategory.POSTS)
        assert posts_total == 1
        assert posts_logs[0].action == "Published a post"

        # 3. Filter by actor_id
        owner_logs, owner_total, _ = list_admin_logs(gym=test_gym, actor_id=str(owner_user.id))
        assert owner_total == 2

        # 4. Search query
        search_logs, search_total, _ = list_admin_logs(gym=test_gym, search="collection")
        assert search_total == 1
        assert "collection" in search_logs[0].details

    def test_admin_logs_metrics(self, test_gym, owner_user, second_user):
        """Tests metrics aggregation: totals, today count, category breakdown, and recents."""
        log_admin_action(
            gym=test_gym,
            actor=owner_user,
            action="Updated page information",
            category=AdminLogCategory.GYM_PROFILE,
        )
        log_admin_action(
            gym=test_gym,
            actor=second_user,
            action="Published a post",
            category=AdminLogCategory.POSTS,
        )

        metrics = get_admin_logs_metrics(gym=test_gym)
        assert metrics["total_logs"] == 2
        assert metrics["logs_today"] == 2
        assert metrics["by_category"].get(AdminLogCategory.GYM_PROFILE) == 1
        assert metrics["by_category"].get(AdminLogCategory.POSTS) == 1
        assert len(metrics["recent_logs"]) == 2

    def test_api_list_admin_logs(self, auth_client, test_gym, owner_user):
        """Tests GET /api/v1/gyms/logs/admin/ endpoint."""
        log_admin_action(
            gym=test_gym,
            actor=owner_user,
            action="Changed page visibility",
            action_type=AdminLogActionType.CHANGE_PAGE_VISIBILITY,
            details="Public → Unpublished",
            category=AdminLogCategory.VISIBILITY,
        )

        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}")

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["count"] == 1
        assert data["results"][0]["action"] == "Changed page visibility"
        assert data["results"][0]["details"] == "Public → Unpublished"
        assert data["results"][0]["admin"]["full_name"] == "Sarah Ahmed"
        assert "formatted_date_time" in data["results"][0]

    def test_api_record_admin_log(self, auth_client, test_gym):
        """Tests POST /api/v1/gyms/logs/admin/ endpoint."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        payload = {
            "action": "Updated page information",
            "action_type": AdminLogActionType.UPDATE_PAGE_INFO,
            "category": AdminLogCategory.GYM_PROFILE,
            "details": "Changed the page description",
        }
        resp = auth_client.post(f"{url}?gym_id={test_gym.id}", payload, format="json")

        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["action"] == "Updated page information"
        assert data["details"] == "Changed the page description"
        assert data["admin"]["full_name"] == "Sarah Ahmed"

    def test_api_admin_log_detail(self, auth_client, test_gym, owner_user):
        """Tests GET /api/v1/gyms/logs/admin/<id>/ endpoint."""
        log_entry = log_admin_action(
            gym=test_gym,
            actor=owner_user,
            action="Published a post",
            details="“Our new collection is here”",
            category=AdminLogCategory.POSTS,
        )

        url = reverse("gyms_v1:gym-admin-log-detail", kwargs={"log_id": log_entry.id})
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}")

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["id"] == str(log_entry.id)
        assert data["action"] == "Published a post"
        assert data["details"] == "“Our new collection is here”"

    def test_api_admin_logs_metrics(self, auth_client, test_gym, owner_user):
        """Tests GET /api/v1/gyms/logs/admin/metrics/ endpoint."""
        log_admin_action(
            gym=test_gym,
            actor=owner_user,
            action="Updated page information",
            category=AdminLogCategory.GYM_PROFILE,
        )

        url = reverse("gyms_v1:gym-admin-logs-metrics")
        resp = auth_client.get(f"{url}?gym_id={test_gym.id}")

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["total_logs"] == 1
        assert data["logs_today"] == 1
        assert AdminLogCategory.GYM_PROFILE in data["by_category"]
        assert len(data["recent_logs"]) == 1

    def test_api_admin_logs_action_types(self, auth_client):
        """Tests GET /api/v1/gyms/logs/admin/actions/ endpoint."""
        url = reverse("gyms_v1:gym-admin-logs-actions")
        resp = auth_client.get(url)

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert "categories" in data
        assert "action_types" in data
        assert any(c["value"] == AdminLogCategory.GYM_PROFILE for c in data["categories"])
        assert any(a["value"] == AdminLogActionType.UPDATE_PAGE_INFO for a in data["action_types"])

    def test_unauthorized_user_forbidden(self, unauthorized_user, test_gym):
        """Verifies unauthorized user cannot access gym admin logs."""
        tokens = issue_context_token(unauthorized_user, context_type=TokenContextType.PERSONAL)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = client.get(f"{url}?gym_id={test_gym.id}")
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_user_rejected(self, unauth_client, test_gym):
        """Verifies unauthenticated request returns 401 Unauthorized."""
        url = reverse("gyms_v1:gym-admin-logs-list")
        resp = unauth_client.get(f"{url}?gym_id={test_gym.id}")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_automatic_logging_on_visibility_change(self, test_gym, owner_user):
        """Verifies apply_access_control_action automatically creates an admin log."""
        apply_access_control_action(gym=test_gym, action="unpublish", user=owner_user)

        logs = GymAdminLog.objects.filter(gym=test_gym, action_type=AdminLogActionType.CHANGE_PAGE_VISIBILITY)
        assert logs.exists()
        latest = logs.first()
        assert latest.action == "Changed page visibility"
        assert latest.details == "Public → Unpublished"

    def test_automatic_logging_on_post_publish(self, test_gym, owner_user):
        """Verifies create_post automatically records an admin log."""
        create_post(
            gym=test_gym,
            author_user=owner_user,
            content_text="Our new collection is here",
        )

        logs = GymAdminLog.objects.filter(gym=test_gym, action_type=AdminLogActionType.PUBLISH_POST)
        assert logs.exists()
        latest = logs.first()
        assert latest.action == "Published a post"
        assert "Our new collection is here" in latest.details

    def test_automatic_logging_on_staff_invitation(self, test_gym, staff_user):
        """Verifies invite_staff_member automatically records an admin log."""
        seed_default_permissions_and_roles()
        admin_role = Role.objects.get(slug="administrator", gym__isnull=True)

        invite_staff_member(gym=test_gym, user_email=staff_user.email, role_id=str(admin_role.id))

        logs = GymAdminLog.objects.filter(gym=test_gym, action_type=AdminLogActionType.ADD_ADMIN)
        assert logs.exists()
        latest = logs.first()
        assert latest.action == "Added an admin"
        assert "Rafi Islam" in latest.details

    def test_automatic_logging_on_blocking_user(self, test_gym, owner_user, second_user):
        """Verifies block_user_for_gym automatically records an admin log."""
        block_user_for_gym(
            gym=test_gym,
            user_id=str(second_user.id),
            blocked_by_user=owner_user,
            reason="Spam activity",
        )

        logs = GymAdminLog.objects.filter(gym=test_gym, action_type=AdminLogActionType.BLOCK_USER)
        assert logs.exists()
        latest = logs.first()
        assert latest.action == "Blocked a user"
        assert second_user.email in latest.details

    def test_admin_logs_n_plus_one_prevention(self, auth_client, test_gym, owner_user, second_user, django_assert_num_queries):
        """Ensures listing 25 logs executes in a constant, minimal number of queries."""
        # Create 25 log entries
        for i in range(25):
            actor = owner_user if i % 2 == 0 else second_user
            log_admin_action(
                gym=test_gym,
                actor=actor,
                action=f"Action {i}",
                details=f"Details {i}",
                category=AdminLogCategory.GENERAL,
            )

        url = reverse("gyms_v1:gym-admin-logs-list")
        # With select_related on actor and actor__profile, query count remains constant
        with django_assert_num_queries(4):
            # 1. Resolve gym context
            # 2. Scope check (user is owner, so fast lookup or token auth)
            # 3. COUNT query for pagination
            # 4. SELECT logs with JOIN on users and user_profiles
            resp = auth_client.get(f"{url}?gym_id={test_gym.id}&page_size=20")
            assert resp.status_code == status.HTTP_200_OK
            assert len(resp.json()["results"]) == 20

    def test_export_admin_logs_csv_and_json(self, auth_client, test_gym, owner_user):
        """Tests GET /api/v1/gyms/logs/admin/export/ endpoint in CSV and JSON formats."""
        log_admin_action(
            gym=test_gym,
            actor=owner_user,
            action="Updated page information",
            details="Changed the page description",
            category=AdminLogCategory.GYM_PROFILE,
        )

        url = reverse("gyms_v1:gym-admin-logs-export")

        # 1. Test CSV format
        resp_csv = auth_client.get(f"{url}?gym_id={test_gym.id}&format=csv")
        assert resp_csv.status_code == status.HTTP_200_OK
        assert "text/csv" in resp_csv["Content-Type"]
        assert "attachment; filename=" in resp_csv["Content-Disposition"]
        content = resp_csv.content.decode("utf-8")
        assert "Sarah Ahmed" in content
        assert "Updated page information" in content
        assert "Changed the page description" in content

        # 2. Test JSON format
        resp_json = auth_client.get(f"{url}?gym_id={test_gym.id}&format=json")
        assert resp_json.status_code == status.HTTP_200_OK
        data = resp_json.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["action"] == "Updated page information"

    def test_automatic_logging_on_gallery_media(self, test_gym):
        """Verifies gallery media upload and deletion records admin logs."""
        from apps.gyms.services.gallery_services import add_gallery_item, delete_gallery_item

        item = add_gallery_item(
            gym=test_gym,
            media_url="https://example.com/photo.jpg",
            caption="Front entrance",
        )
        logs = GymAdminLog.objects.filter(gym=test_gym, action_type=AdminLogActionType.ADD_GALLERY_MEDIA)
        assert logs.exists()

        delete_gallery_item(gym=test_gym, item_id=str(item.id))
        del_logs = GymAdminLog.objects.filter(gym=test_gym, action_type=AdminLogActionType.DELETE_GALLERY_MEDIA)
        assert del_logs.exists()

    def test_automatic_logging_on_lead_lifecycle(self, test_gym):
        """Verifies lead creation, stage update, and deletion record admin logs."""
        from apps.leads.services.lead_services import create_lead, update_lead_stage, delete_lead
        from common.enums import LeadStageEnum

        lead = create_lead(
            gym=test_gym,
            first_name="Jane",
            last_name="Doe",
            phone="01700000000",
            email="jane@example.com",
        )
        logs = GymAdminLog.objects.filter(gym=test_gym, action_type=AdminLogActionType.CREATE_LEAD)
        assert logs.exists()

        update_lead_stage(lead=lead, new_stage=LeadStageEnum.CONTACTED)
        stage_logs = GymAdminLog.objects.filter(gym=test_gym, action_type=AdminLogActionType.UPDATE_LEAD_STAGE)
        assert stage_logs.exists()

        delete_lead(lead=lead)
        del_logs = GymAdminLog.objects.filter(gym=test_gym, action_type=AdminLogActionType.DELETE_LEAD)
        assert del_logs.exists()

    def test_automatic_logging_on_routine_template(self, test_gym):
        """Verifies routine template creation and deletion record admin logs."""
        from apps.routines.services.template_services import create_routine_template, delete_routine_template

        template = create_routine_template(
            gym=test_gym,
            template_name="Strength Builder 3-Day",
        )
        logs = GymAdminLog.objects.filter(gym=test_gym, action_type=AdminLogActionType.CREATE_ROUTINE)
        assert logs.exists()

        delete_routine_template(template=template)
        del_logs = GymAdminLog.objects.filter(gym=test_gym, action_type=AdminLogActionType.DELETE_ROUTINE)
        assert del_logs.exists()


