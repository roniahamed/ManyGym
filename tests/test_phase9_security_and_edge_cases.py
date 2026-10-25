import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock
import pytest
from django.utils import timezone
from django.core import mail
from django.conf import settings

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym
from apps.gyms.services import create_gym
from apps.amenities.services import seed_amenity_catalog
from apps.access_control.models import Role, Permission, GymStaffAssignment
from apps.access_control.services import seed_default_permissions_and_roles
from apps.memberships.models import MembershipPlan
from apps.memberships.services import create_membership_plan
from apps.members.models import Member, MemberSubscription
from apps.members.services import (
    create_member,
    create_member_subscription,
    reconcile_expired_subscriptions,
    send_subscription_expiry_reminders,
)
from apps.members.tasks import (
    reconcile_expired_subscriptions_task,
    send_subscription_expiry_reminder_task,
    send_member_invitation_email,
)
from apps.leads.models import Lead, LeadNextMove
from apps.leads.services import (
    create_lead,
    schedule_next_move,
    send_lead_followup_reminders,
)
from apps.leads.tasks import send_lead_followup_reminder_task
from apps.authentication.models import AuthToken
from apps.authentication.services import (
    issue_context_token,
    cleanup_expired_tokens,
)
from apps.authentication.tasks import cleanup_expired_tokens_task
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
    LeadSourceEnum,
)


@pytest.fixture(autouse=True)
def setup_seeds(db):
    seed_amenity_catalog()
    seed_default_permissions_and_roles()


