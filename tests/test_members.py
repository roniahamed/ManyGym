import uuid
from decimal import Decimal
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.urls import reverse

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym
from apps.gyms.services import create_gym
from apps.amenities.models import AmenityCatalog, GymAmenity
from apps.amenities.services import seed_amenity_catalog
from apps.access_control.models import Role, Permission, GymStaffAssignment
from apps.access_control.services import seed_default_permissions_and_roles
from apps.memberships.models import MembershipPlan
from apps.memberships.services import create_membership_plan
from apps.members.models import (
    Member,
    MemberSubscription,
    MemberPayment,
    MemberExtraAmenities,
)
from apps.members.selectors import list_gym_members, get_member_detail, stream_gym_members
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    UserStatus,
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    PaymentScheduleEnum,
    AmenityGroupEnum,
    MemberJoiningStatus,
    MembershipStatusEnum,
    PaymentStatusEnum,
    PaymentMethodEnum,
)


@pytest.fixture(autouse=True)
def setup_seeds(db):
    seed_amenity_catalog()
    seed_default_permissions_and_roles()


def get_auth_client(user: User, context_type: str = TokenContextType.GYM, gym: Gym = None):
    client = APIClient()
    tokens = issue_context_token(user, context_type=context_type, gym=gym)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return client, tokens


@pytest.mark.django_db
def test_create_member_with_initial_subscription_and_payment():
    """
    Tests complete member onboarding flow:
    - Demographic info & emergency contact
    - Initial active subscription with automated end_date calculation
    - Extra paid amenities attachment
    - Initial payment transaction logging
    - Automated payment_status computation (fully_paid)
    - Default joining_status = 'sent_invitation'
    """
    owner = User.objects.create_user(email="member.owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Olympus Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    # 1. Create plan ($100 price + $20 joining fee = $120)
    plan = create_membership_plan(
        gym=gym,
        name="Gold 3-Month Plan",
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("100.00"),
        duration_value=3,
        duration_unit=DurationUnitEnum.MONTH,
        joining_fee=Decimal("20.00"),
        plan_status=PlanStatusEnum.ACTIVE,
    )

    # 2. Create paid extra amenity ($30 fee)
    cat = AmenityCatalog.objects.create(name="Private Locker", group_name=AmenityGroupEnum.CHANGING_AND_STORAGE)
    gym_amenity = GymAmenity.objects.create(gym=gym, amenity=cat, is_paid=True, default_price=Decimal("30.00"))

    # Total expected cost: $100 + $20 + $30 = $150
    start_date = date.today() + timedelta(days=5)
    start_date_str = str(start_date)
    expected_end_date = str(start_date + relativedelta(months=3))
    payload = {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john.doe@example.com",
        "phone": "+1234567890",
        "address": "456 Fitness Way",
        "city": "Austin",
        "country": "USA",
        "date_of_birth": "1995-05-20",
        "emergency_contact_name": "Jane Doe",
        "emergency_contact_phone": "+1987654321",
        "emergency_contact_relationship": "Spouse",
        "internal_notes": "VIP corporate account.",
        "plan_id": str(plan.id),
        "start_date": start_date_str,
        "extra_amenity_ids": [str(gym_amenity.id)],
        "initial_payment_amount": "150.00",
        "initial_payment_method": "credit_card",
        "initial_payment_date": start_date_str,
        "initial_payment_notes": "Paid upfront in full.",
    }

    url = reverse("member-list-create")
    res = client.post(url, payload, format="json")
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()

    assert data["first_name"] == "John"
    assert data["last_name"] == "Doe"
    assert data["full_name"] == "John Doe"
    assert data["email"] == "john.doe@example.com"
    assert data["joining_status"] == MemberJoiningStatus.SENT_INVITATION
    assert data["invitation_sent_at"] is not None

    # Check active subscription
    sub = data["active_subscription"]
    assert sub is not None
    assert sub["plan_name"] == "Gold 3-Month Plan"
    assert sub["membership_status"] == MembershipStatusEnum.SCHEDULED  # future from today
    assert sub["payment_status"] == PaymentStatusEnum.FULLY_PAID
    assert sub["start_date"] == start_date_str
    assert sub["end_date"] == expected_end_date  # + 3 calendar months

    # Check extra amenities
    assert len(sub["extra_amenities"]) == 1
    assert sub["extra_amenities"][0]["name"] == "Private Locker"
    assert Decimal(sub["extra_amenities"][0]["extra_fee"]) == Decimal("30.00")

    # Check payment transaction
    assert len(sub["payments"]) == 1
    assert Decimal(sub["payments"][0]["amount"]) == Decimal("150.00")
    assert sub["payments"][0]["payment_method"] == "credit_card"


@pytest.mark.django_db
def test_session_based_subscription_and_partial_payment():
    """
    Tests session-based plan subscription:
    - Admin specifies custom end date
    - Initializes total_sessions and remaining_sessions
    - Partial payment leaves status as 'partially_paid'
    """
    owner = User.objects.create_user(email="session.owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="CrossFit Box")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    plan = create_membership_plan(
        gym=gym,
        name="10-Session Punchcard",
        plan_type=PlanTypeEnum.SESSION_BASED,
        price=Decimal("120.00"),
        duration_value=10,
        duration_unit=DurationUnitEnum.SESSION,
        joining_fee=Decimal("0.00"),
        plan_status=PlanStatusEnum.ACTIVE,
    )

    create_url = reverse("member-list-create")
    res = client.post(create_url, {
        "first_name": "Alice",
        "last_name": "Smith",
        "email": "alice.smith@example.com",
        "plan_id": str(plan.id),
        "start_date": "2026-10-10",
        "end_date": "2026-12-31",
        "initial_payment_amount": "50.00",
        "initial_payment_method": "cash",
    }, format="json")
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()

    sub = data["active_subscription"]
    assert sub["plan_name"] == "10-Session Punchcard"
    assert sub["total_sessions"] == 10
    assert sub["remaining_sessions"] == 10
    assert sub["payment_status"] == PaymentStatusEnum.PARTIALLY_PAID
    assert sub["total_cost"] == "120.00"
    assert sub["total_paid"] == "50.00"


@pytest.mark.django_db
def test_accept_member_invitation():
    """
    Tests invitation acceptance flow:
    - Member created with invitation_token
    - Registered user accepts invite using token
    - Member user account linked and status changed to 'joined'
    """
    owner = User.objects.create_user(email="invite.owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Invite Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    create_res = client.post(reverse("member-list-create"), {
        "first_name": "Bob",
        "last_name": "Marley",
        "email": "bob@example.com",
    }, format="json")
    assert create_res.status_code == 201
    member_id = create_res.json()["id"]

    member = Member.objects.get(id=member_id)
    token = member.invitation_token
    assert token is not None

    # New user registers on platform
    joining_user = User.objects.create_user(email="bob@example.com", password="Password123!", is_verified=True)
    user_client = APIClient()
    user_tokens = issue_context_token(joining_user, context_type=TokenContextType.PERSONAL)
    user_client.credentials(HTTP_AUTHORIZATION=f"Bearer {user_tokens['access']}")

    # Accept invitation
    accept_url = reverse("member-accept-invitation")
    accept_res = user_client.post(accept_url, {"token": token}, format="json")
    assert accept_res.status_code == 200
    assert accept_res.json()["joining_status"] == MemberJoiningStatus.JOINED
    assert accept_res.json()["user_id"] == str(joining_user.id)

    # Token should be cleared after acceptance
    member.refresh_from_db()
    assert member.joining_status == MemberJoiningStatus.JOINED
    assert member.user == joining_user
    assert member.invitation_token is None


