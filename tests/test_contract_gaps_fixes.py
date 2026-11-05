import io
import uuid
from datetime import date
import pytest
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient
import yaml

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym, GymSetting, GymGallery
from apps.gyms.services import create_gym, add_gallery_item
from apps.access_control.models import Role, GymStaffAssignment
from apps.members.models import Member, MemberSubscription, MemberPayment
from apps.memberships.models import MembershipPlan
from apps.posts.models import GymPost
from apps.posts.services import create_post
from apps.authentication.services import issue_context_token, is_token_revoked
from common.enums import TokenContextType, MemberJoiningStatus, StaffStatus, PlanStatusEnum, PlanTypeEnum


def _make_dummy_image(name="test.png", fmt="PNG", size=(100, 100), color="blue"):
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format=fmt)
    buf.seek(0)
    return SimpleUploadedFile(name, buf.read(), content_type=f"image/{fmt.lower()}")


@pytest.fixture(autouse=True)
def configure_media_root(settings, tmp_path):
    media_path = tmp_path / "media"
    media_path.mkdir(parents=True, exist_ok=True)
    settings.MEDIA_ROOT = str(media_path)
    return media_path


@pytest.fixture
def owner_user(db):
    user = User.objects.create_user(
        email="owner.gaps@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Owner",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, date_of_birth=date(1990, 1, 1))
    return user


@pytest.fixture
def gym_instance(db, owner_user):
    gym = create_gym(
        owner_user=owner_user,
        name="Contract Gaps Gym",
        primary_type="crossfit",
        timezone="UTC",
    )
    return gym


@pytest.fixture
def gym_auth_client(db, owner_user, gym_instance):
    tokens = issue_context_token(owner_user, context_type=TokenContextType.GYM, gym=gym_instance)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    client.tokens = tokens
    return client


