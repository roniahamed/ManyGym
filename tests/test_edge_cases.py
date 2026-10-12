import uuid
from datetime import timedelta
import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.utils import timezone

from apps.users.models import User, OTPVerification
from apps.gyms.models import Gym
from apps.access_control.models import Role, Permission, GymStaffAssignment
from apps.access_control.services import seed_default_permissions_and_roles
from apps.authentication.models import AuthToken
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, UserStatus, StaffStatus


@pytest.fixture(autouse=True)
def setup_default_seeds(db):
    seed_default_permissions_and_roles()


# =====================================================================
# 1. REGISTRATION VALIDATION EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_registration_validation_edge_cases():
    client = APIClient()
    url = reverse("register")

    # Edge Case: Password shorter than 8 characters
    res = client.post(url, {
        "email": "short.pass@manygym.com",
        "password": "123",
        "first_name": "Short",
        "last_name": "Pass",
    })
    assert res.status_code == 400
    assert "password" in res.data["details"]

    # Edge Case: Invalid email format
    res = client.post(url, {
        "email": "not-an-email",
        "password": "ValidPassword123!",
        "first_name": "Invalid",
        "last_name": "Email",
    })
    assert res.status_code == 400
    assert "email" in res.data["details"]

    # Edge Case: Missing required first_name and last_name
    res = client.post(url, {
        "email": "missing.fields@manygym.com",
        "password": "ValidPassword123!",
    })
    assert res.status_code == 400
    assert "first_name" in res.data["details"]
    assert "last_name" in res.data["details"]

    # Register initial user
    client.post(url, {
        "email": "case.test@manygym.com",
        "password": "ValidPassword123!",
        "first_name": "Case",
        "last_name": "Test",
    })

    # Edge Case: Duplicate registration with UPPERCASE email
    dup_res = client.post(url, {
        "email": "CASE.TEST@MANYGYM.COM",
        "password": "AnotherPassword123!",
        "first_name": "Case",
        "last_name": "Test",
    })
    assert dup_res.status_code == 409
    assert dup_res.data["code"] == "RESOURCE_CONFLICT"


# =====================================================================
# 2. OTP VERIFICATION & LIFECYCLE EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_otp_lifecycle_and_invalidation_edge_cases():
    client = APIClient()

    # Create unverified user
    user = User.objects.create_user(
        email="otp.edge@manygym.com",
        password="ValidPassword123!",
        first_name="Otp",
        last_name="Edge",
        is_verified=False,
    )

    # Edge Case: Verify with non-existent email
    res = client.post(reverse("verify-signup-otp"), {
        "email": "nonexistent@manygym.com",
        "otp_code": "123456",
    })
    assert res.status_code == 404

    # Edge Case: Expired OTP
    past_time = timezone.now() - timedelta(minutes=1)
    expired_otp = OTPVerification.objects.create(
        email=user.email,
        otp_code="111111",
        purpose=OTPVerification.Purpose.SIGNUP_VERIFICATION,
        expires_at=past_time,
        is_used=False,
    )
    res = client.post(reverse("verify-signup-otp"), {
        "email": user.email,
        "otp_code": "111111",
    })
    assert res.status_code == 400
    assert "Invalid or expired" in res.data["message"]

    # Edge Case: Already used OTP
    used_otp = OTPVerification.objects.create(
        email=user.email,
        otp_code="222222",
        purpose=OTPVerification.Purpose.SIGNUP_VERIFICATION,
        expires_at=timezone.now() + timedelta(minutes=15),
        is_used=True,
    )
    res = client.post(reverse("verify-signup-otp"), {
        "email": user.email,
        "otp_code": "222222",
    })
    assert res.status_code == 400

    # Edge Case: Multiple OTPs - Older OTP is invalidated when resend is called
    client.post(reverse("resend-otp"), {"email": user.email})
    old_record = OTPVerification.objects.filter(email=user.email, is_used=False).first()
    old_code = old_record.otp_code

    # Resend again
    client.post(reverse("resend-otp"), {"email": user.email})
    new_record = OTPVerification.objects.filter(email=user.email, is_used=False).order_by("-created_at").first()
    new_code = new_record.otp_code
    assert old_code != new_code

    # Old code should now be marked as used or rejected
    res_old = client.post(reverse("verify-signup-otp"), {
        "email": user.email,
        "otp_code": old_code,
    })
    assert res_old.status_code == 400

    # New code succeeds
    res_new = client.post(reverse("verify-signup-otp"), {
        "email": user.email,
        "otp_code": new_code,
    })
    assert res_new.status_code == 200

    # Edge Case: Attempting to resend OTP after account is already verified
    res_resend_verified = client.post(reverse("resend-otp"), {"email": user.email})
    assert res_resend_verified.status_code == 400
    assert "already verified" in res_resend_verified.data["message"]

    # Edge Case: Resend OTP for non-existent email
    res_resend_404 = client.post(reverse("resend-otp"), {"email": "nobody@nowhere.com"})
    assert res_resend_404.status_code == 404


