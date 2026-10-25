import time
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.core import mail
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User
from apps.gyms.models import Gym
from apps.memberships.models import MembershipPlan
from apps.members.models import Member, MemberSubscription
from apps.leads.models import Lead, LeadNextMove
from apps.access_control.models import GymStaffAssignment, Role
from apps.authentication.models import AuthToken
from apps.members.services import (
    reconcile_expired_subscriptions,
    send_subscription_expiry_reminders,
    create_member,
)
from apps.leads.services import send_lead_followup_reminders
from apps.authentication.services import cleanup_expired_tokens


@pytest.mark.django_db
class TestPhase9PerformanceAndQueryCount:
    @pytest.fixture(autouse=True)
    def setup_fixtures(self, db):
        settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
        if hasattr(mail, "outbox"):
            mail.outbox.clear()

        self.owner = User.objects.create_user(
            email=f"owner_{uuid.uuid4().hex[:6]}@perf.com",
            password="password123",
            first_name="OwnerPerf",
        )
        self.staff_user = User.objects.create_user(
            email=f"staff_{uuid.uuid4().hex[:6]}@perf.com",
            password="password123",
            first_name="StaffPerf",
        )
        self.gym = Gym.objects.create(
            owner_user=self.owner,
            name=f"Perf Gym {uuid.uuid4().hex[:6]}",
        )
        self.role, _ = Role.objects.get_or_create(gym=self.gym, name="Trainer")
        self.staff = GymStaffAssignment.objects.create(
            gym=self.gym,
            user=self.staff_user,
            role=self.role,
            status="active",
        )
        self.plan = MembershipPlan.objects.create(
            gym=self.gym,
            name="Perf Gold Plan",
            price=Decimal("150.00"),
            plan_type="fixed_period",
            duration_value=30,
            duration_unit="days",
        )
        self.today = timezone.localdate()

    def test_reconcile_subscriptions_query_count_and_scalability(self):
        """
        Verify reconcile_expired_subscriptions runs in exactly 2 SQL UPDATE queries,
        irrespective of how many subscriptions are being reconciled (O(1) query complexity).
        """
        # Create 30 members and subscriptions (15 expired, 15 scheduled to activate)
        members = [
            Member(gym=self.gym, first_name=f"Mem{i}", last_name="Perf", email=f"mem{i}@perf.com")
            for i in range(30)
        ]
        created_members = Member.objects.bulk_create(members)

        subs = []
        for i, m in enumerate(created_members):
            if i % 2 == 0:
                subs.append(
                    MemberSubscription(
                        member=m,
                        plan=self.plan,
                        membership_status="active",
                        start_date=self.today - timedelta(days=60),
                        end_date=self.today - timedelta(days=1),
                    )
                )
            else:
                subs.append(
                    MemberSubscription(
                        member=m,
                        plan=self.plan,
                        membership_status="scheduled",
                        start_date=self.today,
                        end_date=self.today + timedelta(days=30),
                    )
                )
        MemberSubscription.objects.bulk_create(subs)

        t0 = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            count = reconcile_expired_subscriptions()
        t1 = time.perf_counter()

        elapsed_ms = (t1 - t0) * 1000
        # Exactly 2 bulk update queries: 1 for active->expired, 1 for scheduled->active (plus atomic savepoints)
        update_queries = [q for q in queries if 'UPDATE' in q['sql']]
        assert len(update_queries) == 2, f"Expected exactly 2 UPDATE queries, got {len(update_queries)}: {[q['sql'] for q in queries]}"
        assert count == 15
        assert elapsed_ms < 100.0, f"Reconciliation took too long: {elapsed_ms:.2f}ms"

    def test_send_subscription_expiry_reminders_single_query_zero_n_plus_one(self):
        """
        Verify send_subscription_expiry_reminders executes in exactly 1 query using
        select_related and column projection (.only), eliminating N+1 across 4 related tables.
        """
        members = [
            Member(gym=self.gym, first_name=f"MemExp{i}", last_name="Perf", email=f"memexp{i}@perf.com")
            for i in range(20)
        ]
        created_members = Member.objects.bulk_create(members)

        subs = []
        for i, m in enumerate(created_members):
            days = 7 if i % 2 == 0 else 1
            subs.append(
                MemberSubscription(
                    member=m,
                    plan=self.plan,
                    membership_status="active",
                    start_date=self.today - timedelta(days=30),
                    end_date=self.today + timedelta(days=days),
                )
            )
        MemberSubscription.objects.bulk_create(subs)

        t0 = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            sent_count = send_subscription_expiry_reminders()
        t1 = time.perf_counter()

        elapsed_ms = (t1 - t0) * 1000
        # Exactly 1 query fetching all 20 subscriptions, members, plans, and gyms!
        assert len(queries) == 1, f"Expected 1 query (zero N+1), got {len(queries)}"
        assert sent_count == 20
        assert len(mail.outbox) == 20
        assert elapsed_ms < 200.0, f"Reminders dispatch took too long: {elapsed_ms:.2f}ms"

    def test_send_lead_followup_reminders_single_query_zero_n_plus_one(self):
        """
        Verify send_lead_followup_reminders executes in exactly 1 query using
        select_related and column projection (.only), eliminating N+1 across 5 related tables.
        """
        leads = [
            Lead(
                gym=self.gym,
                first_name=f"LeadPerf{i}",
                last_name="Test",
                phone="1234567890",
                email=f"leadperf{i}@perf.com",
                stage="new",
                assigned_staff=self.staff if i % 2 == 0 else None,
            )
            for i in range(20)
        ]
        created_leads = Lead.objects.bulk_create(leads)

        moves = [
            LeadNextMove(
                lead=lead,
                scheduled_date=self.today,
                short_description=f"Action item {i}",
                is_completed=False,
            )
            for i, lead in enumerate(created_leads)
        ]
        LeadNextMove.objects.bulk_create(moves)

        t0 = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            sent_count = send_lead_followup_reminders()
        t1 = time.perf_counter()

        elapsed_ms = (t1 - t0) * 1000
        # Exactly 1 query fetching all 20 moves, leads, staff, users, and gym owners!
        assert len(queries) == 1, f"Expected 1 query (zero N+1), got {len(queries)}"
        assert sent_count == 20
        assert len(mail.outbox) == 20
        assert elapsed_ms < 200.0, f"Lead reminders dispatch took too long: {elapsed_ms:.2f}ms"

    def test_cleanup_expired_tokens_single_query_and_performance(self):
        """
        Verify cleanup_expired_tokens executes in exactly 1 delete query with indexed range scan.
        """
        now = timezone.now()
        tokens = [
            AuthToken(
                user=self.owner,
                gym=self.gym,
                token_hash=f"token_hash_{uuid.uuid4().hex}",
                context_type="gym",
                expires_at=now - timedelta(hours=i + 1) if i < 15 else now + timedelta(days=i + 1),
            )
            for i in range(30)
        ]
        AuthToken.objects.bulk_create(tokens)

        t0 = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            deleted = cleanup_expired_tokens()
        t1 = time.perf_counter()

        elapsed_ms = (t1 - t0) * 1000
        assert len(queries) == 1, f"Expected 1 delete query, got {len(queries)}"
        assert deleted == 15
        assert elapsed_ms < 50.0, f"Token purge took too long: {elapsed_ms:.2f}ms"

    def test_member_resend_invitation_api_query_count_and_p95(self):
        """
        Verify POST /api/v1/members/<id>/resend-invitation/ executes within 3-5 queries and < 200ms.
        """
        member = create_member(
            gym=self.gym,
            first_name="ResendTarget",
            last_name="Perf",
            email=f"target_{uuid.uuid4().hex[:6]}@perf.com",
        )

        client = APIClient()
        client.force_authenticate(user=self.owner)

        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            with CaptureQueriesContext(connection) as queries:
                resp = client.post(f"/api/v1/members/{member.id}/resend-invitation/?gym_id={self.gym.id}")
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000)
            assert resp.status_code == status.HTTP_200_OK
            assert len(queries) <= 5, f"Expected <= 5 queries, got {len(queries)}"

        times.sort()
        p95 = times[int(len(times) * 0.95)]
        assert p95 < 200.0, f"Resend invitation p95 ({p95:.2f}ms) exceeded 200ms target"

    def test_member_accept_invitation_api_query_count_and_p95(self):
        """
        Verify POST /api/v1/members/accept-invitation/ executes within 6 queries and < 200ms.
        """
        member = create_member(
            gym=self.gym,
            first_name="AcceptTarget",
            last_name="Perf",
            email=f"accept_{uuid.uuid4().hex[:6]}@perf.com",
        )
        token = member.invitation_token

        new_user = User.objects.create_user(
            email=f"newuser_{uuid.uuid4().hex[:6]}@perf.com",
            password="password123",
        )
        client = APIClient()
        client.force_authenticate(user=new_user)

        t0 = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            resp = client.post(
                "/api/v1/members/accept-invitation/",
                {"token": token},
                format="json",
            )
        t1 = time.perf_counter()

        elapsed_ms = (t1 - t0) * 1000
        assert resp.status_code == status.HTTP_200_OK
        assert len(queries) <= 6, f"Expected <= 6 queries, got {len(queries)}"
        assert elapsed_ms < 200.0, f"Accept invitation took {elapsed_ms:.2f}ms, exceeded 200ms target"