@pytest.fixture
def personal_auth_client(db, owner_user):
    tokens = issue_context_token(owner_user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    client.tokens = tokens
    return client


# =========================================================================
# Issue 18: HTTP Method Checked Before Authentication (405 instead of 401)
# =========================================================================
@pytest.mark.django_db
def test_issue18_http_method_precedence_over_auth():
    unauth_client = APIClient()
    # GET on POST-only protected endpoint (/api/v1/auth/logout/)
    res_logout = unauth_client.get("/api/v1/auth/logout/")
    assert res_logout.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert "POST" in res_logout.headers.get("Allow", "")
    assert res_logout.json().get("code") == "METHOD_NOT_ALLOWED"

    # POST on GET-only protected endpoint (/api/v1/members/metrics/)
    res_metrics = unauth_client.post("/api/v1/members/metrics/")
    assert res_metrics.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
    assert "GET" in res_metrics.headers.get("Allow", "")
    assert res_metrics.json().get("code") == "METHOD_NOT_ALLOWED"


# =========================================================================
# Issue 17b: Context Switching Invalidates Previous Token
# =========================================================================
@pytest.mark.django_db
def test_issue17b_context_switch_invalidates_previous_token(gym_auth_client, owner_user, gym_instance):
    old_access = gym_auth_client.tokens["access"]
    assert not is_token_revoked(old_access)

    # Switch to personal context
    res = gym_auth_client.post("/api/v1/auth/switch-context/", data={"context_type": "personal"}, format="json")
    assert res.status_code == status.HTTP_200_OK

    # Previous token is now revoked
    assert is_token_revoked(old_access)

    # Calling a protected endpoint with the old token now fails with 401
    old_client = APIClient()
    old_client.credentials(HTTP_AUTHORIZATION=f"Bearer {old_access}")
    res_me = old_client.get("/api/v1/auth/me/")
    assert res_me.status_code == status.HTTP_401_UNAUTHORIZED
    assert "revoked" in str(res_me.json())


# =========================================================================
# Issue 2: Post Media File Upload Accepts Singular 'file' Field Name
# =========================================================================
@pytest.mark.django_db
def test_issue2_posts_media_file_singular_upload(gym_auth_client, gym_instance):
    img = _make_dummy_image("post_photo.png")
    payload = {
        "content_text": "Announcing our new strength area!",
        "privacy": "public",
        "file": img,
    }
    response = gym_auth_client.post("/api/v1/posts/", data=payload, format="multipart")
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["content_text"] == "Announcing our new strength area!"
    assert len(data.get("media_attachments", [])) == 1
    media_url = data["media_attachments"][0]["media_url"]
    assert media_url.startswith("http://") or media_url.startswith("https://")


# =========================================================================
# Issue 2b: Uploaded Media Returns Absolute URLs
# =========================================================================
@pytest.mark.django_db
def test_issue2b_gallery_and_post_media_absolute_urls(gym_auth_client, gym_instance):
    img = _make_dummy_image("gym_gallery_equipment.png")
    payload = {
        "file": img,
        "media_type": "picture",
        "category": "equipment",
        "caption": "Calibrated powerlifting plates",
    }
    res = gym_auth_client.post("/api/v1/gyms/gallery/", data=payload, format="multipart")
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["media_url"].startswith("http://") or data["media_url"].startswith("https://")
    assert data["resolved_media_url"].startswith("http://") or data["resolved_media_url"].startswith("https://")


# =========================================================================
# Issue 7: GET /posts/ Publicly Usable Without gym_id
# =========================================================================
@pytest.mark.django_db
def test_issue7_posts_feed_public_access_without_gym_id(gym_instance, owner_user):
    create_post(
        gym=gym_instance,
        author_user=owner_user,
        content_text="Welcome to Many Gym!",
        privacy="public",
    )
    unauth_client = APIClient()
    # Unauthenticated GET /api/v1/posts/ with no gym_id parameter
    res = unauth_client.get("/api/v1/posts/")
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert "results" in data
    assert len(data["results"]) >= 1
    assert data["results"][0]["content_text"] == "Welcome to Many Gym!"


# =========================================================================
# Issue 13: Updating Member joining_status via PATCH
# =========================================================================
@pytest.mark.django_db
def test_issue13_update_member_joining_status(gym_auth_client, gym_instance):
    member = Member.objects.create(
        gym=gym_instance,
        first_name="Jane",
        last_name="Doe",
        email="jane.doe@example.com",
        joining_status=MemberJoiningStatus.SENT_INVITATION,
    )
    assert member.joining_status == "sent_invitation"

    # PATCH to update joining_status to 'joined'
    res = gym_auth_client.patch(
        f"/api/v1/members/{member.id}/",
        data={"joining_status": "joined"},
        format="json",
    )
    assert res.status_code == status.HTTP_200_OK
    member.refresh_from_db()
    assert member.joining_status == "joined"


# =========================================================================
# Issue 14: Updating Staff Member role_id via PATCH
# =========================================================================
@pytest.mark.django_db
def test_issue14_update_staff_role(gym_auth_client, gym_instance):
    trainer_user = User.objects.create_user(
        email="staff.trainer@example.com",
        password="SecurePassword123!",
        first_name="Tom",
        last_name="Trainer",
        is_verified=True,
    )
    role_trainer, _ = Role.objects.get_or_create(name="Trainer", defaults={"slug": "trainer", "is_custom": False})
    role_admin, _ = Role.objects.get_or_create(name="Administrator", defaults={"slug": "administrator", "is_custom": False})

    assignment = GymStaffAssignment.objects.create(
        gym=gym_instance,
        user=trainer_user,
        role=role_trainer,
        status=StaffStatus.ACTIVE,
    )
    assert assignment.role.name == "Trainer"

    # PATCH to reassign role to Administrator
    res = gym_auth_client.patch(
        f"/api/v1/access-control/staff/{assignment.id}/",
        data={"role_id": str(role_admin.id)},
        format="json",
    )
    assert res.status_code == status.HTTP_200_OK
    assignment.refresh_from_db()
    assert assignment.role.name == "Administrator"


# =========================================================================
# Issue 15: DELETE /follows/ Accepts target_id in Query Param and Body
# =========================================================================
@pytest.mark.django_db
def test_issue15_delete_follow_with_query_param_and_body(personal_auth_client, owner_user):
    target_user = User.objects.create_user(
        email="target.follow@example.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Follow",
        is_verified=True,
    )
    # Follow via POST /api/v1/follows/
    res_follow = personal_auth_client.post(
        "/api/v1/follows/",
        data={"target_id": str(target_user.id)},
        format="json",
    )
    assert res_follow.status_code == status.HTTP_201_CREATED

    # Unfollow via DELETE /api/v1/follows/?target_id=<uuid>
    res_del_query = personal_auth_client.delete(f"/api/v1/follows/?target_id={target_user.id}")
    assert res_del_query.status_code == status.HTTP_200_OK
    assert res_del_query.json().get("is_following") is False

    # Follow again
    personal_auth_client.post("/api/v1/follows/", data={"target_id": str(target_user.id)}, format="json")

    # Unfollow via DELETE /api/v1/follows/ with JSON body
    res_del_body = personal_auth_client.delete(
        "/api/v1/follows/",
        data={"target_id": str(target_user.id)},
        format="json",
    )
    assert res_del_body.status_code == status.HTTP_200_OK
    assert res_del_body.json().get("is_following") is False


# =========================================================================
# Issue 29: Clear 409 Conflict Error Messages on Deletion
# =========================================================================
@pytest.mark.django_db
def test_issue29_clear_409_messages(gym_auth_client, gym_instance):
    # 1. Member with payment history
    member = Member.objects.create(
        gym=gym_instance,
        first_name="Alice",
        last_name="Ledger",
        email="ledger.alice@example.com",
    )
    plan = MembershipPlan.objects.create(
        gym=gym_instance,
        name="Gold Plan",
        plan_type=PlanTypeEnum.TIME_BASED,
        duration_unit="month",
        duration_value=1,
        price=100.00,
        plan_status=PlanStatusEnum.ACTIVE,
    )
    from datetime import timedelta
    sub = MemberSubscription.objects.create(
        member=member,
        plan=plan,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30),
    )
    MemberPayment.objects.create(
        member_subscription=sub,
        payment_date=date.today(),
        amount=100.00,
        payment_method="cash",
    )

    res_del_member = gym_auth_client.delete(f"/api/v1/members/{member.id}/")
    assert res_del_member.status_code == status.HTTP_409_CONFLICT
    assert "Members with payment history cannot be deleted" in res_del_member.json().get("message", "")

    # 2. Plan with subscription history
    res_del_plan = gym_auth_client.delete(f"/api/v1/plans/{plan.id}/")
    assert res_del_plan.status_code == status.HTTP_409_CONFLICT
    assert "Membership plans with subscription history cannot be deleted" in res_del_plan.json().get("message", "")