# =====================================================================
# 3. LOGIN & ACCOUNT STATUS EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_login_account_status_edge_cases():
    client = APIClient()

    # User 1: Inactive user
    User.objects.create_user(
        email="inactive.user@manygym.com",
        password="ValidPassword123!",
        first_name="Inactive",
        last_name="User",
        is_verified=True,
        status=UserStatus.INACTIVE,
    )
    res_inactive = client.post(reverse("login"), {
        "email": "inactive.user@manygym.com",
        "password": "ValidPassword123!",
    })
    assert res_inactive.status_code == 400
    assert "inactive or suspended" in res_inactive.data["message"]

    # User 2: Suspended user
    User.objects.create_user(
        email="suspended.user@manygym.com",
        password="ValidPassword123!",
        first_name="Suspended",
        last_name="User",
        is_verified=True,
        status=UserStatus.SUSPENDED,
    )
    res_suspended = client.post(reverse("login"), {
        "email": "suspended.user@manygym.com",
        "password": "ValidPassword123!",
    })
    assert res_suspended.status_code == 400
    assert "inactive or suspended" in res_suspended.data["message"]

    # User 3: Unverified user
    User.objects.create_user(
        email="unverified.user@manygym.com",
        password="ValidPassword123!",
        first_name="Unverified",
        last_name="User",
        is_verified=False,
    )
    res_unverified = client.post(reverse("login"), {
        "email": "unverified.user@manygym.com",
        "password": "ValidPassword123!",
    })
    assert res_unverified.status_code == 400
    assert "not been verified" in res_unverified.data["message"]

    # User 4: Non-existent email
    res_nonexistent = client.post(reverse("login"), {
        "email": "ghost@manygym.com",
        "password": "ValidPassword123!",
    })
    assert res_nonexistent.status_code == 400
    assert "Invalid email or password" in res_nonexistent.data["message"]

    # User 5: Case-insensitive login with valid credentials
    active_user = User.objects.create_user(
        email="normal.case@manygym.com",
        password="ValidPassword123!",
        first_name="Normal",
        last_name="User",
        is_verified=True,
    )
    res_case = client.post(reverse("login"), {
        "email": "NORMAL.CASE@MANYGYM.COM",
        "password": "ValidPassword123!",
    })
    assert res_case.status_code == 200
    assert res_case.data["user"]["email"] == "normal.case@manygym.com"


# =====================================================================
# 4. PASSWORD RESET EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_password_reset_edge_cases():
    client = APIClient()

    # Edge Case: Request password reset for non-existent email -> 200 generic message
    res_ghost = client.post(reverse("forgot-password"), {
        "email": "ghost.reset@manygym.com",
    })
    assert res_ghost.status_code == 200
    assert "If an account exists" in res_ghost.data["message"]

    # Setup valid user
    user = User.objects.create_user(
        email="reset.edge@manygym.com",
        password="OldPassword123!",
        first_name="Reset",
        last_name="Edge",
        is_verified=True,
    )
    client.post(reverse("forgot-password"), {"email": user.email})
    otp = OTPVerification.objects.filter(email=user.email, purpose=OTPVerification.Purpose.PASSWORD_RESET).first().otp_code

    # Edge Case: Reset with password < 8 characters
    short_res = client.post(reverse("reset-password"), {
        "email": user.email,
        "otp_code": otp,
        "new_password": "short",
    })
    assert short_res.status_code == 400

    # Successful reset
    valid_res = client.post(reverse("reset-password"), {
        "email": user.email,
        "otp_code": otp,
        "new_password": "NewSecretPassword2026!",
    })
    assert valid_res.status_code == 200

    # Edge Case: Re-using the same OTP a second time
    reuse_res = client.post(reverse("reset-password"), {
        "email": user.email,
        "otp_code": otp,
        "new_password": "AnotherNewPassword2026!",
    })
    assert reuse_res.status_code == 400