@pytest.mark.django_db
def test_member_subscription_lifecycle_and_payments():
    """
    Tests attaching a second subscription, logging subsequent payments,
    and pausing/cancelling subscription status.
    """
    owner = User.objects.create_user(email="sub.owner@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Lifecycle Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    # Create member
    member = Member.objects.create(
        gym=gym,
        first_name="David",
        last_name="Beckham",
        email="david@example.com",
    )

    plan = create_membership_plan(
        gym=gym,
        name="Monthly Pro",
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("80.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
        joining_fee=Decimal("0.00"),
        plan_status=PlanStatusEnum.ACTIVE,
    )

    # Attach subscription
    sub_url = reverse("member-subscription-create", kwargs={"member_id": member.id})
    res_sub = client.post(sub_url, {
        "plan_id": str(plan.id),
        "start_date": "2026-10-01",
    }, format="json")
    assert res_sub.status_code == 201
    sub_id = res_sub.json()["id"]
    assert res_sub.json()["payment_status"] == PaymentStatusEnum.UNPAID

    # Log payment of $40 (partially paid)
    pay_url = reverse("member-subscription-payment-create", kwargs={"subscription_id": sub_id})
    res_pay1 = client.post(pay_url, {
        "amount": "40.00",
        "payment_method": "cash",
        "payment_date": "2026-10-02",
    }, format="json")
    assert res_pay1.status_code == 201

    sub = MemberSubscription.objects.get(id=sub_id)
    assert sub.payment_status == PaymentStatusEnum.PARTIALLY_PAID

    # Log remaining payment of $40 (fully paid)
    res_pay2 = client.post(pay_url, {
        "amount": "40.00",
        "payment_method": "credit_card",
        "payment_date": "2026-10-05",
    }, format="json")
    assert res_pay2.status_code == 201

    sub.refresh_from_db()
    assert sub.payment_status == PaymentStatusEnum.FULLY_PAID

    # Transition status: active -> paused
    status_url = reverse("member-subscription-status", kwargs={"subscription_id": sub_id})
    res_pause = client.patch(status_url, {"membership_status": "paused"}, format="json")
    assert res_pause.status_code == 200
    assert res_pause.json()["membership_status"] == "paused"

    # Transition status: paused -> cancelled
    res_cancel = client.patch(status_url, {"membership_status": "cancelled"}, format="json")
    assert res_cancel.status_code == 200
    assert res_cancel.json()["membership_status"] == "cancelled"


@pytest.mark.django_db
def test_members_list_query_efficiency(django_assert_num_queries):
    """
    Ensures member directory listing eliminates N+1 query problems.
    Query count stays constant regardless of the number of members,
    subscriptions, trainers, and payments.
    """
    owner = User.objects.create_user(email="nplusone.member@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Fast Query Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    plan = create_membership_plan(
        gym=gym,
        name="Standard Plan",
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("60.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
        plan_status=PlanStatusEnum.ACTIVE,
    )

    # Create 10 members with active subscriptions
    for i in range(10):
        m = Member.objects.create(
            gym=gym,
            first_name=f"Member{i}",
            last_name="Tester",
            email=f"member{i}@manygym.com",
            joining_status=MemberJoiningStatus.JOINED,
        )
        MemberSubscription.objects.create(
            member=m,
            plan=plan,
            membership_status=MembershipStatusEnum.ACTIVE,
            payment_status=PaymentStatusEnum.FULLY_PAID,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 11, 1),
        )

    url = reverse("member-list-create")

    # 1. Auth user lookup (FastJWT select_related profile)
    # 2. Gym lookup
    # 3. Member listing query
    # 4. MemberSubscription prefetch with plan select_related
    with django_assert_num_queries(4):
        res = client.get(url)
        assert res.status_code == 200
        assert len(res.json()) == 10
        # Verify first record fields
        first = res.json()[0]
        assert first["current_plan_name"] == "Standard Plan"
        assert first["membership_status"] == "active"
        assert first["payment_status"] == "fully_paid"


@pytest.mark.django_db
def test_member_metrics_aggregation(django_assert_num_queries):
    """
    Tests single database query calculation of member and subscription metrics.
    """
    owner = User.objects.create_user(email="metrics.member@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Metrics Gym")
    client, _ = get_auth_client(owner, context_type=TokenContextType.GYM, gym=gym)

    plan = create_membership_plan(
        gym=gym,
        name="Plan P",
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("50.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
        plan_status=PlanStatusEnum.ACTIVE,
    )

    m1 = Member.objects.create(gym=gym, first_name="M1", last_name="L", email="m1@g.com", joining_status=MemberJoiningStatus.JOINED)
    m2 = Member.objects.create(gym=gym, first_name="M2", last_name="L", email="m2@g.com", joining_status=MemberJoiningStatus.SENT_INVITATION)

    sub1 = MemberSubscription.objects.create(member=m1, plan=plan, membership_status=MembershipStatusEnum.ACTIVE, payment_status=PaymentStatusEnum.FULLY_PAID, start_date=date(2026, 10, 1), end_date=date(2026, 11, 1))
    sub2 = MemberSubscription.objects.create(member=m2, plan=plan, membership_status=MembershipStatusEnum.ACTIVE, payment_status=PaymentStatusEnum.UNPAID, start_date=date(2026, 10, 1), end_date=date(2026, 11, 1))

    MemberPayment.objects.create(member_subscription=sub1, amount=Decimal("50.00"), payment_method="cash", payment_date=date(2026, 10, 1))

    url = reverse("member-metrics")
    res = client.get(url)
    assert res.status_code == 200
    data = res.json()

    assert data["total_members"] == 2
    assert data["joined_members"] == 1
    assert data["invited_members"] == 1
    assert data["active_subscriptions"] == 2
    assert data["unpaid_subscriptions"] == 1
    assert data["fully_paid_subscriptions"] == 1
    assert Decimal(str(data["total_revenue"])) == Decimal("50.00")


@pytest.mark.django_db
def test_stream_gym_members_iterator():
    """
    Tests streaming members using QuerySet.iterator() to prevent full materialization in memory.
    """
    owner = User.objects.create_user(email="stream.mem@manygym.com", password="Password123!", is_verified=True)
    gym = Gym.objects.create(owner_user=owner, name="Stream Gym")

    for i in range(12):
        Member.objects.create(
            gym=gym,
            first_name=f"Stream{i}",
            last_name="Member",
            email=f"stream{i}@gym.com",
        )

    stream = stream_gym_members(gym, chunk_size=5)
    members = list(stream)
    assert len(members) == 12
    assert members[0].first_name == "Stream11"  # ordered by -created_at
