import hashlib
from datetime import datetime, timezone
from rest_framework_simplejwt.tokens import RefreshToken
from apps.authentication.models import AuthToken
from apps.users.models import User
from apps.gyms.models import Gym
from apps.access_control.selectors import get_user_gym_scopes
from apps.access_control.models import GymStaffAssignment
from common.enums import TokenContextType, UserStatus
from common.exceptions import (
    UnauthorizedContextError,
    DomainValidationError,
    ResourceNotFoundError,
)


def hash_token_string(token_str: str) -> str:
    """Computes SHA256 digest of a token string."""
    return hashlib.sha256(token_str.encode("utf-8")).hexdigest()


def issue_context_token(user: User, context_type: str = TokenContextType.PERSONAL, gym: Gym = None, device_id: str = "") -> dict:
    """
    Generates a JWT access and refresh token pair signed with specific context claims.
    Registers the session in AuthToken table.
    """
    refresh = RefreshToken.for_user(user)

    # Context Claims
    refresh["context_type"] = context_type
    refresh["email"] = user.email
    refresh["first_name"] = user.first_name
    refresh["last_name"] = user.last_name

    scopes = []
    if context_type == TokenContextType.GYM and gym:
        refresh["gym_id"] = str(gym.id)
        refresh["gym_name"] = gym.name
        scopes = get_user_gym_scopes(user, gym)
        refresh["scopes"] = scopes
    else:
        refresh["gym_id"] = None
        refresh["gym_name"] = None
        refresh["scopes"] = []

    # Also mirror claims onto the access token
    access = refresh.access_token
    access["context_type"] = context_type
    access["email"] = user.email
    access["first_name"] = user.first_name
    access["last_name"] = user.last_name
    access["gym_id"] = str(gym.id) if (context_type == TokenContextType.GYM and gym) else None
    access["gym_name"] = gym.name if (context_type == TokenContextType.GYM and gym) else None
    access["scopes"] = scopes

    access_str = str(access)
    refresh_str = str(refresh)
    token_hash = hash_token_string(access_str)

    # Compute expiration datetime
    exp_timestamp = access.payload["exp"]
    expires_at = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)

    AuthToken.objects.create(
        user=user,
        gym=gym if context_type == TokenContextType.GYM else None,
        token_hash=token_hash,
        context_type=context_type,
        device_id=device_id or "",
        expires_at=expires_at,
    )

    return {
        "access": access_str,
        "refresh": refresh_str,
        "context_type": context_type,
        "gym_id": str(gym.id) if gym else None,
        "gym_name": gym.name if gym else None,
        "scopes": scopes,
    }