# =====================================================================
# 5. PROFILE & CHANGE PASSWORD EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_profile_and_change_password_edge_cases():
    client = APIClient()

    # Edge Case: Accessing /me/ without authentication -> 401
    res_no_auth = client.get(reverse("me"))
    assert res_no_auth.status_code == 401

    # Edge Case: Accessing /me/ with malformed token -> 401
    client.credentials(HTTP_AUTHORIZATION="Bearer garbage-invalid-token")
    res_bad_auth = client.get(reverse("me"))
    assert res_bad_auth.status_code == 401

    # Login valid user
    user = User.objects.create_user(
        email="profile.edge@manygym.com",
        password="OriginalPassword123!",
        first_name="Profile",
        last_name="Edge",
        is_verified=True,
    )
    tokens = issue_context_token(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

    # Edge Case: Change password with incorrect current password
    res_wrong_old = client.post(reverse("change-password"), {
        "current_password": "WrongPassword!",
        "new_password": "BrandNewPassword2026!",
    })
    assert res_wrong_old.status_code == 400
    assert "Current password does not match" in res_wrong_old.data["message"]

    # Edge Case: Change password with new password < 8 chars
    res_short_new = client.post(reverse("change-password"), {
        "current_password": "OriginalPassword123!",
        "new_password": "short",
    })
    assert res_short_new.status_code == 400


# =====================================================================
# 6. CONTEXT SWITCHING & MULTI-GYM ISOLATION EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_context_switching_and_isolation_edge_cases():
    client = APIClient()

    owner = User.objects.create_user(
        email="gym1.owner@manygym.com",
        password="Password123!",
        first_name="Gym1",
        last_name="Owner",
        is_verified=True,
    )
    gym1 = Gym.objects.create(owner_user=owner, name="Powerhouse Gym")
    gym2 = Gym.objects.create(owner_user=owner, name="Gold Fitness")

    staff = User.objects.create_user(
        email="staff.gym1@manygym.com",
        password="Password123!",
        first_name="Staff",
        last_name="One",
        is_verified=True,
    )
    trainer_role = Role.objects.get(slug="trainer")
    # Staff in Gym1, but NOT in Gym2
    assignment = GymStaffAssignment.objects.create(
        user=staff,
        gym=gym1,
        role=trainer_role,
        status=StaffStatus.ACTIVE,
    )

    staff_tokens = issue_context_token(staff)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {staff_tokens['access']}")

    # Edge Case: Switching to gym context without gym_id
    res_missing_gid = client.post(reverse("switch-context"), {
        "context_type": "gym",
    })
    assert res_missing_gid.status_code == 400
    assert "gym_id" in res_missing_gid.data["details"]

    # Edge Case: Switching to non-existent gym UUID
    res_random_gid = client.post(reverse("switch-context"), {
        "context_type": "gym",
        "gym_id": str(uuid.uuid4()),
    })
    assert res_random_gid.status_code == 404

    # Edge Case: Staff attempts to switch context to Gym2 (where they have no assignment)
    res_unauth_gym2 = client.post(reverse("switch-context"), {
        "context_type": "gym",
        "gym_id": str(gym2.id),
    })
    assert res_unauth_gym2.status_code == 401
    assert res_unauth_gym2.data["code"] == "UNAUTHORIZED_CONTEXT"

    # Edge Case: Staff assignment is deactivated (inactive) -> switch context rejected
    assignment.status = StaffStatus.INACTIVE
    assignment.save()

    res_inactive_staff = client.post(reverse("switch-context"), {
        "context_type": "gym",
        "gym_id": str(gym1.id),
    })
    assert res_inactive_staff.status_code == 401

    # Reactivate assignment -> switch context succeeds
    assignment.status = StaffStatus.ACTIVE
    assignment.save()

    res_active_staff = client.post(reverse("switch-context"), {
        "context_type": "gym",
        "gym_id": str(gym1.id),
    })
    assert res_active_staff.status_code == 200
    assert res_active_staff.data["tokens"]["context_type"] == "gym"


# =====================================================================
# 7. CUSTOM ROLE & RBAC RESTRICTION EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_custom_role_modification_and_deletion_edge_cases():
    client = APIClient()

    owner = User.objects.create_user(
        email="role.owner@manygym.com",
        password="Password123!",
        first_name="Role",
        last_name="Owner",
        is_verified=True,
    )
    gym = Gym.objects.create(owner_user=owner, name="CrossFit Hub")

    owner_tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {owner_tokens['access']}")

    # Edge Case: Attempt to edit a global system standard role (Administrator)
    admin_role = Role.objects.get(slug="administrator")
    res_edit_admin = client.patch(reverse("role-detail", kwargs={"role_id": str(admin_role.id)}), {
        "name": "Modified Admin Name",
    })
    assert res_edit_admin.status_code == 400
    assert "cannot be modified" in res_edit_admin.data["message"]

    # Edge Case: Attempt to delete a global system standard role
    res_del_admin = client.delete(reverse("role-detail", kwargs={"role_id": str(admin_role.id)}))
    assert res_del_admin.status_code == 400
    assert "cannot be deleted" in res_del_admin.data["message"]

    # Create a custom role
    create_res = client.post(reverse("roles-list-create"), {
        "name": "Weekend Supervisor",
        "description": "Custom supervisor role",
    })
    assert create_res.status_code == 201
    custom_role_id = create_res.data["id"]

    # Edge Case: Attempt to create role with duplicate name in the same gym -> 409 Conflict
    dup_role_res = client.post(reverse("roles-list-create"), {
        "name": "Weekend Supervisor",
    })
    assert dup_role_res.status_code == 409
    assert dup_role_res.data["code"] == "RESOURCE_CONFLICT"

    # Assign this custom role to a staff member
    staff = User.objects.create_user(
        email="weekend.staff@manygym.com",
        password="Password123!",
        first_name="Weekend",
        last_name="Staff",
        is_verified=True,
    )
    custom_role = Role.objects.get(id=custom_role_id)
    GymStaffAssignment.objects.create(
        user=staff,
        gym=gym,
        role=custom_role,
        status=StaffStatus.ACTIVE,
    )

    # Edge Case: Attempt to delete custom role while assigned to active staff -> 400
    res_del_assigned = client.delete(reverse("role-detail", kwargs={"role_id": custom_role_id}))
    assert res_del_assigned.status_code == 400
    assert "currently assigned to gym staff" in res_del_assigned.data["message"]


# =====================================================================
# 8. STAFF ASSIGNMENT & PERMISSION RESTRICTION EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_staff_assignment_edge_cases():
    client = APIClient()

    owner = User.objects.create_user(
        email="staff.mgr@manygym.com",
        password="Password123!",
        first_name="Staff",
        last_name="Manager",
        is_verified=True,
    )
    gym = Gym.objects.create(owner_user=owner, name="Elite Gym")
    other_gym = Gym.objects.create(owner_user=owner, name="Other Gym")

    owner_tokens = issue_context_token(owner, context_type=TokenContextType.GYM, gym=gym)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {owner_tokens['access']}")

    # Edge Case: Invite non-existent user email -> 404
    res_invite_ghost = client.post(reverse("staff-list-invite"), {
        "email": "notregistered@anywhere.com",
        "role_id": str(Role.objects.get(slug="trainer").id),
    })
    assert res_invite_ghost.status_code == 404
    assert "No registered user found" in res_invite_ghost.data["message"]

    # Edge Case: Invite with non-existent role_id -> 404
    valid_user = User.objects.create_user(
        email="candidate@manygym.com",
        password="Password123!",
        first_name="Candidate",
        last_name="One",
        is_verified=True,
    )
    res_invite_bad_role = client.post(reverse("staff-list-invite"), {
        "email": valid_user.email,
        "role_id": str(uuid.uuid4()),
    })
    assert res_invite_bad_role.status_code == 404

    # Edge Case: Invite with custom role belonging to a DIFFERENT gym -> 400
    other_role = Role.objects.create(gym=other_gym, name="Other Custom", slug="other-custom", is_custom=True)
    res_foreign_role = client.post(reverse("staff-list-invite"), {
        "email": valid_user.email,
        "role_id": str(other_role.id),
    })
    assert res_foreign_role.status_code == 400
    assert "does not belong to this gym" in res_foreign_role.data["message"]

    # Valid Invite
    invite_res = client.post(reverse("staff-list-invite"), {
        "email": valid_user.email,
        "role_id": str(Role.objects.get(slug="trainer").id),
    })
    assert invite_res.status_code == 201
    assignment_id = invite_res.data["id"]

    # Edge Case: Update status with invalid value -> 400
    bad_status_res = client.patch(reverse("staff-detail", kwargs={"assignment_id": assignment_id}), {
        "status": "banned_fake_status",
    })
    assert bad_status_res.status_code == 400

    # Valid Status Update to inactive
    deactivate_res = client.patch(reverse("staff-detail", kwargs={"assignment_id": assignment_id}), {
        "status": "inactive",
    })
    assert deactivate_res.status_code == 200
    assert deactivate_res.data["status"] == "inactive"

    # Revoke access -> 200
    delete_res = client.delete(reverse("staff-detail", kwargs={"assignment_id": assignment_id}))
    assert delete_res.status_code == 200
    assert not GymStaffAssignment.objects.filter(id=assignment_id).exists()


# =====================================================================
# 9. TOKEN REVOCATION / LOGOUT EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_logout_and_revocation_edge_cases():
    client = APIClient()

    user = User.objects.create_user(
        email="logout.user@manygym.com",
        password="Password123!",
        first_name="Logout",
        last_name="Tester",
        is_verified=True,
    )
    tokens = issue_context_token(user)
    access_token = tokens["access"]

    # Verify token exists in AuthToken table
    assert AuthToken.objects.filter(user=user).exists()

    # Edge Case: Logout without token -> 401
    res_no_auth = client.post(reverse("logout"))
    assert res_no_auth.status_code == 401

    # Logout with token -> 200 and revokes token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    res_logout = client.post(reverse("logout"))
    assert res_logout.status_code == 200
    assert res_logout.data["message"] == "Logged out successfully."

    # AuthToken record should be deleted
    assert not AuthToken.objects.filter(user=user).exists()
