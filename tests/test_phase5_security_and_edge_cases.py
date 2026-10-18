import uuid
from decimal import Decimal
from datetime import date, timedelta
import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.utils import timezone

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym
from apps.gyms.services import create_gym
from apps.amenities.services import seed_amenity_catalog
from apps.access_control.models import Role, Permission, GymStaffAssignment
from apps.access_control.services import seed_default_permissions_and_roles
from apps.memberships.models import MembershipPlan
from apps.memberships.services import create_membership_plan
from apps.authentication.services import issue_context_token
from apps.members.models import Member
from apps.leads.models import (
    Lead,
    LeadCustomReasons,
    LeadFitnessGoals,
    LeadNextMove,
    LeadNotes,
)
from apps.leads.services import (
    create_lead,
    update_lead,
    update_lead_stage,
    schedule_next_move,
    complete_next_move,
    add_lead_note,
    convert_lead_to_member,
    create_custom_reason,
    delete_lead,
)
from apps.leads.selectors import (
    list_leads,
    get_lead_details,
    get_lead_by_id,
    list_custom_reasons,
    get_lead_metrics,
)
from common.enums import (
    TokenContextType,
    UserStatus,
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    LeadStageEnum,
    LeadSourceEnum,
    NotJoiningReasonStandard,
    FitnessGoalEnum,
    StaffStatus,
)
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    ResourceConflictError,
    PermissionDeniedError,
)


@pytest.fixture(autouse=True)
def setup_seeds(db):
    seed_amenity_catalog()
    seed_default_permissions_and_roles()


def create_user_with_tokens(email="test.phase5@manygym.com", is_verified=True, user_status=UserStatus.ACTIVE):
    user = User.objects.create_user(
        email=email,
        password="SecurePassword123!",
        first_name="Phase5",
        last_name="Tester",
        is_verified=is_verified,
        status=user_status,
    )
    UserProfile.objects.create(user=user)
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return user, client, tokens


def setup_gym_and_lead_context(owner_email="owner.phase5@manygym.com"):
    owner, client, _ = create_user_with_tokens(owner_email)
    gym = create_gym(owner_user=owner, name="Phase 5 CRM Gym")
    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    plan = create_membership_plan(
        gym=gym,
        name="Lead Pro Fitness Plan",
        description="Standard monthly gym membership plan for testing lead inquiries.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("120.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
        joining_fee=Decimal("15.00"),
    )

    # Create a staff member
    staff_user, _, _ = create_user_with_tokens(f"staff.{uuid.uuid4().hex[:8]}@manygym.com")
    staff_role = Role.objects.get(slug="trainer")
    staff_assignment = GymStaffAssignment.objects.create(
        gym=gym,
        user=staff_user,
        role=staff_role,
        status=StaffStatus.ACTIVE,
    )

    return {
        "owner": owner,
        "gym": gym,
        "plan": plan,
        "staff_user": staff_user,
        "staff_assignment": staff_assignment,
        "client": client,
        "tokens": tokens,
    }


# ==============================================================================
# 1. SERVICES & SELECTORS UNIT TESTS
# ==============================================================================