def authenticate_user(
    email: str,
    password: str,
    reactivate: bool = False,
    restore: bool = False,
    device_id: str = "",
    device_name: str = "",
    ip_address: str = None,
    user_agent: str = "",
) -> tuple[User, dict]:
    """
    Authenticates user credentials and returns user and personal context tokens.
    Handles deactivated and soft-deleted accounts:
    - Account Deactivate: if login again, the deactivate status will be removed automatically.
    - Account Delete: 24 hours wait grace period; if login again within 24 hours, removes delete request.
      If beyond 24 hours, permanently rejected.
    Handles Two-Factor Authentication:
    - If 2FA is ON, dispatches OTP via fallback (Primary email -> Secondary email -> Phone SMS)
      and returns two_factor_required challenge.
    Enforces maximum 5 logged-in devices.
    """
    import uuid
    from datetime import timedelta
    from django.core.cache import cache
    from rest_framework.exceptions import Throttled
    from django.utils import timezone as dj_timezone

    email_clean = email.lower().strip()
    lockout_key = f"failed_login_lockout:{email_clean}"
    now_ts = dj_timezone.now().timestamp()
    lockout_record = cache.get(lockout_key)

    if lockout_record:
        count = lockout_record.get("count", 0)
        reset_at = lockout_record.get("reset_at", now_ts + 300)
        if count >= 5 and now_ts < reset_at:
            wait_seconds = max(1, int(reset_at - now_ts))
            raise Throttled(
                wait=wait_seconds,
                detail=f"Account locked due to consecutive failed login attempts. Try again in {wait_seconds} seconds.",
            )

    try:
        user = User.objects.select_related("profile").get(email=email_clean)
        user_exists = True
    except User.DoesNotExist:
        user = None
        user_exists = False

    if not user_exists or not user.check_password(password):
        prev_count = lockout_record.get("count", 0) if lockout_record else 0
        new_count = prev_count + 1
        reset_at = lockout_record.get("reset_at", now_ts + 300) if lockout_record else (now_ts + 300)
        cache.set(lockout_key, {"count": new_count, "reset_at": reset_at}, timeout=300)

        if new_count >= 5:
            wait_seconds = max(1, int(reset_at - now_ts))
            raise Throttled(
                wait=wait_seconds,
                detail=f"Account locked due to consecutive failed login attempts. Try again in {wait_seconds} seconds.",
            )
        raise DomainValidationError("Invalid email or password.")

    # Successful password verification -> clear failed login lockout
    cache.delete(lockout_key)

    setting = user.get_settings()

    # Account Delete: 24 hours wait. If login again within this time, we will remove delete request.
    if setting.is_deleted or user.status == UserStatus.DELETED:
        deleted_at = setting.deleted_at or user.updated_at
        if deleted_at and (dj_timezone.now() - deleted_at) <= timedelta(hours=24):
            from apps.users.services.settings_services import apply_user_access_control_action
            apply_user_access_control_action(user, action="restore", password=password)
            user.refresh_from_db()
            setting.refresh_from_db()
        else:
            raise DomainValidationError("This account has been permanently deleted.")

    # Account Deactivate: if login again, the deactivate status will be removed.
    if setting.is_deactivated or user.status == UserStatus.DEACTIVATED:
        from apps.users.services.settings_services import apply_user_access_control_action
        apply_user_access_control_action(user, action="reactivate")
        user.refresh_from_db()
        setting.refresh_from_db()

    if user.status != UserStatus.ACTIVE or not user.is_active:
        raise DomainValidationError("Your account is currently inactive or suspended.")

    if not user.is_verified:
        raise DomainValidationError("Your account has not been verified yet. Please verify your OTP.")

    # Two Factor Authentication: ON/OFF
    if getattr(setting, "two_factor_enabled", False):
        from apps.users.services.security_services import dispatch_2fa_otp
        dispatch_info = dispatch_2fa_otp(user)
        return user, {
            "two_factor_required": True,
            "channel": dispatch_info["channel"],
            "destination": dispatch_info["destination"],
            "email": user.email,
            "message": dispatch_info["message"],
        }

    # Logged in Devices (Max 5)
    from apps.users.services.security_services import register_or_update_user_device
    effective_device_id = device_id.strip() if device_id else str(uuid.uuid4())
    register_or_update_user_device(
        user=user,
        device_id=effective_device_id,
        device_name=device_name,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL, device_id=effective_device_id)
    return user, tokens


def switch_gym_context(user: User, gym_id: str) -> dict:
    """
    Switches session context to a specific gym after validating user access.
    """
    try:
        import uuid
        uuid.UUID(str(gym_id))
        gym = Gym.objects.select_related("owner_user", "settings").get(id=gym_id)
    except Exception:
        raise ResourceNotFoundError("Gym not found.")

    settings_obj = getattr(gym, "settings", None)
    if settings_obj and getattr(settings_obj, "is_deleted", False):
        raise ResourceNotFoundError("Gym not found.")

    # Check if user is the gym owner
    is_owner = (gym.owner_user_id == user.id) or user.is_superuser

    # Check if user has active staff assignment only if not owner
    is_staff = False
    if not is_owner:
        is_staff = GymStaffAssignment.objects.filter(
            user=user,
            gym=gym,
            status="active",
        ).exists()

    if not (is_owner or is_staff):
        raise UnauthorizedContextError(f"You do not have access rights to gym '{gym.name}'.")

    tokens = issue_context_token(user, context_type=TokenContextType.GYM, gym=gym)
    tokens["_gym"] = gym
    return tokens


def switch_to_personal_context(user: User) -> dict:
    """
    Switches session context back to Personal Profile.
    """
    return issue_context_token(user, context_type=TokenContextType.PERSONAL)


