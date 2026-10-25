import uuid
from datetime import date, timedelta
from decimal import Decimal
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
from apps.members.models import Member, MemberSubscription, MemberPayment
from apps.members.services import create_member, create_member_subscription, record_member_payment
from apps.leads.models import Lead, LeadNextMove, LeadCustomReasons
from apps.leads.services import create_lead, schedule_next_move
from apps.routines.models import RoutineTemplate, MemberRoutine
from apps.routines.services import create_routine_template, assign_routine_to_member
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    UserStatus,
    StaffStatus,
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    MembershipStatusEnum,
    PaymentMethodEnum,
    PaymentStatusEnum,
    LeadStageEnum,
    NotJoiningReasonStandard,
    LeadSourceEnum,
    RoutineFormatEnum,
    RoutineLevelEnum,
)
from common.exceptions import DomainValidationError, ResourceNotFoundError, PermissionDeniedError


@pytest.fixture(autouse=True)
def setup_seeds(db):
    seed_amenity_catalog()
    seed_default_permissions_and_roles()


def create_user_with_tokens(email="test.phase8@manygym.com", is_verified=True, user_status=UserStatus.ACTIVE):
    user = User.objects.create_user(
        email=email,
        password="SecurePassword123!",
        first_name="Phase8",
        last_name="Tester",
        is_verified=is_verified,
        status=user_status,
    )
    UserProfile.objects.create(user=user)
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return user, client, tokens


@pytest.fixture
def report_gym_setup(db):
    # 1. Gym Owner
    owner, owner_client, _ = create_user_with_tokens(email="report.owner@manygym.com")
    gym = create_gym(
        owner_user=owner,
        name="Phase 8 Analytics Gym",
        timezone="UTC",
    )

    # 2. Staff with reports:read
    staff_user, staff_client, _ = create_user_with_tokens(email="report.staff@manygym.com")
    staff_role = Role.objects.get(slug="staff")
    staff_assignment = GymStaffAssignment.objects.create(
        gym=gym,
        user=staff_user,
        role=staff_role,
        status=StaffStatus.ACTIVE,
    )

    # 3. Trainer staff (also active)
    trainer_user, trainer_client, _ = create_user_with_tokens(email="report.trainer@manygym.com")
    trainer_assignment = GymStaffAssignment.objects.create(
        gym=gym,
        user=trainer_user,
        role=staff_role,
        status=StaffStatus.ACTIVE,
    )

    # 4. Staff without reports:read (limited custom role)
    limited_user, limited_client, _ = create_user_with_tokens(email="report.limited@manygym.com")
    custom_role = Role.objects.create(
        gym=gym,
        slug="limited_scope_role",
        name="Limited Scope Staff",
        is_custom=True,
    )
    GymStaffAssignment.objects.create(
        gym=gym,
        user=limited_user,
        role=custom_role,
        status=StaffStatus.ACTIVE,
    )

    # 5. Inactive Staff
    inactive_user, inactive_client, _ = create_user_with_tokens(email="report.inactive@manygym.com")
    GymStaffAssignment.objects.create(
        gym=gym,
        user=inactive_user,
        role=staff_role,
        status=StaffStatus.INACTIVE,
    )

    # 6. Regular Member User (Non-staff)
    member_user, member_client, _ = create_user_with_tokens(email="report.member@manygym.com")
    member = create_member(
        gym=gym,
        first_name="Alice",
        last_name="Member",
        email=member_user.email,
        phone="+12025550199",
        assigned_trainer_id=trainer_assignment.id,
    )

    # 7. Unauthenticated client
    anon_client = APIClient()

    # 8. Another gym for cross-tenant IDOR checks
    other_owner, other_client, _ = create_user_with_tokens(email="report.otherowner@manygym.com")
    gym_b = create_gym(
        owner_user=other_owner,
        name="Gym B Cross Tenant",
        timezone="UTC",
    )

    return {
        "gym": gym,
        "gym_b": gym_b,
        "owner": owner,
        "owner_client": owner_client,
        "staff_user": staff_user,
        "staff_client": staff_client,
        "staff_assignment": staff_assignment,
        "trainer_user": trainer_user,
        "trainer_client": trainer_client,
        "trainer_assignment": trainer_assignment,
        "limited_client": limited_client,
        "inactive_client": inactive_client,
        "member_user": member_user,
        "member": member,
        "member_client": member_client,
        "anon_client": anon_client,
        "other_client": other_client,
    }


# ==============================================================================
# 1. AUTHENTICATION & RBAC PERMISSION ENFORCEMENT
# ==============================================================================