@pytest.mark.django_db
class TestLeadServices:

    def test_create_lead_success_with_email_and_goals(self):
        ctx = setup_gym_and_lead_context()
        lead = create_lead(
            gym=ctx["gym"],
            first_name="Alice",
            last_name="Walker",
            email="alice.walker@example.com",
            phone="+1234567890",
            interested_plan_id=ctx["plan"].id,
            assigned_staff_id=ctx["staff_assignment"].id,
            source=LeadSourceEnum.WALK_IN,
            stage=LeadStageEnum.NEW,
            expected_start_date=date.today() + timedelta(days=7),
            fitness_goals=[FitnessGoalEnum.STRENGTH, FitnessGoalEnum.MUSCLE_GAIN],
            initial_note="Walked in asking about free weights area.",
            author_staff_id=ctx["staff_assignment"].id,
        )

        assert lead.id is not None
        assert lead.full_name == "Alice Walker"
        assert lead.email == "alice.walker@example.com"
        assert lead.phone == "+1234567890"
        assert lead.interested_plan == ctx["plan"]
        assert lead.assigned_staff == ctx["staff_assignment"]
        assert lead.stage == LeadStageEnum.NEW
        assert lead.fitness_goals.count() == 2
        assert lead.notes.count() == 1
        assert "Walked in" in lead.notes.first().note_text

    def test_create_lead_phone_only_success(self):
        ctx = setup_gym_and_lead_context()
        lead = create_lead(
            gym=ctx["gym"],
            first_name="Bob",
            phone="+9876543210",
        )
        assert lead.id is not None
        assert lead.first_name == "Bob"
        assert lead.email is None
        assert lead.phone == "+9876543210"

    def test_create_lead_email_only_success(self):
        ctx = setup_gym_and_lead_context()
        lead = create_lead(
            gym=ctx["gym"],
            first_name="Charlie",
            email="charlie@example.com",
        )
        assert lead.id is not None
        assert lead.first_name == "Charlie"
        assert lead.phone is None
        assert lead.email == "charlie@example.com"

    def test_create_lead_missing_contact_fails(self):
        ctx = setup_gym_and_lead_context()
        with pytest.raises(DomainValidationError) as exc:
            create_lead(
                gym=ctx["gym"],
                first_name="NoContact",
            )
        assert "At least one contact method" in str(exc.value)

    def test_create_lead_missing_first_name_fails(self):
        ctx = setup_gym_and_lead_context()
        with pytest.raises(DomainValidationError) as exc:
            create_lead(
                gym=ctx["gym"],
                first_name="   ",
                phone="+123456",
            )
        assert "first name is required" in str(exc.value)

    def test_create_lead_invalid_email_fails(self):
        ctx = setup_gym_and_lead_context()
        with pytest.raises(DomainValidationError) as exc:
            create_lead(
                gym=ctx["gym"],
                first_name="InvalidEmail",
                email="not-an-email",
            )
        assert "valid email address" in str(exc.value)

    def test_create_lead_cross_tenant_plan_fails(self):
        ctx1 = setup_gym_and_lead_context()
        other_owner, _, _ = create_user_with_tokens("other.owner@manygym.com")
        other_gym = create_gym(owner_user=other_owner, name="Foreign Gym")
        other_plan = create_membership_plan(
            gym=other_gym,
            name="Foreign Plan",
            description="A plan from another gym to test cross-tenant boundary isolation.",
            plan_status=PlanStatusEnum.ACTIVE,
            plan_type=PlanTypeEnum.TIME_BASED,
            price=Decimal("99.00"),
            duration_value=1,
            duration_unit=DurationUnitEnum.MONTH,
        )

        with pytest.raises(DomainValidationError) as exc:
            create_lead(
                gym=ctx1["gym"],
                first_name="Attacker",
                phone="+12345",
                interested_plan_id=other_plan.id,
            )
        assert "Interested plan not found" in str(exc.value)

    def test_create_lead_not_joining_without_reason_fails(self):
        ctx = setup_gym_and_lead_context()
        with pytest.raises(DomainValidationError) as exc:
            create_lead(
                gym=ctx["gym"],
                first_name="Declined",
                phone="+12345",
                stage=LeadStageEnum.NOT_JOINING,
            )
        assert "A standard reason or custom gym reason must be provided" in str(exc.value)

    def test_create_lead_not_joining_with_standard_reason(self):
        ctx = setup_gym_and_lead_context()
        lead = create_lead(
            gym=ctx["gym"],
            first_name="Declined",
            phone="+12345",
            stage=LeadStageEnum.NOT_JOINING,
            not_joining_reason_standard=NotJoiningReasonStandard.PRICE,
        )
        assert lead.stage == LeadStageEnum.NOT_JOINING
        assert lead.not_joining_reason_standard == NotJoiningReasonStandard.PRICE

    def test_custom_reason_creation_and_duplicate_handling(self):
        ctx = setup_gym_and_lead_context()
        reason = create_custom_reason(gym=ctx["gym"], reason_name="Moved to Another City")
        assert reason.id is not None
        assert reason.reason_name == "Moved to Another City"

        with pytest.raises(ResourceConflictError) as exc:
            create_custom_reason(gym=ctx["gym"], reason_name="Moved to Another City")
        assert "already exists" in str(exc.value)

        # Same reason name in a different gym should succeed
        other_owner, _, _ = create_user_with_tokens("diff.owner@manygym.com")
        diff_gym = create_gym(owner_user=other_owner, name="Diff Gym")
        diff_reason = create_custom_reason(gym=diff_gym, reason_name="Moved to Another City")
        assert diff_reason.id is not None

    def test_update_lead_stage_transitions(self):
        ctx = setup_gym_and_lead_context()
        lead = create_lead(
            gym=ctx["gym"],
            first_name="Diana",
            email="diana@example.com",
            phone="+111222333",
        )
        assert lead.stage == LeadStageEnum.NEW

        # Transition to Contacted
        update_lead_stage(lead=lead, new_stage=LeadStageEnum.CONTACTED)
        assert lead.stage == LeadStageEnum.CONTACTED

        # Transition to Visit / Trial Booked
        booking_time = timezone.now() + timedelta(days=2)
        update_lead_stage(
            lead=lead,
            new_stage=LeadStageEnum.VISIT_TRIAL_BOOKED,
            trial_booked_at=booking_time,
        )
        assert lead.stage == LeadStageEnum.VISIT_TRIAL_BOOKED
        assert lead.trial_booked_at == booking_time

        # Transition to Not Joining with dynamic custom reason
        update_lead_stage(
            lead=lead,
            new_stage=LeadStageEnum.NOT_JOINING,
            custom_reason_name="Prefers home workouts",
        )
        assert lead.stage == LeadStageEnum.NOT_JOINING
        assert lead.not_joining_custom_reason.reason_name == "Prefers home workouts"

    def test_schedule_and_complete_next_move(self):
        ctx = setup_gym_and_lead_context()
        lead = create_lead(
            gym=ctx["gym"],
            first_name="Evan",
            phone="+999888777",
        )

        move = schedule_next_move(
            lead=lead,
            scheduled_date=date.today() + timedelta(days=1),
            short_description="Call back regarding class schedule",
        )
        assert move.id is not None
        assert move.is_completed is False

        complete_next_move(move)
        move.refresh_from_db()
        assert move.is_completed is True

    def test_convert_lead_to_member_atomic_success(self):
        ctx = setup_gym_and_lead_context()
        lead = create_lead(
            gym=ctx["gym"],
            first_name="Fiona",
            last_name="Gallagher",
            email="fiona.gallagher@example.com",
            phone="+4455667788",
            interested_plan_id=ctx["plan"].id,
            stage=LeadStageEnum.CONTACTED,
        )

        member = convert_lead_to_member(
            lead=lead,
            initial_payment_amount=Decimal("135.00"),
            initial_payment_method="credit_card",
        )

        assert member.id is not None
        assert member.gym == ctx["gym"]
        assert member.first_name == "Fiona"
        assert member.last_name == "Gallagher"
        assert member.email == "fiona.gallagher@example.com"
        assert member.subscriptions.count() == 1
        sub = member.subscriptions.first()
        assert sub.plan == ctx["plan"]

        lead.refresh_from_db()
        assert lead.stage == LeadStageEnum.JOINED
        assert lead.converted_member == member
        assert lead.notes.filter(note_text__icontains="converted successfully").exists()

        # Attempting second conversion must raise conflict
        with pytest.raises(ResourceConflictError) as exc:
            convert_lead_to_member(lead=lead)
        assert "already been converted" in str(exc.value)

    def test_convert_lead_missing_email_requires_override(self):
        ctx = setup_gym_and_lead_context()
        phone_only_lead = create_lead(
            gym=ctx["gym"],
            first_name="George",
            phone="+4477889900",
            interested_plan_id=ctx["plan"].id,
        )

        with pytest.raises(DomainValidationError) as exc:
            convert_lead_to_member(lead=phone_only_lead)
        assert "valid email address is required" in str(exc.value)

        # Providing email in conversion payload succeeds
        member = convert_lead_to_member(
            lead=phone_only_lead,
            member_email="george.provided@example.com",
        )
        assert member.email == "george.provided@example.com"

    def test_delete_lead_restrictions(self):
        ctx = setup_gym_and_lead_context()
        lead = create_lead(
            gym=ctx["gym"],
            first_name="Temporary",
            phone="+12345",
        )
        lead_id = lead.id
        delete_lead(lead)
        assert not Lead.objects.filter(id=lead_id).exists()

        # Joined lead cannot be deleted
        joined_lead = create_lead(
            gym=ctx["gym"],
            first_name="JoinedLead",
            email="joined@example.com",
            interested_plan_id=ctx["plan"].id,
        )
        convert_lead_to_member(lead=joined_lead)
        with pytest.raises(ResourceConflictError) as exc:
            delete_lead(joined_lead)
        assert "Cannot delete a lead that has already been converted" in str(exc.value)