def is_token_revoked(token_str: str, validated_token=None) -> bool:
    """
    Checks whether the token string or its jti has been marked revoked in the cache denylist.
    """
    if not token_str:
        return False

    from django.core.cache import cache
    token_hash = hash_token_string(token_str)
    if cache.get(f"revoked_token:{token_hash}"):
        return True

    jti = None
    if validated_token is not None:
        jti = validated_token.get("jti")
    else:
        try:
            from rest_framework_simplejwt.tokens import UntypedToken
            parsed = UntypedToken(token_str)
            jti = parsed.get("jti")
        except Exception:
            pass

    if jti and cache.get(f"revoked_jti:{jti}"):
        return True

    return False


def revoke_token(access_token_str: str = "", refresh_token_str: str = "") -> None:
    """
    Revokes the given session access token and/or refresh token.
    Adds them to the Redis denylist cache and removes the access token from the AuthToken table.
    """
    from django.core.cache import cache
    from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

    now_ts = datetime.now(timezone.utc).timestamp()

    if access_token_str:
        access_hash = hash_token_string(access_token_str)
        AuthToken.objects.filter(token_hash=access_hash).delete()
        ttl = 3600
        try:
            tok = AccessToken(access_token_str)
            exp = tok.get("exp")
            if exp:
                ttl = max(int(exp - now_ts), 60)
            jti = tok.get("jti")
            if jti:
                cache.set(f"revoked_jti:{jti}", True, timeout=ttl)
        except Exception:
            pass
        cache.set(f"revoked_token:{access_hash}", True, timeout=ttl)

    if refresh_token_str:
        refresh_hash = hash_token_string(refresh_token_str)
        ttl_r = 7 * 86400
        try:
            tok_r = RefreshToken(refresh_token_str)
            exp = tok_r.get("exp")
            if exp:
                ttl_r = max(int(exp - now_ts), 60)
            jti_r = tok_r.get("jti")
            if jti_r:
                cache.set(f"revoked_jti:{jti_r}", True, timeout=ttl_r)
        except Exception:
            pass
        cache.set(f"revoked_token:{refresh_hash}", True, timeout=ttl_r)


def refresh_context_token(refresh_token_str: str) -> dict:
    """
    Validates a refresh token, verifies it is not revoked, preserves contextual claims
    (context_type, gym_id, scopes), rotates the token pair, and registers the new session.
    """
    from rest_framework_simplejwt.tokens import RefreshToken
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework.exceptions import AuthenticationFailed

    if not refresh_token_str or not isinstance(refresh_token_str, str):
        raise DomainValidationError("A valid refresh token is required.")

    if is_token_revoked(refresh_token_str):
        raise AuthenticationFailed("Refresh token has been revoked.", code="token_revoked")

    try:
        old_refresh = RefreshToken(refresh_token_str)
    except TokenError as e:
        raise AuthenticationFailed(str(e), code="token_invalid")

    user_id = old_refresh.payload.get("user_id")
    if not user_id:
        raise AuthenticationFailed("Invalid token payload: missing user identifier.", code="token_invalid")

    try:
        user = User.objects.select_related("profile").get(id=user_id)
    except User.DoesNotExist:
        raise AuthenticationFailed("User not found.", code="user_not_found")

    if not user.is_active or user.status != UserStatus.ACTIVE:
        raise AuthenticationFailed("User is inactive or suspended.", code="user_inactive")

    context_type = old_refresh.payload.get("context_type", TokenContextType.PERSONAL)
    gym_id = old_refresh.payload.get("gym_id")

    gym = None
    if context_type == TokenContextType.GYM and gym_id:
        try:
            gym = Gym.objects.select_related("settings").get(id=gym_id)
            settings_obj = getattr(gym, "settings", None)
            if settings_obj and getattr(settings_obj, "is_deleted", False):
                context_type = TokenContextType.PERSONAL
                gym = None
        except Gym.DoesNotExist:
            context_type = TokenContextType.PERSONAL
            gym = None

    # Revoke old refresh token for rotation
    revoke_token(access_token_str="", refresh_token_str=refresh_token_str)

    # Issue fresh contextual token pair
    return issue_context_token(user, context_type=context_type, gym=gym)


def cleanup_expired_tokens() -> int:
    """
    Purges all expired AuthToken records where expires_at < timezone.now().
    Returns number of deleted token records.
    """
    from django.utils import timezone
    deleted_count, _ = AuthToken.objects.filter(expires_at__lt=timezone.now()).order_by().delete()
    return deleted_count
