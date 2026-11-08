import uuid
import logging
from datetime import timedelta
from typing import Optional, Dict, Any
from django.db import transaction
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings

from apps.users.models import User, UserSetting, OTPVerification, UserDevice
from apps.messaging.models import UserDeviceKey
from apps.authentication.models import AuthToken
from apps.users.tasks import send_email_task, send_sms_task
from common.exceptions import DomainValidationError, ResourceNotFoundError

logger = logging.getLogger(__name__)


def mask_email(email: str) -> str:
    """Masks an email address for privacy display (e.g. al***@domain.com)."""
    if not email or "@" not in email:
        return email or ""
    parts = email.split("@")
    name = parts[0]
    domain = parts[1]
    if len(name) <= 2:
        masked_name = name[0] + "***"
    else:
        masked_name = name[:2] + "***"
    return f"{masked_name}@{domain}"


def mask_phone(phone: str) -> str:
    """Masks a phone number for privacy display (e.g. +141***2671)."""
    if not phone or len(phone) < 6:
        return phone or ""
    return f"{phone[:4]}***{phone[-4:]}"


def get_user_contact_info(user: User) -> Dict[str, Any]:
    """Returns contact info dictionary with primary email, secondary email, and phone."""
    return {
        "primary_email": user.email,
        "secondary_email": user.secondary_email,
        "phone": user.phone,
    }


@transaction.atomic
def update_user_contact_info(
    user: User,
    secondary_email: Optional[str] = ...,
    phone: Optional[str] = ...,
) -> User:
    """
    Updates optional secondary email and phone.
    Guarantees primary email cannot be updated or deleted.
    """
    update_fields = ["updated_at"]

    if secondary_email is not ...:
        if secondary_email is None or secondary_email == "":
            user.secondary_email = None
            update_fields.append("secondary_email")
        else:
            cleaned_email = secondary_email.strip().lower()
            if cleaned_email == user.email.lower():
                raise DomainValidationError("Secondary email cannot be the same as primary email.")
            user.secondary_email = cleaned_email
            update_fields.append("secondary_email")

    if phone is not ...:
        if phone is None or phone == "":
            user.phone = None
            update_fields.append("phone")
        else:
            cleaned_phone = phone.strip()
            if len(cleaned_phone) > 50:
                raise DomainValidationError("Phone number cannot exceed 50 characters.")
            user.phone = cleaned_phone
            update_fields.append("phone")

    user.save(update_fields=update_fields)
    logger.info("Updated contact info for user %s (%s)", user.email, user.id)
    return user


def get_user_security_overview(user: User) -> Dict[str, Any]:
    """Retrieves high-level summary of login and security settings for the user."""
    setting = user.get_settings()
    devices_count = UserDevice.objects.filter(user=user).count()

    is_del_pending = False
    if setting.is_deleted and setting.deleted_at:
        if timezone.now() - setting.deleted_at <= timedelta(hours=24):
            is_del_pending = True

    return {
        "contact_info": get_user_contact_info(user),
        "two_factor_enabled": setting.two_factor_enabled,
        "logged_in_devices_count": devices_count,
        "max_devices": 5,
        "account_status": {
            "is_deactivated": setting.is_deactivated,
            "deactivated_at": setting.deactivated_at,
            "is_deleted": setting.is_deleted,
            "deleted_at": setting.deleted_at,
            "delete_pending": is_del_pending,
        },
    }


@transaction.atomic
def toggle_user_2fa(user: User, enabled: bool) -> bool:
    """Enables or disables Two Factor Authentication for user profile."""
    setting = user.get_settings()
    setting.two_factor_enabled = bool(enabled)
    setting.save(update_fields=["two_factor_enabled", "updated_at"])
    logger.info("Set 2FA enabled=%s for user %s", enabled, user.email)
    return setting.two_factor_enabled


def generate_six_digit_otp() -> str:
    """Generates a cryptographically strong 6-digit numeric OTP."""
    import secrets
    return f"{secrets.randbelow(900000) + 100000:06d}"


