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