# =========================================================================
# Issue 31: Deleted Gym Excluded from accessible_gyms
# =========================================================================
@pytest.mark.django_db
def test_issue31_deleted_gym_excluded_from_accessible_gyms(gym_auth_client, personal_auth_client, gym_instance):
    # Verify gym is in accessible_gyms initially
    res_me = personal_auth_client.get("/api/v1/auth/me/")
    assert res_me.status_code == status.HTTP_200_OK
    gym_ids = [g["gym_id"] for g in res_me.json().get("accessible_gyms", [])]
    assert str(gym_instance.id) in gym_ids

    # Soft delete gym via access-control action
    res_del = gym_auth_client.post(
        "/api/v1/gyms/settings/access-control/",
        data={"action": "delete", "password": "SecurePassword123!", "confirmation": "delete"},
        format="json",
    )
    assert res_del.status_code == status.HTTP_200_OK

    # Verify deleted gym is now excluded from accessible_gyms
    res_me_after = personal_auth_client.get("/api/v1/auth/me/")
    assert res_me_after.status_code == status.HTTP_200_OK
    gym_ids_after = [g["gym_id"] for g in res_me_after.json().get("accessible_gyms", [])]
    assert str(gym_instance.id) not in gym_ids_after


# =========================================================================
# OpenAPI Schema Verifications (Issues 5, 6, 8, 16, 22c, 30)
# =========================================================================
@pytest.mark.django_db
def test_openapi_schema_contract_fixes():
    client = APIClient()
    res = client.get("/api/v1/schema/")
    assert res.status_code == status.HTTP_200_OK
    data = yaml.safe_load(res.content)
    paths = data.get("paths", {})
    schemas = data.get("components", {}).get("schemas", {})

    # Issue 5: Redundant alias paths deduplicated from schema
    assert "/api/v1/follows/" in paths
    assert "/api/v1/follows/{target_id}/" in paths
    assert "/api/v1/follow/" not in paths
    assert "/api/v1/auth/follow/" not in paths
    assert "/api/v1/users/register/" not in paths

    # Issue 6: Paginated envelopes for members, leads, and plans
    assert "$ref" in paths["/api/v1/members/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert "$ref" in paths["/api/v1/leads/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert "$ref" in paths["/api/v1/plans/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert "PaginatedMemberListList" in schemas
    assert "PaginatedLeadListList" in schemas
    assert "PaginatedMembershipPlanListList" in schemas

    # Issue 8 & 23: Permissions vocabulary documented with 9 topics
    perm_schema_ref = paths["/api/v1/access-control/permissions/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    perm_schema_name = perm_schema_ref.split("/")[-1]
    perm_schema = schemas[perm_schema_name]
    assert "properties" in perm_schema
    assert "Members" in perm_schema["properties"]
    assert "Studio" in perm_schema["properties"]
    assert "Reports" in perm_schema["properties"]

    # Issue 16: Plan metrics response schema
    plan_metrics_ref = paths["/api/v1/plans/metrics/"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert "MembershipPlanMetrics" in plan_metrics_ref
    assert "MembershipPlanMetrics" in schemas

    # Issue 22c: GymDetail location, opening_hours_count, gallery_count types
    gym_detail = schemas["GymDetail"]
    assert gym_detail["properties"]["location"]["allOf"][0]["$ref"] == "#/components/schemas/GymLocation"
    assert gym_detail["properties"]["opening_hours_count"]["type"] == "integer"
    assert gym_detail["properties"]["gallery_count"]["type"] == "integer"

    # Issue 30: GymAccessControlActionRequest declares password and confirmation
    action_schema = schemas.get("GymAccessControlActionRequest", {})
    if action_schema:
        assert "password" in action_schema.get("properties", {})
        assert "confirmation" in action_schema.get("properties", {})