def _send_otp_email_direct(to_email: str, first_name: str, otp_code: str):
    """Dispatches 2FA email synchronously to catch failures for fallback."""
    subject = "Many Gym - Two-Factor Authentication Code"
    message = (
        f"Hello {first_name},\n\n"
        f"Your Two-Factor Authentication (2FA) verification code is: {otp_code}\n"
        f"This code will expire in 10 minutes.\n\n"
        f"If you did not request this login, please secure your account immediately.\n\n"
        f"Regards,\nMany Gym Security Team"
    )
    html_message = (
        f"<h3>Hello {first_name},</h3>"
        f"<p>Your Two-Factor Authentication code is: "
        f"<strong style='font-size:24px;color:#2563eb;'>{otp_code}</strong></p>"
        f"<p>This code will expire in 10 minutes.</p>"
    )
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[to_email],
        html_message=html_message,
        fail_silently=False,
    )


def _send_otp_sms_direct(phone: str, otp_code: str):
    """Dispatches 2FA SMS synchronously to catch failures."""
    message = f"Many Gym: Your 2FA security code is {otp_code}. Valid for 10 minutes."
    # Queue via Celery task or direct integration
    send_sms_task.delay(phone, message)


@transaction.atomic
def dispatch_2fa_otp(user: User, force_channel: Optional[str] = None) -> Dict[str, Any]:
    """
    Dispatches a 2FA OTP following the strict fallback protocol:
    1. Primary Email (user.email)
    2. If failed -> Secondary Email (user.secondary_email)
    3. If failed -> Phone SMS (user.phone)
    """
    # Invalidate previous unused 2FA OTPs for this user's email
    OTPVerification.objects.filter(
        email=user.email.lower().strip(),
        purpose=OTPVerification.Purpose.TWO_FACTOR,
        is_used=False,
    ).update(is_used=True)

    otp_code = generate_six_digit_otp()
    expires_at = timezone.now() + timedelta(minutes=10)

    OTPVerification.objects.create(
        email=user.email.lower().strip(),
        otp_code=otp_code,
        purpose=OTPVerification.Purpose.TWO_FACTOR,
        expires_at=expires_at,
    )

    success = False
    channel_used = None
    dest_used = None

    if force_channel == "secondary_email":
        if not user.secondary_email:
            raise DomainValidationError("No secondary email registered on your account.")
        _send_otp_email_direct(user.secondary_email, user.first_name, otp_code)
        channel_used = "secondary_email"
        dest_used = mask_email(user.secondary_email)
        success = True
    elif force_channel == "phone_sms":
        if not user.phone:
            raise DomainValidationError("No phone number registered on your account.")
        _send_otp_sms_direct(user.phone, otp_code)
        channel_used = "phone_sms"
        dest_used = mask_phone(user.phone)
        success = True
    elif force_channel == "primary_email":
        _send_otp_email_direct(user.email, user.first_name, otp_code)
        channel_used = "primary_email"
        dest_used = mask_email(user.email)
        success = True
    else:
        # Automatic fallback sequence: Primary -> Secondary -> Phone SMS
        # Attempt 1: Primary email
        try:
            _send_otp_email_direct(user.email, user.first_name, otp_code)
            channel_used = "primary_email"
            dest_used = mask_email(user.email)
            success = True
        except Exception as exc:
            logger.warning("Primary email dispatch failed for user %s: %s", user.email, exc)

        # Attempt 2: Secondary email if primary failed
        if not success and user.secondary_email:
            try:
                _send_otp_email_direct(user.secondary_email, user.first_name, otp_code)
                channel_used = "secondary_email"
                dest_used = mask_email(user.secondary_email)
                success = True
            except Exception as exc:
                logger.warning("Secondary email dispatch failed for user %s: %s", user.secondary_email, exc)

        # Attempt 3: Phone SMS if secondary failed / absent
        if not success and user.phone:
            try:
                _send_otp_sms_direct(user.phone, otp_code)
                channel_used = "phone_sms"
                dest_used = mask_phone(user.phone)
                success = True
            except Exception as exc:
                logger.warning("Phone SMS dispatch failed for user %s: %s", user.phone, exc)

    if not success:
        raise DomainValidationError("Unable to send 2FA verification code via available contact methods.")

    logger.info("Dispatched 2FA OTP for user %s via %s (%s)", user.email, channel_used, dest_used)
    return {
        "channel": channel_used,
        "destination": dest_used,
        "email": user.email,
        "message": f"Verification code sent via {channel_used.replace('_', ' ')}.",
    }


