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


def issue_context_token(user: User, context_type: str = TokenContextType.PERSONAL, gym: Gym = None) -> dict:
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


def authenticate_user(email: str, password: str) -> tuple[User, dict]:
    """
    Authenticates user credentials and returns user and personal context tokens.
    """
    email_clean = email.lower().strip()
    try:
        user = User.objects.select_related("profile").get(email=email_clean)
    except User.DoesNotExist:
        raise DomainValidationError("Invalid email or password.")

    if not user.check_password(password):
        raise DomainValidationError("Invalid email or password.")

    if user.status != UserStatus.ACTIVE or not user.is_active:
        raise DomainValidationError("Your account is currently inactive or suspended.")

    if not user.is_verified:
        raise DomainValidationError("Your account has not been verified yet. Please verify your OTP.")

    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    return user, tokens


def switch_gym_context(user: User, gym_id: str) -> dict:
    """
    Switches session context to a specific gym after validating user access.
    """
    try:
        gym = Gym.objects.select_related("owner_user").get(id=gym_id)
    except (Gym.DoesNotExist, ValueError):
        raise ResourceNotFoundError("Gym not found.")

    # Check if user is the gym owner
    is_owner = (gym.owner_user_id == user.id) or user.is_superuser

    # Check if user has active staff assignment
    is_staff = GymStaffAssignment.objects.filter(
        user=user,
        gym=gym,
        status="active",
    ).exists()

    if not (is_owner or is_staff):
        raise UnauthorizedContextError(f"You do not have access rights to gym '{gym.name}'.")

    return issue_context_token(user, context_type=TokenContextType.GYM, gym=gym)


def switch_to_personal_context(user: User) -> dict:
    """
    Switches session context back to Personal Profile.
    """
    return issue_context_token(user, context_type=TokenContextType.PERSONAL)


def revoke_token(access_token_str: str) -> None:
    """
    Revokes the given session token.
    """
    token_hash = hash_token_string(access_token_str)
    AuthToken.objects.filter(token_hash=token_hash).delete()