@pytest.fixture
def phase9_setup(db):
    # Gym Owner
    owner = User.objects.create_user(
        email="phase9.owner@manygym.com",
        password="SecurePassword123!",
        first_name="Owner",
        last_name="Phase9",
        is_verified=True,
        status=UserStatus.ACTIVE,
    )
    UserProfile.objects.create(user=owner)
    gym = create_gym(owner_user=owner, name="Phase 9 Automation Gym", timezone="UTC")

    # Staff
    staff_user = User.objects.create_user(
        email="phase9.staff@manygym.com",
        password="SecurePassword123!",
        first_name="StaffMember",
        last_name="Trainer",
        is_verified=True,
        status=UserStatus.ACTIVE,
    )
    UserProfile.objects.create(user=staff_user)
    staff_role = Role.objects.get(slug="staff")
    staff_assignment = GymStaffAssignment.objects.create(
        gym=gym,
        user=staff_user,
        role=staff_role,
        status=StaffStatus.ACTIVE,
    )

    # Membership Plan
    plan = create_membership_plan(
        gym=gym,
        name="Gold Automated Plan",
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("100.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    return {
        "owner": owner,
        "gym": gym,
        "staff_user": staff_user,
        "staff_assignment": staff_assignment,
        "plan": plan,
    }


# ==============================================================================
# 1. SUBSCRIPTION RECONCILIATION LIFECYCLE TESTS
# ==============================================================================

@pytest.mark.django_db
class TestSubscriptionReconciliation:
    def test_reconcile_expired_subscriptions_transitions_active_past_end_date(self, phase9_setup):
        gym = phase9_setup["gym"]
        plan = phase9_setup["plan"]
        today = timezone.localdate()

        # 1. Subscription ended yesterday (should expire)
        m1 = create_member(gym=gym, first_name="Past", last_name="One", email="past1@test.com")
        sub1 = create_member_subscription(member=m1, plan=plan, start_date=today - timedelta(days=35))
        sub1.end_date = today - timedelta(days=1)
        sub1.membership_status = MembershipStatusEnum.ACTIVE
        sub1.save()

        # 2. Subscription ended 10 days ago (should expire)
        m2 = create_member(gym=gym, first_name="Past", last_name="Two", email="past2@test.com")
        sub2 = create_member_subscription(member=m2, plan=plan, start_date=today - timedelta(days=40))
        sub2.end_date = today - timedelta(days=10)
        sub2.membership_status = MembershipStatusEnum.ACTIVE
        sub2.save()

        # 3. Active subscription ending in future (should NOT expire)
        m3 = create_member(gym=gym, first_name="Future", last_name="Three", email="future3@test.com")
        sub3 = create_member_subscription(member=m3, plan=plan, start_date=today)
        sub3.end_date = today + timedelta(days=30)
        sub3.membership_status = MembershipStatusEnum.ACTIVE
        sub3.save()

        # 4. Active subscription ending TODAY (should NOT expire today; expires tomorrow)
        m4 = create_member(gym=gym, first_name="TodayEnd", last_name="Four", email="today4@test.com")
        sub4 = create_member_subscription(member=m4, plan=plan, start_date=today - timedelta(days=30))
        sub4.end_date = today
        sub4.membership_status = MembershipStatusEnum.ACTIVE
        sub4.save()

        # 5. Paused subscription ended in past (should NOT expire; paused contracts are frozen)
        m5 = create_member(gym=gym, first_name="Paused", last_name="Five", email="paused5@test.com")
        sub5 = create_member_subscription(member=m5, plan=plan, start_date=today - timedelta(days=35))
        sub5.end_date = today - timedelta(days=2)
        sub5.membership_status = MembershipStatusEnum.PAUSED
        sub5.save()

        # Run reconciliation task
        updated = reconcile_expired_subscriptions_task()
        assert updated == 2

        # Verify DB states
        sub1.refresh_from_db()
        assert sub1.membership_status == MembershipStatusEnum.EXPIRED

        sub2.refresh_from_db()
        assert sub2.membership_status == MembershipStatusEnum.EXPIRED

        sub3.refresh_from_db()
        assert sub3.membership_status == MembershipStatusEnum.ACTIVE

        sub4.refresh_from_db()
        assert sub4.membership_status == MembershipStatusEnum.ACTIVE

        sub5.refresh_from_db()
        assert sub5.membership_status == MembershipStatusEnum.PAUSED

    def test_scheduled_subscriptions_activate_upon_reaching_start_date(self, phase9_setup):
        gym = phase9_setup["gym"]
        plan = phase9_setup["plan"]
        today = timezone.localdate()

        # Scheduled subscription with start_date == today
        m = create_member(gym=gym, first_name="Scheduled", last_name="Member", email="sched@test.com")
        sub = create_member_subscription(member=m, plan=plan, start_date=today)
        sub.membership_status = MembershipStatusEnum.SCHEDULED
        sub.end_date = today + timedelta(days=30)
        sub.save()

        reconcile_expired_subscriptions_task()

        sub.refresh_from_db()
        assert sub.membership_status == MembershipStatusEnum.ACTIVE

    def test_reconciliation_idempotency(self, phase9_setup):
        gym = phase9_setup["gym"]
        plan = phase9_setup["plan"]
        today = timezone.localdate()

        m = create_member(gym=gym, first_name="Idempotent", last_name="Test", email="idemp@test.com")
        sub = create_member_subscription(member=m, plan=plan, start_date=today - timedelta(days=35))
        sub.end_date = today - timedelta(days=1)
        sub.membership_status = MembershipStatusEnum.ACTIVE
        sub.save()

        # First run expires it
        assert reconcile_expired_subscriptions() == 1
        sub.refresh_from_db()
        assert sub.membership_status == MembershipStatusEnum.EXPIRED

        # Second run is idempotent (0 updated)
        assert reconcile_expired_subscriptions() == 0


# ==============================================================================
# 2. SUBSCRIPTION EXPIRY REMINDER TESTS
# ==============================================================================

@pytest.mark.django_db
class TestSubscriptionExpiryReminders:
    def test_send_expiry_reminders_for_7_days_and_1_day(self, phase9_setup):
        gym = phase9_setup["gym"]
        plan = phase9_setup["plan"]
        today = timezone.localdate()

        mail.outbox.clear()

        # 1. Expiring in 7 days (Should trigger reminder)
        m7 = create_member(gym=gym, first_name="Alice7", last_name="Seven", email="alice7@test.com")
        sub7 = create_member_subscription(member=m7, plan=plan, start_date=today - timedelta(days=23))
        sub7.end_date = today + timedelta(days=7)
        sub7.membership_status = MembershipStatusEnum.ACTIVE
        sub7.save()

        # 2. Expiring in 1 day (Should trigger reminder)
        m1 = create_member(gym=gym, first_name="Bob1", last_name="One", email="bob1@test.com")
        sub1 = create_member_subscription(member=m1, plan=plan, start_date=today - timedelta(days=29))
        sub1.end_date = today + timedelta(days=1)
        sub1.membership_status = MembershipStatusEnum.ACTIVE
        sub1.save()

        # 3. Expiring in 3 days (Should NOT trigger reminder)
        m3 = create_member(gym=gym, first_name="Charlie3", last_name="Three", email="charlie3@test.com")
        sub3 = create_member_subscription(member=m3, plan=plan, start_date=today - timedelta(days=27))
        sub3.end_date = today + timedelta(days=3)
        sub3.membership_status = MembershipStatusEnum.ACTIVE
        sub3.save()

        # 4. Inactive/Cancelled subscription ending in 1 day (Should NOT trigger reminder)
        m_canc = create_member(gym=gym, first_name="Cancelled", last_name="User", email="canc@test.com")
        sub_canc = create_member_subscription(member=m_canc, plan=plan, start_date=today - timedelta(days=29))
        sub_canc.end_date = today + timedelta(days=1)
        sub_canc.membership_status = MembershipStatusEnum.CANCELLED
        sub_canc.save()

        dispatched = send_subscription_expiry_reminder_task()
        assert dispatched == 2

        # Inspect outbox
        assert len(mail.outbox) == 2
        recipients = [m.to[0] for m in mail.outbox]
        assert "alice7@test.com" in recipients
        assert "bob1@test.com" in recipients

        # Inspect email content
        email_7 = next(m for m in mail.outbox if m.to[0] == "alice7@test.com")
        assert "expires in 7 days" in email_7.subject
        assert plan.name in email_7.body
        assert gym.name in email_7.body


# ==============================================================================
# 3. LEAD FOLLOW-UP REMINDER TESTS
# ==============================================================================

@pytest.mark.django_db
class TestLeadFollowUpReminders:
    def test_send_lead_followup_alerts_for_today_uncompleted_moves(self, phase9_setup):
        gym = phase9_setup["gym"]
        staff_assignment = phase9_setup["staff_assignment"]
        staff_user = phase9_setup["staff_user"]
        today = timezone.localdate()

        mail.outbox.clear()

        # 1. Uncompleted move scheduled for today with assigned staff (Should trigger)
        lead1 = create_lead(
            gym=gym,
            first_name="Prospect1",
            last_name="DueToday",
            phone="+1001",
            assigned_staff_id=staff_assignment.id,
            stage=LeadStageEnum.CONTACTED,
        )
        schedule_next_move(
            lead=lead1,
            scheduled_date=today,
            short_description="Call to confirm gym tour",
        )

        # 2. Completed move scheduled for today (Should NOT trigger)
        lead2 = create_lead(
            gym=gym,
            first_name="Prospect2",
            last_name="Completed",
            phone="+1002",
            assigned_staff_id=staff_assignment.id,
            stage=LeadStageEnum.CONTACTED,
        )
        move2 = schedule_next_move(
            lead=lead2,
            scheduled_date=today,
            short_description="Already talked to client",
        )
        move2.is_completed = True
        move2.save()

        # 3. Move scheduled for tomorrow (Should NOT trigger)
        lead3 = create_lead(
            gym=gym,
            first_name="Prospect3",
            last_name="Tomorrow",
            phone="+1003",
            assigned_staff_id=staff_assignment.id,
            stage=LeadStageEnum.NEW,
        )
        schedule_next_move(
            lead=lead3,
            scheduled_date=today + timedelta(days=1),
            short_description="Future call",
        )

        # 4. Uncompleted move with NO assigned staff (Should fallback to gym owner)
        owner = phase9_setup["owner"]
        lead4 = create_lead(
            gym=gym,
            first_name="UnassignedLead",
            last_name="OwnerFallback",
            phone="+1004",
            stage=LeadStageEnum.NEW,
        )
        schedule_next_move(
            lead=lead4,
            scheduled_date=today,
            short_description="Owner must follow up",
        )

        dispatched = send_lead_followup_reminder_task()
        assert dispatched == 2

        assert len(mail.outbox) == 2
        recipients = [m.to[0] for m in mail.outbox]
        assert staff_user.email in recipients
        assert owner.email in recipients


# ==============================================================================
# 4. TOKEN CLEANUP TASK TESTS
# ==============================================================================

@pytest.mark.django_db
class TestTokenCleanupTask:
    def test_cleanup_expired_tokens_purges_only_past_tokens(self, phase9_setup):
        owner = phase9_setup["owner"]
        gym = phase9_setup["gym"]
        now = timezone.now()

        # 1. Expired personal token (expired 2 hours ago)
        expired_token_1 = AuthToken.objects.create(
            user=owner,
            token_hash="hash_expired_personal",
            context_type=TokenContextType.PERSONAL,
            expires_at=now - timedelta(hours=2),
        )

        # 2. Expired gym token (expired 5 minutes ago)
        expired_token_2 = AuthToken.objects.create(
            user=owner,
            gym=gym,
            token_hash="hash_expired_gym",
            context_type=TokenContextType.GYM,
            expires_at=now - timedelta(minutes=5),
        )

        # 3. Active token (expires in 24 hours)
        active_token = AuthToken.objects.create(
            user=owner,
            gym=gym,
            token_hash="hash_active_gym",
            context_type=TokenContextType.GYM,
            expires_at=now + timedelta(hours=24),
        )

        deleted = cleanup_expired_tokens_task()
        assert deleted == 2

        assert not AuthToken.objects.filter(id=expired_token_1.id).exists()
        assert not AuthToken.objects.filter(id=expired_token_2.id).exists()
        assert AuthToken.objects.filter(id=active_token.id).exists()

    def test_cleanup_idempotency(self, phase9_setup):
        assert cleanup_expired_tokens_task() == 0


# ==============================================================================
# 5. MEMBER INVITATION TASK & CELERY BEAT SCHEDULE VERIFICATION
# ==============================================================================

@pytest.mark.django_db
class TestInvitationAndBeatConfiguration:
    def test_send_member_invitation_email_task_execution(self):
        mail.outbox.clear()
        res = send_member_invitation_email(
            member_id=str(uuid.uuid4()),
            email="invitee@manygym.com",
            first_name="Invitee",
            gym_name="Gold Gym",
            token="invitation-secret-token-123",
        )
        assert res is True
        assert len(mail.outbox) == 1
        sent = mail.outbox[0]
        assert "invitee@manygym.com" in sent.to
        assert "invitation-secret-token-123" in sent.body

    def test_celery_beat_schedule_registered_crons(self):
        from config.settings.base import CELERY_BEAT_SCHEDULE

        required_tasks = [
            "apps.members.tasks.reconcile_expired_subscriptions_task",
            "apps.members.tasks.send_subscription_expiry_reminder_task",
            "apps.leads.tasks.send_lead_followup_reminder_task",
            "apps.authentication.tasks.cleanup_expired_tokens_task",
        ]

        scheduled_task_names = [entry["task"] for entry in CELERY_BEAT_SCHEDULE.values()]
        for req in required_tasks:
            assert req in scheduled_task_names, f"Missing required Celery Beat cron: {req}"