# ==============================================================================
# 2. REST API & RBAC ENDPOINT TESTS
# ==============================================================================

@pytest.mark.django_db
class TestLeadAPIEndpoints:

    def test_list_leads_with_filters_and_pagination(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        # Create multiple leads
        create_lead(gym=ctx["gym"], first_name="User1", phone="+111", stage=LeadStageEnum.NEW)
        create_lead(gym=ctx["gym"], first_name="User2", email="u2@example.com", stage=LeadStageEnum.CONTACTED)
        create_lead(gym=ctx["gym"], first_name="SpecialSearch", phone="+222", stage=LeadStageEnum.NEW)

        # List all
        resp = client.get("/api/v1/leads/")
        assert resp.status_code == status.HTTP_200_OK
        results = resp.data.get("results", resp.data)
        assert len(results) >= 3

        # Filter by stage
        resp_stage = client.get("/api/v1/leads/?stage=contacted")
        assert resp_stage.status_code == status.HTTP_200_OK
        stage_results = resp_stage.data.get("results", resp_stage.data)
        assert len(stage_results) == 1
        assert stage_results[0]["first_name"] == "User2"

        # Search filter
        resp_search = client.get("/api/v1/leads/?search=SpecialSearch")
        assert resp_search.status_code == status.HTTP_200_OK
        search_results = resp_search.data.get("results", resp_search.data)
        assert len(search_results) == 1
        assert search_results[0]["first_name"] == "SpecialSearch"

    def test_create_lead_api_success_and_validation(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        payload = {
            "first_name": "APILead",
            "last_name": "Smith",
            "email": "apilead@example.com",
            "phone": "+1234567890",
            "source": "website",
            "stage": "new",
            "fitness_goals": ["general_fitness", "weight_loss"],
            "initial_note": "Interested in morning yoga sessions.",
        }

        resp = client.post("/api/v1/leads/", payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["full_name"] == "APILead Smith"
        assert resp.data["email"] == "apilead@example.com"
        assert len(resp.data["fitness_goals"]) == 2
        assert len(resp.data["notes"]) == 1

        # Error if missing contact method
        bad_payload = {
            "first_name": "NoContact",
        }
        resp_bad = client.post("/api/v1/leads/", bad_payload, format="json")
        assert resp_bad.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_lead_details_api(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        lead = create_lead(
            gym=ctx["gym"],
            first_name="DetailTester",
            email="detail@example.com",
        )
        schedule_next_move(lead=lead, scheduled_date=date.today(), short_description="Initial call")
        add_lead_note(lead=lead, note_text="Follow-up note")

        resp = client.get(f"/api/v1/leads/{lead.id}/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["id"] == str(lead.id)
        assert len(resp.data["next_moves"]) == 1
        assert len(resp.data["notes"]) == 1

    def test_patch_lead_api(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        lead = create_lead(
            gym=ctx["gym"],
            first_name="OriginalName",
            phone="+12345",
        )

        patch_payload = {
            "first_name": "UpdatedName",
            "email": "updated@example.com",
            "stage": "contacted",
        }
        resp = client.patch(f"/api/v1/leads/{lead.id}/", patch_payload, format="json")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["first_name"] == "UpdatedName"
        assert resp.data["email"] == "updated@example.com"
        assert resp.data["stage"] == "contacted"

    def test_lead_next_moves_crud_api(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        lead = create_lead(gym=ctx["gym"], first_name="MoveTester", phone="+555")

        # Create next move
        move_payload = {
            "scheduled_date": str(date.today() + timedelta(days=3)),
            "short_description": "Send workout plan preview",
        }
        resp = client.post(f"/api/v1/leads/{lead.id}/next-moves/", move_payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        move_id = resp.data["id"]
        assert resp.data["is_completed"] is False

        # Mark completed
        patch_payload = {"is_completed": True}
        resp_patch = client.patch(f"/api/v1/leads/{lead.id}/next-moves/{move_id}/", patch_payload, format="json")
        assert resp_patch.status_code == status.HTTP_200_OK
        assert resp_patch.data["is_completed"] is True

    def test_lead_add_note_api(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        lead = create_lead(gym=ctx["gym"], first_name="NoteTester", phone="+555")

        note_payload = {"note_text": "Spoke on phone, client interested in personal trainer."}
        resp = client.post(f"/api/v1/leads/{lead.id}/notes/", note_payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["note_text"] == note_payload["note_text"]

    def test_lead_convert_api(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        lead = create_lead(
            gym=ctx["gym"],
            first_name="ConvertAPI",
            last_name="User",
            email="convertapi@example.com",
            phone="+99887766",
            interested_plan_id=ctx["plan"].id,
        )

        convert_payload = {
            "initial_payment_amount": "135.00",
            "initial_payment_method": "cash",
            "initial_payment_notes": "Paid at front desk upon signing up.",
        }

        resp = client.post(f"/api/v1/leads/{lead.id}/convert/", convert_payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert "member_id" in resp.data

        # Verify member created
        member = Member.objects.get(id=resp.data["member_id"])
        assert member.email == "convertapi@example.com"
        assert member.first_name == "ConvertAPI"

    def test_lead_metrics_api(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        create_lead(gym=ctx["gym"], first_name="M1", phone="+1", stage=LeadStageEnum.NEW)
        create_lead(gym=ctx["gym"], first_name="M2", phone="+2", stage=LeadStageEnum.CONTACTED)
        joined_lead = create_lead(gym=ctx["gym"], first_name="M3", email="m3@example.com", interested_plan_id=ctx["plan"].id)
        convert_lead_to_member(lead=joined_lead)

        resp = client.get("/api/v1/leads/metrics/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["total_leads"] >= 3
        assert resp.data["new"] >= 1
        assert resp.data["contacted"] >= 1
        assert resp.data["joined"] >= 1
        assert resp.data["conversion_rate_percentage"] > 0

    def test_lead_reasons_api(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        # Create custom reason
        create_payload = {"reason_name": "Too far from work"}
        resp_post = client.post("/api/v1/leads/reasons/", create_payload, format="json")
        assert resp_post.status_code == status.HTTP_201_CREATED
        assert resp_post.data["reason_name"] == "Too far from work"

        # List reasons
        resp_get = client.get("/api/v1/leads/reasons/")
        assert resp_get.status_code == status.HTTP_200_OK
        assert len(resp_get.data["standard_reasons"]) > 0
        assert any(r["reason_name"] == "Too far from work" for r in resp_get.data["custom_reasons"])

    def test_delete_lead_api(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        lead = create_lead(gym=ctx["gym"], first_name="ToDelete", phone="+999")
        resp_del = client.delete(f"/api/v1/leads/{lead.id}/")
        assert resp_del.status_code == status.HTTP_200_OK
        assert not Lead.objects.filter(id=lead.id).exists()

    def test_rbac_security_unauthenticated_denied(self):
        anonymous_client = APIClient()
        resp = anonymous_client.get("/api/v1/leads/")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_rbac_security_cross_tenant_isolation(self):
        ctx1 = setup_gym_and_lead_context("owner1@manygym.com")
        lead1 = create_lead(gym=ctx1["gym"], first_name="Tenant1Lead", phone="+111")

        # Second gym owner
        ctx2 = setup_gym_and_lead_context("owner2@manygym.com")
        client2 = ctx2["client"]

        # Attempt to access lead of gym 1 with gym 2 credentials
        resp = client2.get(f"/api/v1/leads/{lead1.id}/")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

        # Attempt to update lead of gym 1 with gym 2 credentials
        resp_patch = client2.patch(f"/api/v1/leads/{lead1.id}/", {"first_name": "Hacked"}, format="json")
        assert resp_patch.status_code == status.HTTP_404_NOT_FOUND


def create_staff_with_scopes(gym, scopes: list[str], email_prefix="staff.custom"):
    user, _, _ = create_user_with_tokens(f"{email_prefix}.{uuid.uuid4().hex[:8]}@manygym.com")
    role = Role.objects.create(
        gym=gym,
        name=f"Role_{uuid.uuid4().hex[:6]}",
        slug=f"slug_{uuid.uuid4().hex[:8]}",
        is_custom=True,
    )
    perm_objs = [Permission.objects.get(scope_code=sc) for sc in scopes if Permission.objects.filter(scope_code=sc).exists()]
    role.permissions.set(perm_objs)
    assignment = GymStaffAssignment.objects.create(
        gym=gym,
        user=user,
        role=role,
        status=StaffStatus.ACTIVE,
    )
    tokens = issue_context_token(user, context_type=TokenContextType.GYM, gym=gym)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return user, client, assignment


# ==============================================================================
# 3. TYPE JUGGLING & DATA TYPE MISMATCH TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase5TypeJugglingAndMismatches:

    @pytest.mark.parametrize("bad_name", [
        12345,
        True,
        ["Invalid", "Array"],
        {"first_name": "nested_dict"},
    ])
    def test_lead_first_name_type_mismatch_rejected(self, bad_name):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        payload = {
            "first_name": bad_name,
            "phone": "+1234567890",
        }
        resp = client.post("/api/v1/leads/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_goals", [
        "weight_loss",  # string instead of list
        123,
        True,
        {"goal": "weight_loss"},
    ])
    def test_lead_fitness_goals_non_array_rejected(self, bad_goals):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        payload = {
            "first_name": "TypeTest",
            "phone": "+1234567890",
            "fitness_goals": bad_goals,
        }
        resp = client.post("/api/v1/leads/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_date", [
        1700000000,
        ["2026-10-15"],
        {"date": "2026-10-15"},
        True,
    ])
    def test_next_move_scheduled_date_type_mismatch_rejected(self, bad_date):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        lead = create_lead(gym=ctx["gym"], first_name="MoveType", phone="+111")

        payload = {
            "scheduled_date": bad_date,
            "short_description": "Follow-up call",
        }
        resp = client.post(f"/api/v1/leads/{lead.id}/next-moves/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_amount", [
        ["100.00"],
        {"amount": 100},
        True,
    ])
    def test_convert_initial_payment_amount_type_mismatch_rejected(self, bad_amount):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        lead = create_lead(gym=ctx["gym"], first_name="ConvertType", email="ct@test.com", interested_plan_id=ctx["plan"].id)

        payload = {
            "initial_payment_amount": bad_amount,
            "initial_payment_method": "cash",
        }
        resp = client.post(f"/api/v1/leads/{lead.id}/convert/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_note", [
        12345,
        ["nested", "note"],
        {"note": "text"},
        None,
    ])
    def test_note_text_type_mismatch_rejected(self, bad_note):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        lead = create_lead(gym=ctx["gym"], first_name="NoteType", phone="+111")

        payload = {"note_text": bad_note}
        resp = client.post(f"/api/v1/leads/{lead.id}/notes/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 4. BOUNDARY & EXTREME LENGTH VALUES TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase5BoundaryAndExtremeLengths:

    def test_first_name_extreme_length_rejected(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        # Exactly 100 chars (valid)
        valid_name = "A" * 100
        resp_valid = client.post("/api/v1/leads/", {"first_name": valid_name, "phone": "+12345"}, format="json")
        assert resp_valid.status_code == status.HTTP_201_CREATED

        # 101 chars (invalid)
        resp_over = client.post("/api/v1/leads/", {"first_name": "A" * 101, "phone": "+12345"}, format="json")
        assert resp_over.status_code == status.HTTP_400_BAD_REQUEST

        # 10,000 chars (extreme payload)
        resp_extreme = client.post("/api/v1/leads/", {"first_name": "A" * 10000, "phone": "+12345"}, format="json")
        assert resp_extreme.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("blank_name", ["", "   ", "\t\t\n"])
    def test_whitespace_and_blank_names_rejected(self, blank_name):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        resp = client.post("/api/v1/leads/", {"first_name": blank_name, "phone": "+12345"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_empty_contact_methods_rejected(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        # Neither phone nor email provided
        resp = client.post("/api/v1/leads/", {"first_name": "NoContact"}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

        # Whitespace-only phone and email
        resp_ws = client.post("/api/v1/leads/", {"first_name": "NoContact", "phone": "   ", "email": "   "}, format="json")
        assert resp_ws.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_decimal", [
        "-0.01",
        "-100.00",
        "0.00",  # min_value=0.01
        "99999999999999999.99",  # exceeds max_digits
    ])
    def test_payment_amount_boundary_decimals_rejected(self, bad_decimal):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        lead = create_lead(gym=ctx["gym"], first_name="DecTest", email="dec@test.com", interested_plan_id=ctx["plan"].id)

        resp = client.post(
            f"/api/v1/leads/{lead.id}/convert/",
            {"initial_payment_amount": bad_decimal, "initial_payment_method": "cash"},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_valid_boundary_payment_amount_accepted(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        lead = create_lead(gym=ctx["gym"], first_name="DecValid", email="decvalid@test.com", interested_plan_id=ctx["plan"].id)

        resp = client.post(
            f"/api/v1/leads/{lead.id}/convert/",
            {"initial_payment_amount": "99999999.99", "initial_payment_method": "cash"},
            format="json",
        )
        assert resp.status_code == status.HTTP_201_CREATED


# ==============================================================================
# 5. MISSING, EXTRA & GARBAGE FIELDS TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase5MissingAndGarbageFields:

    @pytest.mark.parametrize("endpoint,method", [
        ("/api/v1/leads/", "post"),
        ("/api/v1/leads/reasons/", "post"),
    ])
    def test_empty_json_payload_rejected(self, endpoint, method):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        resp = getattr(client, method)(endpoint, {}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_extra_garbage_fields_handled_gracefully(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        garbage_payload = {
            "first_name": "GarbageTester",
            "phone": "+1234567890",
        }
        for i in range(100):
            garbage_payload[f"unknown_field_{i}"] = f"garbage_val_{i}"

        resp = client.post("/api/v1/leads/", garbage_payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["first_name"] == "GarbageTester"

    def test_mass_assignment_protection_on_system_fields(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        lead = create_lead(gym=ctx["gym"], first_name="MassAssign", phone="+123")

        fake_id = str(uuid.uuid4())
        fake_gym_id = str(uuid.uuid4())
        malicious_payload = {
            "id": fake_id,
            "gym_id": fake_gym_id,
            "created_at": "2020-01-01T00:00:00Z",
            "converted_member_id": str(uuid.uuid4()),
            "first_name": "TamperedName",
        }

        resp = client.patch(f"/api/v1/leads/{lead.id}/", malicious_payload, format="json")
        assert resp.status_code == status.HTTP_200_OK

        lead.refresh_from_db()
        assert str(lead.id) != fake_id
        assert str(lead.gym_id) != fake_gym_id
        assert lead.converted_member_id is None
        assert lead.first_name == "TamperedName"


# ==============================================================================
# 6. FORMAT-SPECIFIC & SEMANTIC INVALID INPUTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase5FormatAndSemanticValidation:

    @pytest.mark.parametrize("bad_date", [
        "2026-13-45",
        "32-01-2026",
        "tomorrow",
        "2026/05/10",
        "invalid-date",
    ])
    def test_invalid_date_formats_rejected(self, bad_date):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        resp = client.post("/api/v1/leads/", {
            "first_name": "BadDateLead",
            "phone": "+12345",
            "expected_start_date": bad_date,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_email", [
        "plainaddress",
        "@missingusername.com",
        "username@.com",
        "username@name@name.com",
        "user name@domain.com",
    ])
    def test_invalid_email_formats_rejected(self, bad_email):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        resp = client.post("/api/v1/leads/", {
            "first_name": "BadEmailLead",
            "email": bad_email,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_choice_field,bad_value", [
        ("stage", "SUPER_HOT_PROSPECT"),
        ("source", "FLYING_SAUCER"),
        ("not_joining_reason_standard", "TOO_TIRED_FOREVER"),
    ])
    def test_invalid_enum_choices_rejected(self, bad_choice_field, bad_value):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        payload = {
            "first_name": "ChoiceLead",
            "phone": "+12345",
            bad_choice_field: bad_value,
        }
        resp = client.post("/api/v1/leads/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_non_existent_uuid_foreign_keys_rejected(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        non_existent_uuid = str(uuid.uuid4())
        resp = client.post("/api/v1/leads/", {
            "first_name": "FakeFKLead",
            "phone": "+12345",
            "interested_plan_id": non_existent_uuid,
        }, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 7. QUERY PARAMS, FILTERS & PAGINATION EDGE CASES
# ==============================================================================

@pytest.mark.django_db
class TestPhase5QueryParamsAndPaginationEdgeCases:

    @pytest.mark.parametrize("sqli_param", [
        "' OR '1'='1",
        "'; DROP TABLE apps_leads_lead; --",
        "admin'--",
        "\" OR \"\"=\"",
        "%' OR 1=1 --",
        "_",
        "%%%",
    ])
    def test_search_parameter_sqli_resilience(self, sqli_param):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        create_lead(gym=ctx["gym"], first_name="SearchTarget", phone="+12345")

        resp = client.get(f"/api/v1/leads/?search={sqli_param}")
        assert resp.status_code == status.HTTP_200_OK
        # Zero crash, safe parameterized SQL executed

    @pytest.mark.parametrize("xss_search", [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "<svg/onload=alert('xss')>",
    ])
    def test_search_parameter_xss_resilience(self, xss_search):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        resp = client.get(f"/api/v1/leads/?search={xss_search}")
        assert resp.status_code == status.HTTP_200_OK

    @pytest.mark.parametrize("bad_page", [
        0,
        -1,
        -99,
        "abc",
        "null",
    ])
    def test_pagination_invalid_page_handles_gracefully(self, bad_page):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        resp = client.get(f"/api/v1/leads/?page={bad_page}")
        assert resp.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]

    def test_pagination_out_of_bounds_page_returns_404(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        create_lead(gym=ctx["gym"], first_name="P1", phone="+1")

        resp = client.get("/api/v1/leads/?page=999999")
        assert resp.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize("bad_page_size", [
        0,
        -10,
        999999,
    ])
    def test_pagination_boundary_page_size(self, bad_page_size):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        create_lead(gym=ctx["gym"], first_name="SizeTester", phone="+1")

        resp = client.get(f"/api/v1/leads/?page_size={bad_page_size}")
        assert resp.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]

    def test_invalid_assigned_staff_uuid_query_param_fails(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        resp = client.get("/api/v1/leads/?assigned_staff_id=not-a-uuid")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 8. SECURITY & ADVERSARIAL INJECTIONS
# ==============================================================================

@pytest.mark.django_db
class TestPhase5SecurityAndAdversarialInjections:

    @pytest.mark.parametrize("injection_string", [
        "'; DROP TABLE apps_leads_lead; --",
        "' OR 1=1 --",
        "UNION SELECT NULL, NULL, NULL --",
        "\" OR \"a\"=\"a",
    ])
    def test_sql_injection_stored_literally_without_execution(self, injection_string):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        # In lead first name
        resp = client.post("/api/v1/leads/", {
            "first_name": injection_string,
            "phone": "+12345",
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        lead_id = resp.data["id"]

        # In lead note
        resp_note = client.post(f"/api/v1/leads/{lead_id}/notes/", {
            "note_text": injection_string,
        }, format="json")
        assert resp_note.status_code == status.HTTP_201_CREATED

        # In next move description
        resp_move = client.post(f"/api/v1/leads/{lead_id}/next-moves/", {
            "scheduled_date": str(date.today()),
            "short_description": injection_string,
        }, format="json")
        assert resp_move.status_code == status.HTTP_201_CREATED

        # Database tables must remain completely intact
        assert Lead.objects.filter(id=lead_id).exists()
        lead = Lead.objects.get(id=lead_id)
        assert lead.first_name == injection_string

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(document.cookie)>",
        "<iframe src=\"javascript:alert('pwned')\"></iframe>",
    ])
    def test_stored_xss_payloads_persisted_safely_as_strings(self, xss_payload):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        resp = client.post("/api/v1/leads/", {
            "first_name": xss_payload,
            "phone": "+12345",
            "initial_note": xss_payload,
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["first_name"] == xss_payload

    @pytest.mark.parametrize("traversal_string", [
        "../../../../../../etc/passwd",
        "..\\..\\..\\windows\\system32\\cmd.exe",
        "/var/log/syslog",
    ])
    def test_path_traversal_payloads_handled_as_plain_strings(self, traversal_string):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        resp = client.post("/api/v1/leads/", {
            "first_name": "PathTest",
            "phone": "+12345",
            "initial_note": traversal_string,
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED

    @pytest.mark.parametrize("unicode_string", [
        "مرحبا بك في صالة الألعاب الرياضية",  # Arabic
        "ברוכים הבאים לחדר כושר",             # Hebrew
        "健身房潜在客户测试",                  # Chinese
        "🏋️‍♂️ Muscle Building & Fat Loss 💪🔥💯",  # Emojis
    ])
    def test_unicode_and_multilingual_data_integrity(self, unicode_string):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        resp = client.post("/api/v1/leads/", {
            "first_name": unicode_string,
            "phone": "+12345",
            "initial_note": unicode_string,
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["first_name"] == unicode_string


# ==============================================================================
# 9. AUTHENTICATION & RBAC PERMISSIONS TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase5RBACAndAuthentication:

    def test_anonymous_requests_blocked_with_401(self):
        anon_client = APIClient()
        fake_uuid = uuid.uuid4()

        endpoints = [
            ("get", "/api/v1/leads/"),
            ("post", "/api/v1/leads/"),
            ("get", "/api/v1/leads/metrics/"),
            ("get", "/api/v1/leads/reasons/"),
            ("post", "/api/v1/leads/reasons/"),
            ("get", f"/api/v1/leads/{fake_uuid}/"),
            ("patch", f"/api/v1/leads/{fake_uuid}/"),
            ("delete", f"/api/v1/leads/{fake_uuid}/"),
            ("post", f"/api/v1/leads/{fake_uuid}/next-moves/"),
            ("post", f"/api/v1/leads/{fake_uuid}/notes/"),
            ("post", f"/api/v1/leads/{fake_uuid}/convert/"),
        ]

        for method, url in endpoints:
            resp = getattr(anon_client, method)(url, {}, format="json")
            assert resp.status_code == status.HTTP_401_UNAUTHORIZED, f"Failed for {method.upper()} {url}"

    def test_invalid_bearer_token_rejected_with_401(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer invalid.token.payload")

        resp = client.get("/api/v1/leads/")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_personal_token_without_gym_context_fails(self):
        user, client, _ = create_user_with_tokens("personal.only@manygym.com")
        resp = client.get("/api/v1/leads/")
        assert resp.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN]

    def test_read_only_staff_blocked_from_all_mutations(self):
        ctx = setup_gym_and_lead_context()
        lead = create_lead(gym=ctx["gym"], first_name="StaffTestLead", phone="+12345")

        # Staff with ONLY 'leads:read'
        _, read_client, _ = create_staff_with_scopes(ctx["gym"], scopes=["leads:read"])

        # Reads succeed
        resp_list = read_client.get("/api/v1/leads/")
        assert resp_list.status_code == status.HTTP_200_OK

        resp_detail = read_client.get(f"/api/v1/leads/{lead.id}/")
        assert resp_detail.status_code == status.HTTP_200_OK

        resp_metrics = read_client.get("/api/v1/leads/metrics/")
        assert resp_metrics.status_code == status.HTTP_200_OK

        resp_reasons = read_client.get("/api/v1/leads/reasons/")
        assert resp_reasons.status_code == status.HTTP_200_OK

        # Mutations MUST fail with 403 Forbidden
        resp_post = read_client.post("/api/v1/leads/", {"first_name": "NewLead", "phone": "+999"}, format="json")
        assert resp_post.status_code == status.HTTP_403_FORBIDDEN

        resp_patch = read_client.patch(f"/api/v1/leads/{lead.id}/", {"first_name": "Changed"}, format="json")
        assert resp_patch.status_code == status.HTTP_403_FORBIDDEN

        resp_del = read_client.delete(f"/api/v1/leads/{lead.id}/")
        assert resp_del.status_code == status.HTTP_403_FORBIDDEN

        resp_move = read_client.post(
            f"/api/v1/leads/{lead.id}/next-moves/",
            {"scheduled_date": str(date.today()), "short_description": "Call"},
            format="json",
        )
        assert resp_move.status_code == status.HTTP_403_FORBIDDEN

        resp_note = read_client.post(f"/api/v1/leads/{lead.id}/notes/", {"note_text": "Note"}, format="json")
        assert resp_note.status_code == status.HTTP_403_FORBIDDEN

        resp_conv = read_client.post(f"/api/v1/leads/{lead.id}/convert/", {}, format="json")
        assert resp_conv.status_code == status.HTTP_403_FORBIDDEN

        resp_reas = read_client.post("/api/v1/leads/reasons/", {"reason_name": "Too far"}, format="json")
        assert resp_reas.status_code == status.HTTP_403_FORBIDDEN


# ==============================================================================
# 10. IDOR & MULTI-TENANT ISOLATION TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase5CrossTenantIDORIsolation:

    def test_complete_cross_tenant_dossier_isolation(self):
        ctx1 = setup_gym_and_lead_context("gym1.owner@manygym.com")
        lead1 = create_lead(gym=ctx1["gym"], first_name="Gym1Lead", phone="+111")
        move1 = schedule_next_move(lead=lead1, scheduled_date=date.today(), short_description="Initial Task")

        ctx2 = setup_gym_and_lead_context("gym2.owner@manygym.com")
        client2 = ctx2["client"]

        # Gym 2 attempts all actions against Gym 1's lead
        assert client2.get(f"/api/v1/leads/{lead1.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert client2.patch(f"/api/v1/leads/{lead1.id}/", {"first_name": "Tamper"}, format="json").status_code == status.HTTP_404_NOT_FOUND
        assert client2.delete(f"/api/v1/leads/{lead1.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert client2.post(f"/api/v1/leads/{lead1.id}/notes/", {"note_text": "Spy Note"}, format="json").status_code == status.HTTP_404_NOT_FOUND
        assert client2.post(f"/api/v1/leads/{lead1.id}/next-moves/", {"scheduled_date": str(date.today()), "short_description": "Spy Move"}, format="json").status_code == status.HTTP_404_NOT_FOUND
        assert client2.patch(f"/api/v1/leads/{lead1.id}/next-moves/{move1.id}/", {"is_completed": True}, format="json").status_code == status.HTTP_404_NOT_FOUND
        assert client2.post(f"/api/v1/leads/{lead1.id}/convert/", {}, format="json").status_code == status.HTTP_404_NOT_FOUND

    def test_foreign_key_cross_tenant_tampering_blocked(self):
        ctx1 = setup_gym_and_lead_context("gym1.fk@manygym.com")
        ctx2 = setup_gym_and_lead_context("gym2.fk@manygym.com")

        # Gym 1 tries to use Gym 2's plan
        resp_plan = ctx1["client"].post("/api/v1/leads/", {
            "first_name": "CrossPlanLead",
            "phone": "+123",
            "interested_plan_id": str(ctx2["plan"].id),
        }, format="json")
        assert resp_plan.status_code == status.HTTP_400_BAD_REQUEST

        # Gym 1 tries to assign Gym 2's staff member
        resp_staff = ctx1["client"].post("/api/v1/leads/", {
            "first_name": "CrossStaffLead",
            "phone": "+123",
            "assigned_staff_id": str(ctx2["staff_assignment"].id),
        }, format="json")
        assert resp_staff.status_code == status.HTTP_400_BAD_REQUEST

        # Gym 1 creates a valid lead, then tries to convert using Gym 2's plan
        lead1 = create_lead(gym=ctx1["gym"], first_name="ConvertFK", email="fk@test.com")
        resp_conv = ctx1["client"].post(f"/api/v1/leads/{lead1.id}/convert/", {
            "plan_id": str(ctx2["plan"].id),
        }, format="json")
        assert resp_conv.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 11. BUSINESS INVARIANTS & STATE RULES
# ==============================================================================

@pytest.mark.django_db
class TestPhase5BusinessInvariantsAndStateRules:

    def test_not_joining_without_reason_rejected_on_create_and_patch(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        # Create with stage=not_joining but no reason -> 400
        resp_create = client.post("/api/v1/leads/", {
            "first_name": "LostLead",
            "phone": "+123",
            "stage": "not_joining",
        }, format="json")
        assert resp_create.status_code == status.HTTP_400_BAD_REQUEST

        # Valid lead, then patch to not_joining without reason -> 400
        lead = create_lead(gym=ctx["gym"], first_name="ValidLead", phone="+123")
        resp_patch = client.patch(f"/api/v1/leads/{lead.id}/", {
            "stage": "not_joining",
        }, format="json")
        assert resp_patch.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_revert_joined_lead(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        lead = create_lead(gym=ctx["gym"], first_name="JoinedRevert", email="jr@test.com", interested_plan_id=ctx["plan"].id)
        convert_lead_to_member(lead=lead)

        # Attempt to patch stage back to new or contacted -> 409 Conflict
        for target_stage in ["new", "contacted", "visit_trial_booked", "not_joining"]:
            resp = client.patch(f"/api/v1/leads/{lead.id}/", {"stage": target_stage}, format="json")
            assert resp.status_code == status.HTTP_409_CONFLICT

    def test_cannot_reconvert_already_joined_lead(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        lead = create_lead(gym=ctx["gym"], first_name="DoubleConvert", email="dc@test.com", interested_plan_id=ctx["plan"].id)
        convert_lead_to_member(lead=lead)

        resp = client.post(f"/api/v1/leads/{lead.id}/convert/", {}, format="json")
        assert resp.status_code == status.HTTP_409_CONFLICT

    def test_cannot_delete_joined_lead(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        lead = create_lead(gym=ctx["gym"], first_name="DeleteJoined", email="dj@test.com", interested_plan_id=ctx["plan"].id)
        convert_lead_to_member(lead=lead)

        resp = client.delete(f"/api/v1/leads/{lead.id}/")
        assert resp.status_code == status.HTTP_409_CONFLICT


# ==============================================================================
# 12. HTTP METHOD NOT ALLOWED (405) TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase5HTTPMethodNotAllowed:

    def test_disallowed_http_methods(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]
        lead = create_lead(gym=ctx["gym"], first_name="MethodLead", phone="+123")

        disallowed_routes = [
            ("put", "/api/v1/leads/"),
            ("delete", "/api/v1/leads/"),
            ("post", "/api/v1/leads/metrics/"),
            ("put", "/api/v1/leads/metrics/"),
            ("delete", "/api/v1/leads/metrics/"),
            ("put", "/api/v1/leads/reasons/"),
            ("delete", "/api/v1/leads/reasons/"),
            ("post", f"/api/v1/leads/{lead.id}/"),
            ("get", f"/api/v1/leads/{lead.id}/convert/"),
            ("put", f"/api/v1/leads/{lead.id}/convert/"),
            ("delete", f"/api/v1/leads/{lead.id}/convert/"),
            ("put", f"/api/v1/leads/{lead.id}/notes/"),
            ("delete", f"/api/v1/leads/{lead.id}/notes/"),
        ]

        for method, url in disallowed_routes:
            resp = getattr(client, method)(url, {}, format="json")
            assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, f"Expected 405 for {method.upper()} {url}, got {resp.status_code}"


# ==============================================================================
# 13. ERROR ENVELOPE CONSISTENCY TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase5ErrorEnvelopeConsistency:

    def test_error_envelope_structure(self):
        ctx = setup_gym_and_lead_context()
        client = ctx["client"]

        # 400 Bad Request
        resp_400 = client.post("/api/v1/leads/", {"first_name": "NoContact"}, format="json")
        assert resp_400.status_code == status.HTTP_400_BAD_REQUEST
        assert "code" in resp_400.data or "message" in resp_400.data or "detail" in resp_400.data

        # 404 Not Found
        non_existent_uuid = uuid.uuid4()
        resp_404 = client.get(f"/api/v1/leads/{non_existent_uuid}/")
        assert resp_404.status_code == status.HTTP_404_NOT_FOUND
        assert "code" in resp_404.data or "message" in resp_404.data or "detail" in resp_404.data

        # Malformed non-UUID in path returns 404 (URL pattern does not match)
        resp_bad_path = client.get("/api/v1/leads/not-a-valid-uuid/")
        assert resp_bad_path.status_code == status.HTTP_404_NOT_FOUND

