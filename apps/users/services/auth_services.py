import secrets
from datetime import timedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.users.models import User, UserProfile, OTPVerification
from apps.users.tasks import send_email_task
from common.security import hash_otp
from common.exceptions import (
    DomainValidationError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from common.enums import UserStatus


def generate_numeric_otp(length=6) -> str:
    """Generate a cryptographically secure random 6-digit OTP code."""
    return "".join(secrets.choice("0123456789") for _ in range(length))


@transaction.atomic
def register_user(email: str, password: str, first_name: str, last_name: str, phone: str = None) -> User:
    """
    Registers a new user, creates empty UserProfile, and sends an email OTP verification code.
    """
    email_clean = email.lower().strip()
    existing_user = User.objects.filter(email=email_clean).first()
    if existing_user:
        if existing_user.is_verified:
            raise ResourceConflictError("This account is already registered and verified. Please proceed to login.")
        raise ResourceConflictError("An account with this email already exists but is unverified. Please verify your OTP or request a new code.")

    user = User.objects.create_user(
        email=email_clean,
        password=password,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        phone=phone.strip() if phone else None,
        is_verified=False,
        status=UserStatus.ACTIVE,
    )

    profile = UserProfile.objects.create(user=user)
    user.profile = profile

    # Invalidate any prior unused OTPs for this email
    OTPVerification.objects.filter(
        email=email_clean,
        purpose=OTPVerification.Purpose.SIGNUP_VERIFICATION,
        is_used=False,
    ).update(is_used=True)

    # Generate OTP (valid for 15 minutes)
    otp_code = generate_numeric_otp()
    expires_at = timezone.now() + timedelta(minutes=15)
    OTPVerification.objects.create(
        email=email_clean,
        otp_code=otp_code,
        purpose=OTPVerification.Purpose.SIGNUP_VERIFICATION,
        expires_at=expires_at,
    )

    # Trigger async email
    subject = "Many Gym - Verify Your Account"
    message = (
        f"Hello {user.first_name},\n\n"
        f"Thank you for registering at Many Gym.\n"
        f"Your verification code is: {otp_code}\n"
        f"This code will expire in 15 minutes.\n\n"
        f"Regards,\nMany Gym Team"
    )
    html_message = (
        f"<h3>Hello {user.first_name},</h3>"
        f"<p>Thank you for registering at <strong>Many Gym</strong>.</p>"
        f"<p>Your verification code is: <strong style='font-size:24px;color:#2563eb;'>{otp_code}</strong></p>"
        f"<p>This code will expire in 15 minutes.</p>"
        f"<br><p>Best regards,<br>The Many Gym Team</p>"
    )
    transaction.on_commit(lambda: send_email_task.delay(subject, [email_clean], message, html_message))

    return user


def verify_signup_otp(email: str, otp_code: str) -> User:
    """
    Validates signup OTP and activates account verification status.
    Enforces maximum 5 attempts per OTP code to prevent brute-forcing.
    """
    email_clean = email.lower().strip()
    try:
        user = User.objects.select_related("profile").get(email=email_clean)
    except User.DoesNotExist:
        raise ResourceNotFoundError("User with this email was not found.")

    if user.is_verified:
        raise DomainValidationError("This account is already verified. Please proceed to login.")

    otp_record = (
        OTPVerification.objects.filter(
            email=email_clean,
            purpose=OTPVerification.Purpose.SIGNUP_VERIFICATION,
            is_used=False,
        )
        .order_by("-created_at")
        .first()
    )

    from django.core.cache import cache
    if not otp_record or not otp_record.is_valid() or (otp_record and cache.get(f"otp_burned:{otp_record.id}")):
        raise DomainValidationError("Invalid or expired verification OTP.")

    cache_key = f"otp_failed:{otp_record.id}"
    failed_attempts = cache.get(cache_key, 0)
    if failed_attempts >= 5 or cache.get(f"otp_burned:{otp_record.id}"):
        OTPVerification.objects.filter(id=otp_record.id).update(is_used=True)
        cache.set(f"otp_burned:{otp_record.id}", True, timeout=900)
        raise DomainValidationError("Too many failed attempts. This verification code has been invalidated. Please request a new code.")

    hashed_otp = hash_otp(email_clean, otp_code.strip())
    is_valid_otp = (
        otp_record.check_otp(otp_code.strip())
        or (otp_record.otp_code == hashed_otp)
        or (otp_record.otp_code == otp_code.strip())
    )

    if not is_valid_otp:
        failed_attempts += 1
        cache.set(cache_key, failed_attempts, timeout=900)
        if failed_attempts >= 5:
            OTPVerification.objects.filter(id=otp_record.id).update(is_used=True)
            cache.set(f"otp_burned:{otp_record.id}", True, timeout=900)
            raise DomainValidationError("Too many failed attempts. This verification code has been invalidated. Please request a new code.")
        remaining = 5 - failed_attempts
        raise DomainValidationError(f"Invalid verification OTP. {remaining} attempt(s) remaining.")

    with transaction.atomic():
        otp_record.is_used = True
        otp_record.save(update_fields=["is_used"])

        user.is_verified = True
        user.status = UserStatus.ACTIVE
        user.save(update_fields=["is_verified", "status"])

    cache.delete(cache_key)
    cache.delete(f"otp_burned:{otp_record.id}")
    return user


@transaction.atomic
def resend_signup_otp(email: str) -> None:
    """
    Generates and resends a fresh signup OTP code.
    """
    email_clean = email.lower().strip()
    try:
        user = User.objects.get(email=email_clean)
    except User.DoesNotExist:
        raise ResourceNotFoundError("User with this email was not found.")

    if user.is_verified:
        raise DomainValidationError("This account is already verified. Please proceed to login.")

    # Mark previous as used
    OTPVerification.objects.filter(
        email=email_clean,
        purpose=OTPVerification.Purpose.SIGNUP_VERIFICATION,
        is_used=False,
    ).update(is_used=True)

    otp_code = generate_numeric_otp()
    expires_at = timezone.now() + timedelta(minutes=15)
    OTPVerification.objects.create(
        email=email_clean,
        otp_code=otp_code,
        purpose=OTPVerification.Purpose.SIGNUP_VERIFICATION,
        expires_at=expires_at,
    )

    subject = "Many Gym - New Verification Code"
    message = f"Hello {user.first_name},\n\nYour new verification code is: {otp_code} (expires in 15 minutes)."
    html_message = (
        f"<h3>Hello {user.first_name},</h3>"
        f"<p>Your new verification code is: <strong style='font-size:24px;color:#2563eb;'>{otp_code}</strong></p>"
        f"<p>This code will expire in 15 minutes.</p>"
    )
    transaction.on_commit(lambda: send_email_task.delay(subject, [email_clean], message, html_message))


@transaction.atomic
def request_password_reset(email: str) -> None:
    """
    Initiates forgot-password OTP dispatch.
    """
    email_clean = email.lower().strip()
    try:
        user = User.objects.get(email=email_clean)
    except User.DoesNotExist:
        # Don't leak user existence in response, return quietly
        return

    # Invalidate prior password reset OTPs
    OTPVerification.objects.filter(
        email=email_clean,
        purpose=OTPVerification.Purpose.PASSWORD_RESET,
        is_used=False,
    ).update(is_used=True)

    otp_code = generate_numeric_otp()
    expires_at = timezone.now() + timedelta(minutes=15)
    OTPVerification.objects.create(
        email=email_clean,
        otp_code=otp_code,
        purpose=OTPVerification.Purpose.PASSWORD_RESET,
        expires_at=expires_at,
    )

    subject = "Many Gym - Password Reset Code"
    message = (
        f"Hello {user.first_name},\n\n"
        f"You requested to reset your Many Gym password.\n"
        f"Your reset code is: {otp_code}\n"
        f"If you did not make this request, please ignore this email.\n"
    )
    html_message = (
        f"<h3>Hello {user.first_name},</h3>"
        f"<p>You requested to reset your password for <strong>Many Gym</strong>.</p>"
        f"<p>Your reset code is: <strong style='font-size:24px;color:#dc2626;'>{otp_code}</strong></p>"
        f"<p>This code expires in 15 minutes. If you did not request this, please ignore this email.</p>"
    )
    transaction.on_commit(lambda: send_email_task.delay(subject, [email_clean], message, html_message))


def verify_password_reset_otp(email: str, otp_code: str) -> bool:
    """
    Verifies that the password reset OTP is currently valid.
    Enforces maximum 5 attempts per OTP code to prevent brute-forcing.
    """
    email_clean = email.lower().strip()
    otp_record = (
        OTPVerification.objects.filter(
            email=email_clean,
            purpose=OTPVerification.Purpose.PASSWORD_RESET,
            is_used=False,
        )
        .order_by("-created_at")
        .first()
    )

    from django.core.cache import cache
    if not otp_record or not otp_record.is_valid() or (otp_record and cache.get(f"otp_burned:{otp_record.id}")):
        raise DomainValidationError("Invalid or expired password reset code.")

    cache_key = f"otp_failed:{otp_record.id}"
    failed_attempts = cache.get(cache_key, 0)
    if failed_attempts >= 5 or cache.get(f"otp_burned:{otp_record.id}"):
        OTPVerification.objects.filter(id=otp_record.id).update(is_used=True)
        cache.set(f"otp_burned:{otp_record.id}", True, timeout=900)
        raise DomainValidationError("Too many failed attempts. This password reset code has been invalidated. Please request a new code.")

    hashed_otp = hash_otp(email_clean, otp_code.strip())
    is_valid_otp = (
        otp_record.check_otp(otp_code.strip())
        or (otp_record.otp_code == hashed_otp)
        or (otp_record.otp_code == otp_code.strip())
    )

    if not is_valid_otp:
        failed_attempts += 1
        cache.set(cache_key, failed_attempts, timeout=900)
        if failed_attempts >= 5:
            OTPVerification.objects.filter(id=otp_record.id).update(is_used=True)
            cache.set(f"otp_burned:{otp_record.id}", True, timeout=900)
            raise DomainValidationError("Too many failed attempts. This password reset code has been invalidated. Please request a new code.")
        remaining = 5 - failed_attempts
        raise DomainValidationError(f"Invalid password reset code. {remaining} attempt(s) remaining.")

    return True


def reset_password(email: str, otp_code: str, new_password: str) -> User:
    """
    Resets the user's password using the verified OTP.
    Enforces maximum 5 attempts per OTP code to prevent brute-forcing.
    """
    email_clean = email.lower().strip()
    try:
        user = User.objects.get(email=email_clean)
    except User.DoesNotExist:
        raise ResourceNotFoundError("User not found.")

    otp_record = (
        OTPVerification.objects.filter(
            email=email_clean,
            purpose=OTPVerification.Purpose.PASSWORD_RESET,
            is_used=False,
        )
        .order_by("-created_at")
        .first()
    )

    from django.core.cache import cache
    if not otp_record or not otp_record.is_valid() or (otp_record and cache.get(f"otp_burned:{otp_record.id}")):
        raise DomainValidationError("Invalid or expired password reset code.")

    cache_key = f"otp_failed:{otp_record.id}"
    failed_attempts = cache.get(cache_key, 0)
    if failed_attempts >= 5 or cache.get(f"otp_burned:{otp_record.id}"):
        OTPVerification.objects.filter(id=otp_record.id).update(is_used=True)
        cache.set(f"otp_burned:{otp_record.id}", True, timeout=900)
        raise DomainValidationError("Too many failed attempts. This password reset code has been invalidated. Please request a new code.")

    hashed_otp = hash_otp(email_clean, otp_code.strip())
    is_valid_otp = (
        otp_record.check_otp(otp_code.strip())
        or (otp_record.otp_code == hashed_otp)
        or (otp_record.otp_code == otp_code.strip())
    )

    if not is_valid_otp:
        failed_attempts += 1
        cache.set(cache_key, failed_attempts, timeout=900)
        if failed_attempts >= 5:
            OTPVerification.objects.filter(id=otp_record.id).update(is_used=True)
            cache.set(f"otp_burned:{otp_record.id}", True, timeout=900)
            raise DomainValidationError("Too many failed attempts. This password reset code has been invalidated. Please request a new code.")
        remaining = 5 - failed_attempts
        raise DomainValidationError(f"Invalid password reset code. {remaining} attempt(s) remaining.")

    if len(new_password) < 8:
        raise DomainValidationError("Password must be at least 8 characters long.")

    with transaction.atomic():
        user.set_password(new_password)
        user.save(update_fields=["password"])
        otp_record.is_used = True
        otp_record.save(update_fields=["is_used"])

    cache.delete(cache_key)
    cache.delete(f"otp_burned:{otp_record.id}")
    return user


@transaction.atomic
def change_password(user: User, current_password: str, new_password: str) -> None:
    """
    Changes a logged-in user's password after verifying the old password.
    """
    if not user.check_password(current_password):
        raise DomainValidationError("Current password does not match.")
    if len(new_password) < 8:
        raise DomainValidationError("New password must be at least 8 characters long.")
    user.set_password(new_password)
    user.save(update_fields=["password"])
