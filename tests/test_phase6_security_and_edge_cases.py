import uuid
import pytest
from rest_framework import status
from rest_framework.test import APIClient

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
from apps.members.services import create_member
from apps.routines.models import (
    RoutineTemplate,
    RoutineTemplateGoal,
    RoutineTemplateDay,
    RoutineTemplateExercise,
    MemberRoutine,
    MemberRoutineDay,
    MemberRoutineExercise,
)
from apps.routines.services import (
    create_routine_template,
    update_routine_template,
    delete_routine_template,
    assign_routine_to_member,
    customize_member_routine,
)
from apps.routines.selectors import (
    list_routine_templates,
    get_routine_template_detail,
    get_member_active_routine,
    list_member_routine_history,
    get_member_routine_by_id,
    stream_routine_templates,
)
from common.enums import (
    TokenContextType,
    UserStatus,
    PlanStatusEnum,
    PlanTypeEnum,
    DurationUnitEnum,
    StaffStatus,
    RoutineFormatEnum,
    RoutineLevelEnum,
    FitnessGoalEnum,
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


def create_user_with_tokens(email="test.phase6@manygym.com", is_verified=True, user_status=UserStatus.ACTIVE):
    user = User.objects.create_user(
        email=email,
        password="SecurePassword123!",
        first_name="Phase6",
        last_name="Tester",
        is_verified=is_verified,
        status=user_status,
    )
    UserProfile.objects.create(user=user)
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return user, client, tokens


def setup_gym_and_routine_context(owner_email="owner.phase6@manygym.com"):
    owner, client, _ = create_user_with_tokens(owner_email)
    gym = create_gym(owner_user=owner, name="Phase 6 Routine Gym")
    tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    plan = create_membership_plan(
        gym=gym,
        name="Phase 6 Workout Plan",
        description="Standard monthly gym membership plan for testing workout routines.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=100.00,
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    member_user, _, _ = create_user_with_tokens(f"member.{uuid.uuid4().hex[:8]}@manygym.com")
    member = create_member(
        gym=gym,
        first_name="Routine",
        last_name="Athlete",
        email=member_user.email,
        phone="+1234567890",
        plan_id=plan.id,
    )

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
        "member": member,
        "staff_user": staff_user,
        "staff_assignment": staff_assignment,
        "client": client,
        "tokens": tokens,
    }


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
# 1. SERVICES & SELECTORS UNIT TESTS
# ==============================================================================

@pytest.mark.django_db
class TestRoutineServices:

    def test_create_weekly_routine_template_success(self):
        ctx = setup_gym_and_routine_context()
        gym = ctx["gym"]

        days_data = [
            {
                "day_of_week": 1,
                "is_rest_day": False,
                "workout_title": "Chest & Triceps",
                "workday_note": "Focus on progressive overload.",
                "exercises": [
                    {"exercise_name": "Bench Press", "sets": 4, "reps_or_duration": "8-10 reps", "rest_seconds": 90},
                    {"exercise_name": "Incline Dumbbell Press", "sets": 3, "reps_or_duration": "10-12 reps", "rest_seconds": 60},
                ],
            },
            {
                "day_of_week": 2,
                "is_rest_day": True,
                "workout_title": "Rest Day",
                "workday_note": "Active recovery or stretching.",
                "exercises": [],
            },
        ]

        template = create_routine_template(
            gym=gym,
            template_name="Push Pull Legs - Weekly",
            routine_format=RoutineFormatEnum.WEEKLY,
            level=RoutineLevelEnum.INTERMEDIATE,
            notes="Standard 6-week split.",
            goals=[FitnessGoalEnum.MUSCLE_GAIN, FitnessGoalEnum.STRENGTH],
            days=days_data,
            created_by_staff_id=ctx["staff_assignment"].id,
        )

        assert template.template_name == "Push Pull Legs - Weekly"
        assert template.routine_format == RoutineFormatEnum.WEEKLY
        assert template.level == RoutineLevelEnum.INTERMEDIATE
        assert template.goals.count() == 2
        assert template.days.count() == 2

        # Check day 1
        day1 = template.days.get(day_of_week=1)
        assert day1.is_rest_day is False
        assert day1.exercises.count() == 2

        # Check day 2 (rest day)
        day2 = template.days.get(day_of_week=2)
        assert day2.is_rest_day is True
        assert day2.exercises.count() == 0

    def test_create_session_based_routine_template_success(self):
        ctx = setup_gym_and_routine_context()
        gym = ctx["gym"]

        sessions_data = [
            {
                "session_number": 1,
                "workout_title": "Session A: Full Body Heavy",
                "exercises": [
                    {"exercise_name": "Barbell Squats", "sets": 5, "reps_or_duration": "5 reps", "rest_seconds": 120},
                    {"exercise_name": "Treadmill Warmup", "sets": None, "reps_or_duration": "10 min", "rest_seconds": None},
                ],
            },
            {
                "session_number": 2,
                "workout_title": "Session B: Conditioning",
                "exercises": [
                    {"exercise_name": "Rowing Machine", "sets": None, "reps_or_duration": "20 min", "rest_seconds": 60},
                ],
            },
        ]

        template = create_routine_template(
            gym=gym,
            template_name="Session Split Routine",
            routine_format=RoutineFormatEnum.SESSION_BASED,
            level=RoutineLevelEnum.BEGINNER,
            days=sessions_data,
        )

        assert template.routine_format == RoutineFormatEnum.SESSION_BASED
        assert template.days.count() == 2
        # Ensure is_rest_day is False for sessions
        for d in template.days.all():
            assert d.is_rest_day is False

    def test_create_template_rest_day_with_exercises_fails(self):
        ctx = setup_gym_and_routine_context()
        gym = ctx["gym"]

        days_data = [
            {
                "day_of_week": 1,
                "is_rest_day": True,
                "exercises": [
                    {"exercise_name": "Deadlift", "sets": 3, "reps_or_duration": "5 reps"},
                ],
            }
        ]
        with pytest.raises(DomainValidationError) as exc:
            create_routine_template(
                gym=gym,
                template_name="Invalid Rest Day Split",
                routine_format=RoutineFormatEnum.WEEKLY,
                days=days_data,
            )
        assert "cannot contain exercises" in str(exc.value)

    def test_create_template_duplicate_day_of_week_fails(self):
        ctx = setup_gym_and_routine_context()
        days_data = [
            {"day_of_week": 1, "is_rest_day": True},
            {"day_of_week": 1, "is_rest_day": True},
        ]
        with pytest.raises(DomainValidationError) as exc:
            create_routine_template(
                gym=ctx["gym"],
                template_name="Duplicate Day Split",
                routine_format=RoutineFormatEnum.WEEKLY,
                days=days_data,
            )
        assert "Duplicate day_of_week" in str(exc.value)

    def test_update_routine_template_success(self):
        ctx = setup_gym_and_routine_context()
        template = create_routine_template(
            gym=ctx["gym"],
            template_name="Initial Name",
            level=RoutineLevelEnum.BEGINNER,
        )

        updated = update_routine_template(
            template=template,
            template_name="Updated Name",
            level=RoutineLevelEnum.ADVANCED,
            goals=[FitnessGoalEnum.STRENGTH],
            days=[
                {"day_of_week": 3, "workout_title": "Wednesday Workout", "is_rest_day": False, "exercises": [
                    {"exercise_name": "Overhead Press", "sets": 3, "reps_or_duration": "8 reps"}
                ]}
            ],
        )

        assert updated.template_name == "Updated Name"
        assert updated.level == RoutineLevelEnum.ADVANCED
        assert updated.goals.count() == 1
        assert updated.days.count() == 1
        assert updated.days.first().exercises.first().exercise_name == "Overhead Press"

    def test_delete_routine_template_restrictions(self):
        ctx = setup_gym_and_routine_context()
        gym = ctx["gym"]
        member = ctx["member"]

        template = create_routine_template(gym=gym, template_name="ToDelete Template")

        # Assign to member
        member_routine = assign_routine_to_member(
            gym=gym,
            member=member,
            source_template_id=template.id,
        )
        assert member_routine.is_active is True

        # Attempt to delete template while actively prescribed -> Conflict
        with pytest.raises(ResourceConflictError):
            delete_routine_template(template)

        # Deactivate member routine
        member_routine.is_active = False
        member_routine.save()

        # Now deletion succeeds
        delete_routine_template(template)
        assert not RoutineTemplate.objects.filter(id=template.id).exists()

    def test_assign_routine_from_template_deep_clones_structure(self):
        ctx = setup_gym_and_routine_context()
        gym = ctx["gym"]
        member = ctx["member"]

        template = create_routine_template(
            gym=gym,
            template_name="Master Blueprint",
            routine_format=RoutineFormatEnum.WEEKLY,
            level=RoutineLevelEnum.INTERMEDIATE,
            days=[
                {
                    "day_of_week": 1,
                    "workout_title": "Chest Blast",
                    "exercises": [
                        {"exercise_name": "Bench Press", "sets": 4, "reps_or_duration": "10 reps"},
                    ],
                }
            ],
        )

        # Assign to member
        routine = assign_routine_to_member(
            gym=gym,
            member=member,
            source_template_id=template.id,
            prescribed_by_staff_id=ctx["staff_assignment"].id,
        )

        assert routine.member_id == member.id
        assert routine.source_template_id == template.id
        assert routine.is_active is True
        assert routine.days.count() == 1
        assert routine.days.first().exercises.count() == 1
        assert routine.days.first().exercises.first().exercise_name == "Bench Press"

        # Modifying member routine exercises does not alter master template
        mr_ex = routine.days.first().exercises.first()
        mr_ex.sets = 10
        mr_ex.save()

        template_ex = template.days.first().exercises.first()
        assert template_ex.sets == 4

    def test_assign_routine_deactivates_previous_active_routines(self):
        ctx = setup_gym_and_routine_context()
        gym = ctx["gym"]
        member = ctx["member"]

        r1 = assign_routine_to_member(
            gym=gym,
            member=member,
            routine_name="Routine 1",
            routine_format=RoutineFormatEnum.WEEKLY,
            level=RoutineLevelEnum.BEGINNER,
        )
        assert r1.is_active is True

        r2 = assign_routine_to_member(
            gym=gym,
            member=member,
            routine_name="Routine 2",
            routine_format=RoutineFormatEnum.WEEKLY,
            level=RoutineLevelEnum.INTERMEDIATE,
        )
        assert r2.is_active is True

        r1.refresh_from_db()
        assert r1.is_active is False

    def test_customize_member_routine(self):
        ctx = setup_gym_and_routine_context()
        gym = ctx["gym"]
        member = ctx["member"]

        routine = assign_routine_to_member(
            gym=gym,
            member=member,
            routine_name="Initial Custom",
            routine_format=RoutineFormatEnum.WEEKLY,
            level=RoutineLevelEnum.BEGINNER,
        )

        updated = customize_member_routine(
            member_routine=routine,
            routine_name="Tailored for Athlete",
            level=RoutineLevelEnum.ADVANCED,
            days=[
                {
                    "day_of_week": 4,
                    "workout_title": "Power Day",
                    "exercises": [
                        {"exercise_name": "Power Clean", "sets": 5, "reps_or_duration": "3 reps"},
                    ],
                }
            ],
        )

        assert updated.routine_name == "Tailored for Athlete"
        assert updated.level == RoutineLevelEnum.ADVANCED
        assert updated.days.count() == 1
        assert updated.days.first().exercises.first().exercise_name == "Power Clean"


# ==============================================================================
# 2. REST API CONTRACT & WORKFLOW TESTS
# ==============================================================================

@pytest.mark.django_db
class TestRoutineAPIEndpoints:

    def test_list_routine_templates_api(self):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        create_routine_template(
            gym=ctx["gym"],
            template_name="Template A",
            routine_format=RoutineFormatEnum.WEEKLY,
            level=RoutineLevelEnum.BEGINNER,
        )
        create_routine_template(
            gym=ctx["gym"],
            template_name="Template B",
            routine_format=RoutineFormatEnum.SESSION_BASED,
            level=RoutineLevelEnum.ADVANCED,
        )

        # Unfiltered list
        resp = client.get("/api/v1/routine-templates/")
        assert resp.status_code == status.HTTP_200_OK
        results = resp.data["results"] if "results" in resp.data else resp.data
        assert len(results) >= 2

        # Filter by format
        resp_fmt = client.get("/api/v1/routine-templates/?routine_format=session_based")
        assert resp_fmt.status_code == status.HTTP_200_OK
        fmt_results = resp_fmt.data["results"] if "results" in resp_fmt.data else resp_fmt.data
        assert all(r["routine_format"] == "session_based" for r in fmt_results)

    def test_create_routine_template_api(self):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        payload = {
            "template_name": "Hypertrophy Program",
            "routine_format": "weekly",
            "level": "intermediate",
            "notes": "Follow for 8 weeks.",
            "goals": ["muscle_gain", "strength"],
            "days": [
                {
                    "day_of_week": 1,
                    "workout_title": "Leg Day",
                    "is_rest_day": False,
                    "exercises": [
                        {"exercise_name": "Barbell Squats", "sets": 4, "reps_or_duration": "8-10 reps", "rest_seconds": 90},
                    ],
                },
                {
                    "day_of_week": 2,
                    "is_rest_day": True,
                    "workout_title": "Rest",
                },
            ],
        }

        resp = client.post("/api/v1/routine-templates/", payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["template_name"] == "Hypertrophy Program"
        assert len(resp.data["days"]) == 2
        assert "id" in resp.data

    def test_get_routine_template_detail_api(self):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        template = create_routine_template(
            gym=ctx["gym"],
            template_name="Detail Template",
            days=[{"day_of_week": 1, "is_rest_day": True}],
        )

        resp = client.get(f"/api/v1/routine-templates/{template.id}/")
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["template_name"] == "Detail Template"
        assert len(resp.data["days"]) == 1

    def test_update_and_delete_routine_template_api(self):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        template = create_routine_template(gym=ctx["gym"], template_name="Initial API Template")

        # PATCH update
        resp_patch = client.patch(
            f"/api/v1/routine-templates/{template.id}/",
            {"template_name": "Patched API Template", "level": "advanced"},
            format="json",
        )
        assert resp_patch.status_code == status.HTTP_200_OK
        assert resp_patch.data["template_name"] == "Patched API Template"

        # DELETE
        resp_del = client.delete(f"/api/v1/routine-templates/{template.id}/")
        assert resp_del.status_code == status.HTTP_200_OK
        assert not RoutineTemplate.objects.filter(id=template.id).exists()

    def test_member_routine_prescription_workflow_api(self):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]
        member = ctx["member"]

        template = create_routine_template(
            gym=ctx["gym"],
            template_name="Prescription Template",
            days=[
                {
                    "day_of_week": 1,
                    "workout_title": "Upper Body",
                    "exercises": [{"exercise_name": "Pullups", "sets": 3, "reps_or_duration": "10 reps"}],
                }
            ],
        )

        # 1. Assign template to member
        assign_payload = {"source_template_id": str(template.id)}
        resp_assign = client.post(f"/api/v1/members/{member.id}/routines/assign/", assign_payload, format="json")
        assert resp_assign.status_code == status.HTTP_201_CREATED
        routine_id = resp_assign.data["id"]
        assert resp_assign.data["is_active"] is True
        assert len(resp_assign.data["days"]) == 1

        # 2. List member routines
        resp_list = client.get(f"/api/v1/members/{member.id}/routines/")
        assert resp_list.status_code == status.HTTP_200_OK
        assert len(resp_list.data) >= 1

        # 3. Get routine detail
        resp_detail = client.get(f"/api/v1/members/{member.id}/routines/{routine_id}/")
        assert resp_detail.status_code == status.HTTP_200_OK
        assert resp_detail.data["id"] == routine_id

        # 4. Customize member routine
        customize_payload = {
            "routine_name": "Personalized Routine for Member",
            "days": [
                {
                    "day_of_week": 1,
                    "workout_title": "Custom Upper Body",
                    "exercises": [{"exercise_name": "Weighted Pullups", "sets": 4, "reps_or_duration": "6 reps"}],
                }
            ],
        }
        resp_custom = client.patch(f"/api/v1/members/{member.id}/routines/{routine_id}/", customize_payload, format="json")
        assert resp_custom.status_code == status.HTTP_200_OK
        assert resp_custom.data["routine_name"] == "Personalized Routine for Member"
        assert resp_custom.data["days"][0]["exercises"][0]["exercise_name"] == "Weighted Pullups"


# ==============================================================================
# 3. TYPE JUGGLING & DATA TYPE MISMATCH TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase6TypeJugglingAndMismatches:

    @pytest.mark.parametrize("bad_name", [
        12345,
        True,
        ["Invalid", "Array"],
        {"template_name": "nested"},
    ])
    def test_template_name_type_mismatch_rejected(self, bad_name):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        payload = {"template_name": bad_name}
        resp = client.post("/api/v1/routine-templates/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_goals", [
        "muscle_gain",  # string instead of array
        12345,
        True,
        {"goal": "muscle_gain"},
    ])
    def test_goals_non_array_type_mismatch_rejected(self, bad_goals):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        payload = {
            "template_name": "TypeTest",
            "goals": bad_goals,
        }
        resp = client.post("/api/v1/routine-templates/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_days", [
        "day1",
        123,
        True,
        {"day": 1},
    ])
    def test_days_non_array_type_mismatch_rejected(self, bad_days):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        payload = {
            "template_name": "TypeTestDays",
            "days": bad_days,
        }
        resp = client.post("/api/v1/routine-templates/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_sets", [
        "not_an_int",
        [3],
        {"sets": 3},
    ])
    def test_exercise_sets_type_mismatch_rejected(self, bad_sets):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        payload = {
            "template_name": "BadSetsSplit",
            "days": [
                {
                    "day_of_week": 1,
                    "exercises": [{"exercise_name": "Squat", "sets": bad_sets, "reps_or_duration": "10 reps"}],
                }
            ],
        }
        resp = client.post("/api/v1/routine-templates/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 4. BOUNDARY & EXTREME LENGTH VALUES TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase6BoundaryAndExtremeLengths:

    def test_template_name_boundary_lengths(self):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        # 255 chars (valid boundary)
        valid_name = "T" * 255
        resp_valid = client.post("/api/v1/routine-templates/", {"template_name": valid_name}, format="json")
        assert resp_valid.status_code == status.HTTP_201_CREATED

        # 256 chars (exceeds max_length)
        resp_over = client.post("/api/v1/routine-templates/", {"template_name": "T" * 256}, format="json")
        assert resp_over.status_code == status.HTTP_400_BAD_REQUEST

        # 10,000 chars (extreme length)
        resp_extreme = client.post("/api/v1/routine-templates/", {"template_name": "T" * 10000}, format="json")
        assert resp_extreme.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("blank_name", ["", "   ", "\t\t\n"])
    def test_whitespace_and_blank_template_names_rejected(self, blank_name):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        resp = client.post("/api/v1/routine-templates/", {"template_name": blank_name}, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_dow", [0, 8, -1, 100])
    def test_day_of_week_boundary_validation(self, invalid_dow):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        payload = {
            "template_name": "DayBoundarySplit",
            "routine_format": "weekly",
            "days": [{"day_of_week": invalid_dow, "is_rest_day": True}],
        }
        resp = client.post("/api/v1/routine-templates/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("invalid_sess", [0, -1, -50])
    def test_session_number_boundary_validation(self, invalid_sess):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        payload = {
            "template_name": "SessionBoundarySplit",
            "routine_format": "session_based",
            "days": [{"session_number": invalid_sess}],
        }
        resp = client.post("/api/v1/routine-templates/", payload, format="json")
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 5. MISSING, EXTRA & GARBAGE FIELDS TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase6MissingAndGarbageFields:

    def test_empty_json_payloads_rejected(self):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]
        member = ctx["member"]

        assert client.post("/api/v1/routine-templates/", {}, format="json").status_code == status.HTTP_400_BAD_REQUEST
        assert client.post(f"/api/v1/members/{member.id}/routines/assign/", {}, format="json").status_code == status.HTTP_400_BAD_REQUEST

    def test_garbage_fields_handled_gracefully(self):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        payload = {"template_name": "GarbageTolerant"}
        for i in range(100):
            payload[f"garbage_{i}"] = f"garbage_value_{i}"

        resp = client.post("/api/v1/routine-templates/", payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["template_name"] == "GarbageTolerant"

    def test_mass_assignment_protection_on_system_fields(self):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]
        template = create_routine_template(gym=ctx["gym"], template_name="MassAssign")

        fake_id = str(uuid.uuid4())
        fake_gym_id = str(uuid.uuid4())

        resp = client.patch(
            f"/api/v1/routine-templates/{template.id}/",
            {"id": fake_id, "gym_id": fake_gym_id, "template_name": "TamperedName"},
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK

        template.refresh_from_db()
        assert str(template.id) != fake_id
        assert str(template.gym_id) != fake_gym_id
        assert template.template_name == "TamperedName"


# ==============================================================================
# 6. SECURITY & ADVERSARIAL INJECTIONS
# ==============================================================================

@pytest.mark.django_db
class TestPhase6SecurityAndAdversarialInjections:

    @pytest.mark.parametrize("injection_string", [
        "'; DROP TABLE routine_templates; --",
        "' OR 1=1 --",
        "UNION SELECT NULL, NULL, NULL --",
        "\" OR \"a\"=\"a",
    ])
    def test_sql_injection_stored_literally_without_corruption(self, injection_string):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        resp = client.post("/api/v1/routine-templates/", {
            "template_name": injection_string,
            "notes": injection_string,
            "days": [
                {
                    "day_of_week": 1,
                    "workout_title": injection_string,
                    "exercises": [{"exercise_name": injection_string, "reps_or_duration": "10 reps"}],
                }
            ],
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        template_id = resp.data["id"]

        assert RoutineTemplate.objects.filter(id=template_id).exists()
        t = RoutineTemplate.objects.get(id=template_id)
        assert t.template_name == injection_string

    @pytest.mark.parametrize("xss_payload", [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(document.cookie)>",
        "<iframe src=\"javascript:alert('pwned')\"></iframe>",
    ])
    def test_stored_xss_persisted_safely_as_plain_strings(self, xss_payload):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        resp = client.post("/api/v1/routine-templates/", {
            "template_name": xss_payload,
            "notes": xss_payload,
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["template_name"] == xss_payload

    @pytest.mark.parametrize("unicode_string", [
        "تمرين الصدر والذراعين",  # Arabic
        "אימון גוף מלא למתחילים",  # Hebrew
        "初学者全身力量训练计划",    # Chinese
        "🏋️‍♂️ Bench Press & Squat Power Split 🔥💪💯",  # Emojis
    ])
    def test_unicode_and_multilingual_data_integrity(self, unicode_string):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]

        resp = client.post("/api/v1/routine-templates/", {
            "template_name": unicode_string,
            "notes": unicode_string,
        }, format="json")
        assert resp.status_code == status.HTTP_201_CREATED
        assert resp.data["template_name"] == unicode_string


# ==============================================================================
# 7. AUTHENTICATION & RBAC PERMISSIONS TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase6RBACAndAuthentication:

    def test_anonymous_requests_blocked_with_401(self):
        anon_client = APIClient()
        fake_uuid = uuid.uuid4()

        endpoints = [
            ("get", "/api/v1/routine-templates/"),
            ("post", "/api/v1/routine-templates/"),
            ("get", f"/api/v1/routine-templates/{fake_uuid}/"),
            ("put", f"/api/v1/routine-templates/{fake_uuid}/"),
            ("patch", f"/api/v1/routine-templates/{fake_uuid}/"),
            ("delete", f"/api/v1/routine-templates/{fake_uuid}/"),
            ("get", f"/api/v1/members/{fake_uuid}/routines/"),
            ("post", f"/api/v1/members/{fake_uuid}/routines/assign/"),
            ("get", f"/api/v1/members/{fake_uuid}/routines/{fake_uuid}/"),
            ("patch", f"/api/v1/members/{fake_uuid}/routines/{fake_uuid}/"),
        ]

        for method, url in endpoints:
            resp = getattr(anon_client, method)(url, {}, format="json")
            assert resp.status_code == status.HTTP_401_UNAUTHORIZED, f"Failed for {method.upper()} {url}"

    def test_read_only_staff_blocked_from_routine_mutations(self):
        ctx = setup_gym_and_routine_context()
        template = create_routine_template(gym=ctx["gym"], template_name="StaffTestTemplate")
        member = ctx["member"]

        # Staff with ONLY 'routines:read'
        _, read_client, _ = create_staff_with_scopes(ctx["gym"], scopes=["routines:read"])

        # Reads succeed
        assert read_client.get("/api/v1/routine-templates/").status_code == status.HTTP_200_OK
        assert read_client.get(f"/api/v1/routine-templates/{template.id}/").status_code == status.HTTP_200_OK
        assert read_client.get(f"/api/v1/members/{member.id}/routines/").status_code == status.HTTP_200_OK

        # Mutations FAIL with 403 Forbidden
        assert read_client.post("/api/v1/routine-templates/", {"template_name": "Forbidden"}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert read_client.patch(f"/api/v1/routine-templates/{template.id}/", {"template_name": "Forbidden"}, format="json").status_code == status.HTTP_403_FORBIDDEN
        assert read_client.delete(f"/api/v1/routine-templates/{template.id}/").status_code == status.HTTP_403_FORBIDDEN
        assert read_client.post(f"/api/v1/members/{member.id}/routines/assign/", {"source_template_id": str(template.id)}, format="json").status_code == status.HTTP_403_FORBIDDEN


# ==============================================================================
# 8. IDOR & MULTI-TENANT ISOLATION TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase6CrossTenantIDORIsolation:

    def test_complete_cross_tenant_isolation(self):
        ctx1 = setup_gym_and_routine_context("gym1.owner@manygym.com")
        template1 = create_routine_template(gym=ctx1["gym"], template_name="Gym1Template")
        member1 = ctx1["member"]
        routine1 = assign_routine_to_member(gym=ctx1["gym"], member=member1, source_template_id=template1.id)

        ctx2 = setup_gym_and_routine_context("gym2.owner@manygym.com")
        client2 = ctx2["client"]

        # Gym 2 tries to access Gym 1's template -> 404
        assert client2.get(f"/api/v1/routine-templates/{template1.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert client2.patch(f"/api/v1/routine-templates/{template1.id}/", {"template_name": "Hacked"}, format="json").status_code == status.HTTP_404_NOT_FOUND
        assert client2.delete(f"/api/v1/routine-templates/{template1.id}/").status_code == status.HTTP_404_NOT_FOUND

        # Gym 2 tries to access or assign Gym 1's member routines -> 404
        assert client2.get(f"/api/v1/members/{member1.id}/routines/").status_code == status.HTTP_404_NOT_FOUND
        assert client2.post(f"/api/v1/members/{member1.id}/routines/assign/", {}, format="json").status_code == status.HTTP_404_NOT_FOUND
        assert client2.get(f"/api/v1/members/{member1.id}/routines/{routine1.id}/").status_code == status.HTTP_404_NOT_FOUND
        assert client2.patch(f"/api/v1/members/{member1.id}/routines/{routine1.id}/", {}, format="json").status_code == status.HTTP_404_NOT_FOUND

    def test_cross_tenant_template_tampering_in_prescription_fails(self):
        ctx1 = setup_gym_and_routine_context("gym1.tamper@manygym.com")
        ctx2 = setup_gym_and_routine_context("gym2.tamper@manygym.com")

        template2 = create_routine_template(gym=ctx2["gym"], template_name="Gym2SecretTemplate")
        member1 = ctx1["member"]

        # Gym 1 attempts to prescribe Gym 2's template to Gym 1's member -> 400 Bad Request
        resp = ctx1["client"].post(
            f"/api/v1/members/{member1.id}/routines/assign/",
            {"source_template_id": str(template2.id)},
            format="json",
        )
        assert resp.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 9. HTTP METHOD NOT ALLOWED (405) TESTS
# ==============================================================================

@pytest.mark.django_db
class TestPhase6HTTPMethodNotAllowed:

    def test_disallowed_http_methods(self):
        ctx = setup_gym_and_routine_context()
        client = ctx["client"]
        template = create_routine_template(gym=ctx["gym"], template_name="MethodTemplate")
        member = ctx["member"]

        disallowed_routes = [
            ("put", "/api/v1/routine-templates/"),
            ("delete", "/api/v1/routine-templates/"),
            ("post", f"/api/v1/routine-templates/{template.id}/"),
            ("put", f"/api/v1/members/{member.id}/routines/"),
            ("delete", f"/api/v1/members/{member.id}/routines/"),
            ("get", f"/api/v1/members/{member.id}/routines/assign/"),
            ("put", f"/api/v1/members/{member.id}/routines/assign/"),
            ("delete", f"/api/v1/members/{member.id}/routines/assign/"),
            ("post", f"/api/v1/members/{member.id}/routines/{template.id}/"),
            ("delete", f"/api/v1/members/{member.id}/routines/{template.id}/"),
        ]

        for method, url in disallowed_routes:
            resp = getattr(client, method)(url, {}, format="json")
            assert resp.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, f"Expected 405 for {method.upper()} {url}, got {resp.status_code}"
