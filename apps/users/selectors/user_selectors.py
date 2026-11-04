from typing import Optional, Iterator, Union
import uuid
from django.db.models import QuerySet
from apps.users.models import User, UserProfile, UserEducation, UserSocialLink, UserBlockedUser
from common.exceptions import ResourceNotFoundError, PermissionDeniedError, DomainValidationError


def get_user_by_email(email: str) -> Optional[User]:
    """Retrieve user with profile by normalized email using select_related."""
    return User.objects.select_related("profile").filter(email=email.lower().strip()).first()


def get_user_by_id(user_id) -> Optional[User]:
    """Retrieve user with profile by UUID using select_related."""
    try:
        uuid.UUID(str(user_id))
        return User.objects.select_related("profile").filter(id=user_id).first()
    except Exception:
        return None


def get_user_profile(user: User) -> UserProfile:
    """Retrieve or create user profile."""
    profile, _ = UserProfile.objects.select_related("user").get_or_create(user=user)
    return profile


def get_user_about_profile(
    user_or_id: Union[User, str, uuid.UUID],
    requesting_user: Optional[User] = None,
) -> User:
    """
    Retrieves full user entity with profile, educations, and social links eagerly preloaded.
    Enforces privacy invariants:
    - User must exist and not be soft-deleted.
    - If user is deactivated, only the user themselves can view it.
    - If requesting user is blocked by target user, raises PermissionDeniedError.
    - If target user is private, only the user themselves or approved followers can view it.
    """
    if isinstance(user_or_id, User):
        target_id = user_or_id.id
    else:
        try:
            target_id = uuid.UUID(str(user_or_id))
        except (ValueError, TypeError, AttributeError):
            raise DomainValidationError("Invalid user ID.")

    user = (
        User.objects.select_related("profile", "settings")
        .prefetch_related("educations", "social_links")
        .filter(id=target_id)
        .first()
    )
    if not user:
        raise ResourceNotFoundError("User not found.")

    setting = user.get_settings()
    if setting.is_deleted:
        raise ResourceNotFoundError("User not found.")

    if setting.is_deactivated:
        if not requesting_user or requesting_user.id != user.id:
            raise DomainValidationError("This user account is deactivated.")

    # Check blocking & privacy if viewing someone else's profile
    if requesting_user and requesting_user.is_authenticated and requesting_user.id != user.id:
        if UserBlockedUser.objects.filter(blocker=user, blocked_user=requesting_user).exists():
            raise PermissionDeniedError("You have been blocked by this user.")

    profile = getattr(user, "profile", None)
    if profile and profile.is_private:
        if not requesting_user or requesting_user.id != user.id:
            from apps.users.selectors.social_selectors import is_following_user
            if not requesting_user.is_authenticated or not is_following_user(requesting_user, user):
                raise PermissionDeniedError("This user account is private.")

    return user


def list_user_educations(user: User) -> QuerySet[UserEducation]:
    """Retrieves all education entries for a user ordered by from_year descending."""
    return UserEducation.objects.filter(user=user).order_by("-from_year", "-created_at")


def get_user_education_by_id(user: User, education_id) -> UserEducation:
    """Retrieves a single education entry for a user, or raises ResourceNotFoundError."""
    try:
        education_uuid = uuid.UUID(str(education_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid education ID.")

    education = UserEducation.objects.filter(id=education_uuid, user=user).first()
    if not education:
        raise ResourceNotFoundError("Education record not found.")
    return education


def list_user_social_links(user: User) -> QuerySet[UserSocialLink]:
    """Retrieves all social link entries for a user ordered by creation time."""
    return UserSocialLink.objects.filter(user=user).order_by("created_at")


def get_user_social_link_by_id(user: User, link_id) -> UserSocialLink:
    """Retrieves a single social link entry for a user, or raises ResourceNotFoundError."""
    try:
        link_uuid = uuid.UUID(str(link_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid social link ID.")

    link = UserSocialLink.objects.filter(id=link_uuid, user=user).first()
    if not link:
        raise ResourceNotFoundError("Social link record not found.")
    return link


def iter_users(chunk_size: int = 500) -> Iterator[User]:
    """
    Generator yielding users with profiles preloaded,
    streaming records via iterator() to minimize memory footprint.
    """
    for user in (
        User.objects.select_related("profile")
        .order_by("-created_at")
        .iterator(chunk_size=chunk_size)
    ):
        yield user