@transaction.atomic
def verify_2fa_otp(email: str, otp_code: str) -> User:
    """
    Validates a submitted 2FA OTP code and returns verified user.
    """
    email_clean = email.lower().strip()
    try:
        user = User.objects.get(email=email_clean)
    except User.DoesNotExist:
        raise DomainValidationError("Invalid email or user not found.")

    otp_record = (
        OTPVerification.objects.filter(
            email=email_clean,
            purpose=OTPVerification.Purpose.TWO_FACTOR,
            is_used=False,
            expires_at__gte=timezone.now(),
        )
        .order_by("-created_at")
        .first()
    )

    if not otp_record or not otp_record.check_otp(otp_code):
        raise DomainValidationError("Invalid or expired verification code.")

    otp_record.is_used = True
    otp_record.save(update_fields=["is_used"])

    logger.info("2FA successfully verified for user %s", user.email)
    return user


# ==============================================================================
# LOGGED IN DEVICES (MAX 5)
# ==============================================================================

def list_user_devices(user: User):
    """Retrieves all logged-in devices for the user (up to 5)."""
    return UserDevice.objects.filter(user=user).order_by("-last_login")[:5]


@transaction.atomic
def register_or_update_user_device(
    user: User,
    device_id: str,
    device_name: str = "",
    ip_address: Optional[str] = None,
    user_agent: str = "",
) -> UserDevice:
    """
    Registers a new logged-in device or updates an existing device.
    Enforces maximum of 5 concurrent devices.
    If the limit is exceeded, automatically evicts the oldest device(s) and cleans their keys.
    """
    if not device_id:
        device_id = str(uuid.uuid4())

    existing_device = UserDevice.objects.filter(user=user, device_id=device_id).first()
    if existing_device:
        existing_device.last_login = timezone.now()
        if device_name:
            existing_device.device_name = device_name
        if ip_address:
            existing_device.ip_address = ip_address
        if user_agent:
            existing_device.user_agent = user_agent
        existing_device.save(update_fields=["last_login", "device_name", "ip_address", "user_agent"])
        return existing_device

    # Check active devices count
    current_count = UserDevice.objects.filter(user=user).count()
    if current_count >= 5:
        # Evict oldest devices so total is at most 4 before adding the new device
        to_evict_count = current_count - 4
        oldest_devices = list(UserDevice.objects.filter(user=user).order_by("last_login")[:to_evict_count])
        for dev in oldest_devices:
            # Clean device key for messaging E2EE
            UserDeviceKey.objects.filter(user=user, device_id=dev.device_id).delete()
            # Invalidate session tokens for that device
            AuthToken.objects.filter(user=user, device_id=dev.device_id).delete()
            dev.delete()
            logger.info("Evicted device %s for user %s to enforce max 5 devices limit.", dev.device_id, user.email)

    new_device = UserDevice.objects.create(
        user=user,
        device_id=device_id,
        device_name=device_name or "Unknown Device",
        ip_address=ip_address,
        user_agent=user_agent or "",
    )
    logger.info("Registered device %s (%s) for user %s", new_device.device_name, new_device.device_id, user.email)
    return new_device


@transaction.atomic
def delete_user_device(user: User, identifier: str) -> bool:
    """
    Deletes a logged-in device by device_id or UUID id.
    Cleans associated cryptographic device keys and revokes active tokens for that device.
    """
    device = None
    # Try finding by device_id
    device = UserDevice.objects.filter(user=user, device_id=identifier).first()
    if not device:
        # Try finding by UUID primary key
        try:
            device = UserDevice.objects.filter(user=user, id=uuid.UUID(identifier)).first()
        except (ValueError, TypeError):
            device = None

    if not device:
        raise ResourceNotFoundError("Logged-in device not found.")

    target_device_id = device.device_id

    # Clean cryptographic keys for that device
    cleaned_keys_count, _ = UserDeviceKey.objects.filter(user=user, device_id=target_device_id).delete()
    # Revoke auth tokens for that device
    revoked_tokens_count, _ = AuthToken.objects.filter(user=user, device_id=target_device_id).delete()
    # Delete device record
    device.delete()

    logger.info(
        "Deleted device %s for user %s: cleaned %s keys and revoked %s tokens.",
        target_device_id,
        user.email,
        cleaned_keys_count,
        revoked_tokens_count,
    )
    return True