@pytest.mark.django_db
class TestReportsAuthenticationAndRBAC:
    ENDPOINTS = [
        "/api/v1/dashboard/summary/",
        "/api/v1/reports/revenue/",
        "/api/v1/reports/membership-growth/",
        "/api/v1/reports/leads-funnel/",
        "/api/v1/reports/trainer-workload/",
    ]

    def test_anonymous_requests_rejected_with_401(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        anon_client = report_gym_setup["anon_client"]

        for ep in self.ENDPOINTS:
            res = anon_client.get(f"{ep}?gym_id={gym.id}")
            assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Expected 401 for {ep}"

    def test_regular_member_rejected_with_403(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        member_client = report_gym_setup["member_client"]

        for ep in self.ENDPOINTS:
            res = member_client.get(f"{ep}?gym_id={gym.id}")
            assert res.status_code == status.HTTP_403_FORBIDDEN, f"Expected 403 for {ep}"

    def test_inactive_staff_rejected_with_403(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        inactive_client = report_gym_setup["inactive_client"]

        for ep in self.ENDPOINTS:
            res = inactive_client.get(f"{ep}?gym_id={gym.id}")
            assert res.status_code == status.HTTP_403_FORBIDDEN, f"Expected 403 for {ep}"

    def test_staff_lacking_reports_read_rejected_with_403(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        limited_client = report_gym_setup["limited_client"]

        for ep in self.ENDPOINTS:
            res = limited_client.get(f"{ep}?gym_id={gym.id}")
            assert res.status_code == status.HTTP_403_FORBIDDEN, f"Expected 403 for {ep}"

    def test_authorized_staff_and_owner_succeed_with_200(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        staff_client = report_gym_setup["staff_client"]
        owner_client = report_gym_setup["owner_client"]

        for ep in self.ENDPOINTS:
            # Staff with reports:read
            res_staff = staff_client.get(f"{ep}?gym_id={gym.id}")
            assert res_staff.status_code == status.HTTP_200_OK, f"Staff failed for {ep}: {res_staff.data}"

            # Gym Owner
            res_owner = owner_client.get(f"{ep}?gym_id={gym.id}")
            assert res_owner.status_code == status.HTTP_200_OK, f"Owner failed for {ep}: {res_owner.data}"


# ==============================================================================
# 2. MULTI-TENANT ISOLATION & IDOR ATTACK PREVENTION
# ==============================================================================

@pytest.mark.django_db
class TestReportsMultiTenantIsolation:
    def test_cross_tenant_isolation(self, report_gym_setup):
        gym_a = report_gym_setup["gym"]
        gym_b = report_gym_setup["gym_b"]
        staff_client = report_gym_setup["staff_client"]
        other_client = report_gym_setup["other_client"]

        # 1. Staff of Gym A cannot query Gym B's reports
        for ep in [
            "/api/v1/dashboard/summary/",
            "/api/v1/reports/revenue/",
            "/api/v1/reports/membership-growth/",
            "/api/v1/reports/leads-funnel/",
            "/api/v1/reports/trainer-workload/",
        ]:
            res = staff_client.get(f"{ep}?gym_id={gym_b.id}")
            assert res.status_code == status.HTTP_403_FORBIDDEN

        # 2. Owner of Gym B gets their own zeroed reports, not Gym A's data
        res_b = other_client.get(f"/api/v1/dashboard/summary/?gym_id={gym_b.id}")
        assert res_b.status_code == status.HTTP_200_OK
        assert res_b.data["gym_id"] == str(gym_b.id)
        assert res_b.data["headline_metrics"]["total_members"] == 0


# ==============================================================================
# 3. DATE RANGE VALIDATION & ERROR HANDLING
# ==============================================================================

@pytest.mark.django_db
class TestReportsDateValidation:
    def test_invalid_start_date_format_returns_400(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res = owner_client.get(f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date=invalid-date")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid date format for 'start_date'" in str(res.data)

        res2 = owner_client.get(f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date=2026-02-31")
        assert res2.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_end_date_format_returns_400(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res = owner_client.get(f"/api/v1/reports/revenue/?gym_id={gym.id}&end_date=9999-99-99")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid date format for 'end_date'" in str(res.data)

    def test_inverted_date_range_returns_400(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res = owner_client.get(
            f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date=2026-06-15&end_date=2026-06-01"
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "'start_date' cannot be after 'end_date'" in str(res.data)

    def test_valid_custom_date_range(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res = owner_client.get(
            f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date=2026-01-01&end_date=2026-01-31"
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["start_date"] == "2026-01-01"
        assert res.data["end_date"] == "2026-01-31"


# ==============================================================================
# 4. DATA ACCURACY & AGGREGATIONS
# ==============================================================================

@pytest.mark.django_db
class TestReportsDataAccuracyAndAggregations:
    def test_dashboard_summary_metrics(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]
        today = timezone.localdate()

        # 1. Create plan
        plan = create_membership_plan(
            gym=gym,
            name="Gold Standard",
            plan_type=PlanTypeEnum.TIME_BASED,
            price=Decimal("150.00"),
            duration_value=1,
            duration_unit=DurationUnitEnum.MONTH,
        )

        # 2. Create members and subscriptions
        m1 = create_member(gym=gym, first_name="Bob", last_name="Active", email="bob@test.com")
        sub1 = create_member_subscription(
            member=m1,
            plan=plan,
            start_date=today,
        )
        sub1.end_date = today + timedelta(days=5)  # Expiring in 5 days (<= 7 days)
        sub1.membership_status = MembershipStatusEnum.ACTIVE
        sub1.save()

        m2 = create_member(gym=gym, first_name="Charlie", last_name="ExpiringSoon", email="charlie@test.com")
        sub2 = create_member_subscription(
            member=m2,
            plan=plan,
            start_date=today - timedelta(days=20),
        )
        sub2.end_date = today + timedelta(days=25)  # Expiring in 25 days (<= 30 days)
        sub2.membership_status = MembershipStatusEnum.ACTIVE
        sub2.save()

        # 3. Create payments (today & current month)
        record_member_payment(
            subscription=sub1,
            amount=Decimal("150.00"),
            payment_method=PaymentMethodEnum.CREDIT_CARD,
            payment_date=today,
        )
        record_member_payment(
            subscription=sub2,
            amount=Decimal("150.00"),
            payment_method=PaymentMethodEnum.CASH,
            payment_date=today,
        )

        # 4. Create leads and next moves
        lead1 = create_lead(
            gym=gym,
            first_name="Prospect",
            last_name="One",
            phone="+12025550101",
            source=LeadSourceEnum.WALK_IN,
        )
        lead1.trial_booked_at = timezone.now()
        lead1.stage = LeadStageEnum.VISIT_TRIAL_BOOKED
        lead1.save()

        schedule_next_move(
            lead=lead1,
            scheduled_date=today,
            short_description="Call lead about trial confirmation",
        )
        schedule_next_move(
            lead=lead1,
            scheduled_date=today - timedelta(days=2),
            short_description="Overdue follow up",
        )

        # Execute GET /api/v1/dashboard/summary/
        res = owner_client.get(f"/api/v1/dashboard/summary/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_200_OK
        metrics = res.data["headline_metrics"]

        assert metrics["total_members"] >= 2
        assert metrics["total_active_members"] >= 2
        assert metrics["expiring_memberships_next_7_days"] >= 1
        assert metrics["expiring_memberships_next_30_days"] >= 2
        assert metrics["new_leads_this_week"] >= 1
        assert metrics["pending_next_moves_today"] >= 1
        assert metrics["overdue_next_moves"] >= 1
        assert metrics["todays_scheduled_trials"] >= 1
        assert metrics["todays_revenue"] >= 300.0
        assert metrics["current_month_revenue"] >= 300.0

    def test_revenue_report_breakdowns(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]
        today = timezone.localdate()

        plan_a = create_membership_plan(
            gym=gym,
            name="VIP Elite",
            plan_type=PlanTypeEnum.TIME_BASED,
            price=Decimal("200.00"),
            duration_value=1,
            duration_unit=DurationUnitEnum.MONTH,
        )
        plan_b = create_membership_plan(
            gym=gym,
            name="Basic Fitness",
            plan_type=PlanTypeEnum.TIME_BASED,
            price=Decimal("100.00"),
            duration_value=1,
            duration_unit=DurationUnitEnum.MONTH,
        )

        m = create_member(gym=gym, first_name="John", last_name="Payer", email="john.payer@test.com")
        sub_a = create_member_subscription(member=m, plan=plan_a, start_date=today)
        sub_b = create_member_subscription(member=m, plan=plan_b, start_date=today)

        record_member_payment(
            subscription=sub_a,
            amount=Decimal("200.00"),
            payment_method=PaymentMethodEnum.CREDIT_CARD,
            payment_date=today,
        )
        record_member_payment(
            subscription=sub_b,
            amount=Decimal("100.00"),
            payment_method=PaymentMethodEnum.CASH,
            payment_date=today,
        )

        res = owner_client.get(
            f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date={today}&end_date={today}"
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.data

        assert data["total_revenue"] == 300.0
        assert data["total_transactions"] == 2
        assert data["average_transaction_value"] == 150.0

        # Check payment method breakdown
        methods = {item["payment_method"]: item["total_amount"] for item in data["payment_method_breakdown"]}
        assert methods[PaymentMethodEnum.CREDIT_CARD] == 200.0
        assert methods[PaymentMethodEnum.CASH] == 100.0

        # Check plan distribution
        plans = {item["plan_name"]: item["total_amount"] for item in data["plan_distribution"]}
        assert plans["VIP Elite"] == 200.0
        assert plans["Basic Fitness"] == 100.0

        # Check daily breakdown
        assert len(data["daily_breakdown"]) == 1
        assert data["daily_breakdown"][0]["date"] == str(today)
        assert data["daily_breakdown"][0]["amount"] == 300.0

    def test_lead_funnel_conversion_rates(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]
        today = timezone.localdate()

        # Create custom lost reason
        custom_reason = LeadCustomReasons.objects.create(gym=gym, reason_name="Moved to another city")

        # Lead 1: New
        create_lead(gym=gym, first_name="L1", phone="+1001", stage=LeadStageEnum.NEW)

        # Lead 2: Contacted
        create_lead(gym=gym, first_name="L2", phone="+1002", stage=LeadStageEnum.CONTACTED)

        # Lead 3: Trial Booked
        create_lead(gym=gym, first_name="L3", phone="+1003", stage=LeadStageEnum.VISIT_TRIAL_BOOKED)

        # Lead 4: Joined
        create_lead(gym=gym, first_name="L4", phone="+1004", stage=LeadStageEnum.JOINED)

        # Lead 5: Lost with standard reason
        create_lead(
            gym=gym,
            first_name="L5",
            phone="+1005",
            stage=LeadStageEnum.NOT_JOINING,
            not_joining_reason_standard=NotJoiningReasonStandard.PRICE,
        )

        # Lead 6: Lost with custom reason
        create_lead(
            gym=gym,
            first_name="L6",
            phone="+1006",
            stage=LeadStageEnum.NOT_JOINING,
            not_joining_custom_reason_id=custom_reason.id,
        )

        res = owner_client.get(
            f"/api/v1/reports/leads-funnel/?gym_id={gym.id}&start_date={today - timedelta(days=1)}&end_date={today + timedelta(days=1)}"
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.data

        assert data["total_leads"] == 6
        assert data["funnel_stages"]["new"] == 1
        assert data["funnel_stages"]["contacted"] == 1
        assert data["funnel_stages"]["trial_booked"] == 1
        assert data["funnel_stages"]["joined"] == 1
        assert data["funnel_stages"]["lost"] == 2

        # Rates
        assert data["conversion_rates"]["overall_conversion_rate_percentage"] == round(1 / 6 * 100, 2)
        assert data["conversion_rates"]["drop_off_rate_percentage"] == round(2 / 6 * 100, 2)

        # Lost reason distributions
        reasons = [r["reason"] for r in data["lost_reason_distribution"]]
        assert NotJoiningReasonStandard.PRICE in reasons
        assert "Moved to another city" in reasons

    def test_trainer_workload_metrics(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]
        trainer_assignment = report_gym_setup["trainer_assignment"]

        # Assign member to trainer
        member = report_gym_setup["member"]
        template = create_routine_template(gym=gym, template_name="Legs Day")
        assign_routine_to_member(
            gym=gym,
            member=member,
            source_template_id=template.id,
            prescribed_by_staff_id=trainer_assignment.id,
        )

        res = owner_client.get(f"/api/v1/reports/trainer-workload/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_200_OK
        data = res.data

        assert data["total_active_staff"] >= 2
        assert data["total_assigned_members"] >= 1
        assert data["total_active_routines"] >= 1

        # Locate trainer in trainers array
        trainer_data = next((t for t in data["trainers"] if t["staff_assignment_id"] == str(trainer_assignment.id)), None)
        assert trainer_data is not None
        assert trainer_data["assigned_members_count"] >= 1
        assert trainer_data["active_routines_count"] >= 1


# ==============================================================================
# 5. BOUNDARY CONDITIONS & ZERO-DIVISION SAFETY
# ==============================================================================

@pytest.mark.django_db
class TestReportsEmptyGymZeroDivision:
    def test_empty_gym_returns_clean_zeroes_without_error(self, report_gym_setup):
        gym_b = report_gym_setup["gym_b"]
        other_client = report_gym_setup["other_client"]

        # 1. Dashboard summary
        res = other_client.get(f"/api/v1/dashboard/summary/?gym_id={gym_b.id}")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["headline_metrics"]["total_members"] == 0
        assert res.data["headline_metrics"]["todays_revenue"] == 0.0

        # 2. Revenue report
        res = other_client.get(f"/api/v1/reports/revenue/?gym_id={gym_b.id}")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["total_revenue"] == 0.0
        assert res.data["average_transaction_value"] == 0.0
        assert len(res.data["payment_method_breakdown"]) == 0

        # 3. Membership growth report
        res = other_client.get(f"/api/v1/reports/membership-growth/?gym_id={gym_b.id}")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["total_members"] == 0
        assert res.data["churn_rate_percentage"] == 0.0

        # 4. Lead funnel report
        res = other_client.get(f"/api/v1/reports/leads-funnel/?gym_id={gym_b.id}")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["total_leads"] == 0
        assert res.data["conversion_rates"]["overall_conversion_rate_percentage"] == 0.0
        assert res.data["conversion_rates"]["drop_off_rate_percentage"] == 0.0

        # 5. Trainer workload report
        res = other_client.get(f"/api/v1/reports/trainer-workload/?gym_id={gym_b.id}")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["total_active_staff"] == 1
        assert res.data["total_assigned_members"] == 0
        assert res.data["total_active_routines"] == 0
        assert res.data["average_members_per_trainer"] == 0.0


# ==============================================================================
# 6. HTTP METHOD NOT ALLOWED (405) & MALFORMED GYM ID
# ==============================================================================

@pytest.mark.django_db
class TestReportsHTTPMethodsAndBadUUID:
    ENDPOINTS = [
        "/api/v1/dashboard/summary/",
        "/api/v1/reports/revenue/",
        "/api/v1/reports/membership-growth/",
        "/api/v1/reports/leads-funnel/",
        "/api/v1/reports/trainer-workload/",
    ]

    def test_http_methods_not_allowed_405(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        for ep in self.ENDPOINTS:
            res_post = owner_client.post(f"{ep}?gym_id={gym.id}", {})
            assert res_post.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, f"POST allowed on {ep}"

            res_put = owner_client.put(f"{ep}?gym_id={gym.id}", {})
            assert res_put.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, f"PUT allowed on {ep}"

            res_delete = owner_client.delete(f"{ep}?gym_id={gym.id}")
            assert res_delete.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, f"DELETE allowed on {ep}"

    def test_malformed_gym_id_returns_400_or_404(self, report_gym_setup):
        owner_client = report_gym_setup["owner_client"]

        for ep in self.ENDPOINTS:
            res = owner_client.get(f"{ep}?gym_id=not-a-uuid")
            assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)

            res_missing = owner_client.get(ep)
            assert res_missing.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 7. DATA TYPE MISMATCHES (TYPE JUGGLING)
# ==============================================================================

@pytest.mark.django_db
class TestPhase8TypeJugglingAndDataTypes:
    ENDPOINTS = [
        "/api/v1/dashboard/summary/",
        "/api/v1/reports/revenue/",
        "/api/v1/reports/membership-growth/",
        "/api/v1/reports/leads-funnel/",
        "/api/v1/reports/trainer-workload/",
    ]
    DATE_ENDPOINTS = [
        "/api/v1/reports/revenue/",
        "/api/v1/reports/membership-growth/",
        "/api/v1/reports/leads-funnel/",
    ]

    @pytest.mark.parametrize("bad_val", [
        12345,
        123.45,
        True,
        False,
        "null",
        "undefined",
        "None",
    ])
    def test_gym_id_type_juggling_handled_gracefully(self, report_gym_setup, bad_val):
        owner_client = report_gym_setup["owner_client"]
        for ep in self.ENDPOINTS:
            res = owner_client.get(f"{ep}?gym_id={bad_val}")
            assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize("bad_date", [
        12345,
        True,
        12.34,
        "true",
        "null",
        "NaN",
    ])
    def test_date_params_type_juggling_handled_gracefully(self, report_gym_setup, bad_date):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]
        for ep in self.DATE_ENDPOINTS:
            res_start = owner_client.get(f"{ep}?gym_id={gym.id}&start_date={bad_date}")
            assert res_start.status_code == status.HTTP_400_BAD_REQUEST
            assert res_start.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

            res_end = owner_client.get(f"{ep}?gym_id={gym.id}&end_date={bad_date}")
            assert res_end.status_code == status.HTTP_400_BAD_REQUEST
            assert res_end.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==============================================================================
# 8. BOUNDARY & LENGTH EDGE CASES
# ==============================================================================

@pytest.mark.django_db
class TestPhase8BoundariesAndLengths:
    DATE_ENDPOINTS = [
        "/api/v1/reports/revenue/",
        "/api/v1/reports/membership-growth/",
        "/api/v1/reports/leads-funnel/",
    ]

    def test_whitespace_and_blank_query_values(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        # Blank gym_id
        res = owner_client.get(f"/api/v1/dashboard/summary/?gym_id=")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Whitespace-only gym_id
        res_ws = owner_client.get(f"/api/v1/dashboard/summary/?gym_id=%20%20%20")
        assert res_ws.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)

        # Whitespace-only dates
        for ep in self.DATE_ENDPOINTS:
            res_date = owner_client.get(f"{ep}?gym_id={gym.id}&start_date=%20%20%20")
            assert res_date.status_code == status.HTTP_400_BAD_REQUEST
            assert "Invalid date format" in str(res_date.data)

    def test_extreme_length_strings(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]
        huge_str = "a" * 10000

        # Huge gym_id
        res = owner_client.get(f"/api/v1/dashboard/summary/?gym_id={huge_str}")
        assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)
        assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

        # Huge date strings
        for ep in self.DATE_ENDPOINTS:
            res_date = owner_client.get(f"{ep}?gym_id={gym.id}&start_date={huge_str}")
            assert res_date.status_code == status.HTTP_400_BAD_REQUEST
            assert res_date.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_leading_and_trailing_whitespace_trimmed_or_handled(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        for ep in self.DATE_ENDPOINTS:
            res = owner_client.get(f"{ep}?gym_id={gym.id}&start_date=%202026-01-01%20&end_date=%202026-01-31%20")
            assert res.status_code == status.HTTP_200_OK
            assert res.data["start_date"] == "2026-01-01"
            assert res.data["end_date"] == "2026-01-31"

    def test_date_range_exact_boundaries(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        for ep in self.DATE_ENDPOINTS:
            # Same day (min range: 0 days)
            res_same = owner_client.get(f"{ep}?gym_id={gym.id}&start_date=2026-03-15&end_date=2026-03-15")
            assert res_same.status_code == status.HTTP_200_OK

            # Exactly 1 day inverted (min - 1)
            res_inv = owner_client.get(f"{ep}?gym_id={gym.id}&start_date=2026-03-16&end_date=2026-03-15")
            assert res_inv.status_code == status.HTTP_400_BAD_REQUEST
            assert "'start_date' cannot be after 'end_date'" in str(res_inv.data)


# ==============================================================================
# 9. MISSING, EXTRA & MALFORMED FIELDS
# ==============================================================================

@pytest.mark.django_db
class TestPhase8MissingExtraAndMalformedFields:
    ENDPOINTS = [
        "/api/v1/dashboard/summary/",
        "/api/v1/reports/revenue/",
        "/api/v1/reports/membership-growth/",
        "/api/v1/reports/leads-funnel/",
        "/api/v1/reports/trainer-workload/",
    ]

    def test_hundred_garbage_query_params_ignored_without_500(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        garbage_params = "&".join(f"garbage_key_{i}=garbage_val_{i}" for i in range(120))
        for ep in self.ENDPOINTS:
            res = owner_client.get(f"{ep}?gym_id={gym.id}&{garbage_params}")
            assert res.status_code == status.HTTP_200_OK, f"Failed on {ep}"
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_server_controlled_and_mass_assignment_fields_in_query(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        for ep in self.ENDPOINTS:
            res = owner_client.get(f"{ep}?gym_id={gym.id}&is_superuser=true&role=admin&total_revenue=9999999")
            assert res.status_code == status.HTTP_200_OK
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_duplicate_query_params_handled(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res = owner_client.get(
            f"/api/v1/reports/revenue/?gym_id={gym.id}&gym_id={gym.id}&start_date=2026-01-01&start_date=2026-01-05"
        )
        assert res.status_code == status.HTTP_200_OK
        assert res.data["start_date"] == "2026-01-05"


# ==============================================================================
# 10. FORMAT-SPECIFIC INVALID INPUTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase8FormatSpecificInvalidInputs:
    DATE_ENDPOINTS = [
        "/api/v1/reports/revenue/",
        "/api/v1/reports/membership-growth/",
        "/api/v1/reports/leads-funnel/",
    ]

    @pytest.mark.parametrize("invalid_date", [
        "2026-13-45",
        "2026-02-29",
        "31/12/2026",
        "12-31-2026",
        "2026.01.01",
        "today",
        "yesterday",
        "1740000000",
        "2026-01-01T00:00:00",
        "2026-1-1",
        "10000-01-01",
    ])
    def test_invalid_date_formats_rejected_with_400(self, report_gym_setup, invalid_date):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        for ep in self.DATE_ENDPOINTS:
            res_start = owner_client.get(f"{ep}?gym_id={gym.id}&start_date={invalid_date}")
            assert res_start.status_code == status.HTTP_400_BAD_REQUEST
            assert res_start.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

            res_end = owner_client.get(f"{ep}?gym_id={gym.id}&end_date={invalid_date}")
            assert res_end.status_code == status.HTTP_400_BAD_REQUEST
            assert res_end.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_leap_year_february_29_handled_cleanly(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        # 2024 is a leap year (Feb 29 exists)
        res_leap = owner_client.get(
            f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date=2024-02-01&end_date=2024-02-29"
        )
        assert res_leap.status_code == status.HTTP_200_OK

        # 2025 is not a leap year (Feb 29 does not exist)
        res_non_leap = owner_client.get(
            f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date=2025-02-01&end_date=2025-02-29"
        )
        assert res_non_leap.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_uuid", [
        "not-a-uuid",
        "12345",
        "g" * 36,
        "00000000-0000-0000-0000-00000000000g",
        "0",
        "-1",
    ])
    def test_invalid_uuid_formats_rejected(self, report_gym_setup, invalid_uuid):
        owner_client = report_gym_setup["owner_client"]
        res = owner_client.get(f"/api/v1/dashboard/summary/?gym_id={invalid_uuid}")
        assert res.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)
        assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_nonexistent_valid_uuid_returns_404(self, report_gym_setup):
        owner_client = report_gym_setup["owner_client"]
        non_existent_uuid = str(uuid.uuid4())
        res = owner_client.get(f"/api/v1/dashboard/summary/?gym_id={non_existent_uuid}")
        assert res.status_code == status.HTTP_404_NOT_FOUND
        assert "Gym not found" in str(res.data)


# ==============================================================================
# 11. SECURITY & INJECTION TESTING (SQLi, XSS, Path Traversal, Unicode)
# ==============================================================================

@pytest.mark.django_db
class TestPhase8SecurityAndInjections:
    ENDPOINTS = [
        "/api/v1/dashboard/summary/",
        "/api/v1/reports/revenue/",
        "/api/v1/reports/membership-growth/",
        "/api/v1/reports/leads-funnel/",
        "/api/v1/reports/trainer-workload/",
    ]

    @pytest.mark.parametrize("sqli_payload", [
        "' OR 1=1 --",
        '" OR ""="',
        "'; DROP TABLE gyms; --",
        "UNION SELECT NULL, NULL, NULL --",
        "1' AND SLEEP(5) --",
        "admin'--",
    ])
    def test_sqli_payloads_in_parameters_blocked(self, report_gym_setup, sqli_payload):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res_gym = owner_client.get(f"/api/v1/dashboard/summary/?gym_id={sqli_payload}")
        assert res_gym.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)
        assert res_gym.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

        res_date = owner_client.get(f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date={sqli_payload}")
        assert res_date.status_code == status.HTTP_400_BAD_REQUEST
        assert res_date.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(document.cookie)>",
        "javascript:alert('pwned')",
        "<svg/onload=alert('xss')>",
    ])
    def test_xss_payloads_in_parameters_blocked(self, report_gym_setup, xss_payload):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res_gym = owner_client.get(f"/api/v1/dashboard/summary/?gym_id={xss_payload}")
        assert res_gym.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)

        res_date = owner_client.get(f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date={xss_payload}")
        assert res_date.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("path_payload", [
        "../../etc/passwd",
        "..%2F..%2Fetc%2Fpasswd",
        "/etc/shadow",
        "..\..\windows\system32",
    ])
    def test_path_traversal_payloads_blocked(self, report_gym_setup, path_payload):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res_gym = owner_client.get(f"/api/v1/dashboard/summary/?gym_id={path_payload}")
        assert res_gym.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)

        res_date = owner_client.get(f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date={path_payload}")
        assert res_date.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("unicode_payload", [
        "🏋️‍♂️💪🔥📊",
        "تقرير اللياقة البدنية والتحليلات",
        "דוח אנליטיקה וביצועים של חדר כושר",
        "月次売上レポートと会員獲得メトリクス",
        "Z̡̢͏a̴̴͏l̶g̢o̷ ̴T͏e̷x̶t",
    ])
    def test_unicode_and_adversarial_encoding_resilience(self, report_gym_setup, unicode_payload):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res_gym = owner_client.get(f"/api/v1/dashboard/summary/?gym_id={unicode_payload}")
        assert res_gym.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND)
        assert res_gym.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR

        res_date = owner_client.get(f"/api/v1/reports/revenue/?gym_id={gym.id}&start_date={unicode_payload}")
        assert res_date.status_code == status.HTTP_400_BAD_REQUEST
        assert res_date.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==============================================================================
# 12. AUTHENTICATION, REVOCATION & USER STATUS EDGE CASES
# ==============================================================================

@pytest.mark.django_db
class TestPhase8AuthAndUserStatusEdgeCases:
    ENDPOINTS = [
        "/api/v1/dashboard/summary/",
        "/api/v1/reports/revenue/",
        "/api/v1/reports/membership-growth/",
        "/api/v1/reports/leads-funnel/",
        "/api/v1/reports/trainer-workload/",
    ]

    def test_malformed_authorization_headers(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        client = APIClient()

        # Missing token after Bearer
        client.credentials(HTTP_AUTHORIZATION="Bearer ")
        res1 = client.get(f"/api/v1/dashboard/summary/?gym_id={gym.id}")
        assert res1.status_code == status.HTTP_401_UNAUTHORIZED

        # Garbage token
        client.credentials(HTTP_AUTHORIZATION="Bearer totally.invalid.jwt.token")
        res2 = client.get(f"/api/v1/dashboard/summary/?gym_id={gym.id}")
        assert res2.status_code == status.HTTP_401_UNAUTHORIZED

        # Basic auth instead of Bearer
        client.credentials(HTTP_AUTHORIZATION="Basic dXNlcjpwYXNz")
        res3 = client.get(f"/api/v1/dashboard/summary/?gym_id={gym.id}")
        assert res3.status_code == status.HTTP_401_UNAUTHORIZED

    def test_suspended_gym_owner_blocked_with_403(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner = report_gym_setup["owner"]
        owner_client = report_gym_setup["owner_client"]

        owner.status = UserStatus.SUSPENDED
        owner.save()

        for ep in self.ENDPOINTS:
            res = owner_client.get(f"{ep}?gym_id={gym.id}")
            assert res.status_code == status.HTTP_403_FORBIDDEN, f"Suspended owner allowed on {ep}"
            assert "inactive or suspended" in str(res.data)

    def test_inactive_user_account_rejected_with_401_or_403(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        staff_user = report_gym_setup["staff_user"]
        staff_client = report_gym_setup["staff_client"]

        staff_user.is_active = False
        staff_user.save()

        for ep in self.ENDPOINTS:
            res = staff_client.get(f"{ep}?gym_id={gym.id}")
            assert res.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_superuser_access_allowed(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        admin_user, admin_client, _ = create_user_with_tokens(email="admin.phase8@manygym.com")
        admin_user.is_superuser = True
        admin_user.is_staff = True
        admin_user.save()

        for ep in self.ENDPOINTS:
            res = admin_client.get(f"{ep}?gym_id={gym.id}")
            assert res.status_code == status.HTTP_200_OK


# ==============================================================================
# 13. QUERY PARAMETERS, FILTERS & UNEXPECTED PAGINATION
# ==============================================================================

@pytest.mark.django_db
class TestPhase8QueryParamsAndFilters:
    ENDPOINTS = [
        "/api/v1/dashboard/summary/",
        "/api/v1/reports/revenue/",
        "/api/v1/reports/membership-growth/",
        "/api/v1/reports/leads-funnel/",
        "/api/v1/reports/trainer-workload/",
    ]

    @pytest.mark.parametrize("bad_pagination", [
        "?page=0",
        "?page=-1",
        "?page=abc",
        "?page=999999",
        "?page_size=0",
        "?page_size=-10",
        "?page_size=1000000",
        "?search=test&ordering=-created_at",
    ])
    def test_unexpected_pagination_and_search_ignored_without_500(self, report_gym_setup, bad_pagination):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        for ep in self.ENDPOINTS:
            res = owner_client.get(f"{ep}?gym_id={gym.id}&{bad_pagination.lstrip('?')}")
            assert res.status_code == status.HTTP_200_OK
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==============================================================================
# 14. RESPONSE VALIDATION & CONTRACT ENVELOPE CONSISTENCY
# ==============================================================================

@pytest.mark.django_db
class TestPhase8ResponseContractAndStructure:
    def test_dashboard_summary_envelope_structure(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res = owner_client.get(f"/api/v1/dashboard/summary/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_200_OK
        data = res.data

        assert "gym_id" in data
        assert "gym_name" in data
        assert "generated_at" in data
        assert "headline_metrics" in data

        metrics = data["headline_metrics"]
        expected_metric_keys = {
            "total_members",
            "total_active_members",
            "expiring_memberships_next_7_days",
            "expiring_memberships_next_30_days",
            "new_leads_this_week",
            "pending_next_moves_today",
            "overdue_next_moves",
            "todays_scheduled_trials",
            "todays_revenue",
            "current_month_revenue",
        }
        assert set(metrics.keys()) == expected_metric_keys
        for k in expected_metric_keys:
            assert isinstance(metrics[k], (int, float)), f"Metric {k} must be numeric, got {type(metrics[k])}"

    def test_revenue_report_envelope_structure(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res = owner_client.get(f"/api/v1/reports/revenue/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_200_OK
        data = res.data

        expected_keys = {
            "gym_id",
            "start_date",
            "end_date",
            "total_revenue",
            "total_transactions",
            "average_transaction_value",
            "payment_method_breakdown",
            "plan_distribution",
            "daily_breakdown",
        }
        assert set(data.keys()) == expected_keys
        assert isinstance(data["total_revenue"], float)
        assert isinstance(data["total_transactions"], int)
        assert isinstance(data["average_transaction_value"], float)
        assert isinstance(data["payment_method_breakdown"], list)
        assert isinstance(data["plan_distribution"], list)
        assert isinstance(data["daily_breakdown"], list)

    def test_membership_growth_envelope_structure(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res = owner_client.get(f"/api/v1/reports/membership-growth/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_200_OK
        data = res.data

        expected_keys = {
            "gym_id",
            "start_date",
            "end_date",
            "total_members",
            "active_subscriptions",
            "new_members_in_period",
            "new_subscriptions_in_period",
            "cancelled_subscriptions_in_period",
            "net_growth",
            "churn_rate_percentage",
            "status_breakdown",
            "plan_breakdown",
        }
        assert set(data.keys()) == expected_keys
        assert isinstance(data["churn_rate_percentage"], float)

    def test_leads_funnel_envelope_structure(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res = owner_client.get(f"/api/v1/reports/leads-funnel/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_200_OK
        data = res.data

        expected_keys = {
            "gym_id",
            "start_date",
            "end_date",
            "total_leads",
            "funnel_stages",
            "conversion_rates",
            "stage_breakdown",
            "lost_reason_distribution",
            "source_breakdown",
        }
        assert set(data.keys()) == expected_keys
        assert set(data["funnel_stages"].keys()) == {"new", "contacted", "trial_booked", "joined", "lost"}
        assert set(data["conversion_rates"].keys()) == {
            "trial_booking_rate_percentage",
            "trial_to_join_rate_percentage",
            "overall_conversion_rate_percentage",
            "drop_off_rate_percentage",
        }

    def test_trainer_workload_envelope_structure(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res = owner_client.get(f"/api/v1/reports/trainer-workload/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_200_OK
        data = res.data

        expected_keys = {
            "gym_id",
            "gym_name",
            "total_active_staff",
            "total_assigned_members",
            "total_active_routines",
            "average_members_per_trainer",
            "trainers",
        }
        assert set(data.keys()) == expected_keys
        assert isinstance(data["trainers"], list)


# ==============================================================================
# 15. REGRESSION & BUG FIX VERIFICATION
# ==============================================================================

@pytest.mark.django_db
class TestPhase8BugFixRegression:
    def test_year_0001_subtraction_overflow_handled_gracefully(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        for ep in [
            "/api/v1/reports/revenue/",
            "/api/v1/reports/membership-growth/",
            "/api/v1/reports/leads-funnel/",
        ]:
            res = owner_client.get(f"{ep}?gym_id={gym.id}&end_date=0001-01-01")
            assert res.status_code == status.HTTP_400_BAD_REQUEST
            assert res.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
            assert "out of valid bounds" in str(res.data)

    def test_nonexistent_report_subpath_returns_404(self, report_gym_setup):
        gym = report_gym_setup["gym"]
        owner_client = report_gym_setup["owner_client"]

        res = owner_client.get(f"/api/v1/reports/nonexistent-report/?gym_id={gym.id}")
        assert res.status_code == status.HTTP_404_NOT_FOUND
