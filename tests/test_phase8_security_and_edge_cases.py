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
