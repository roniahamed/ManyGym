from typing import Optional, Iterator
from apps.users.models import User, UserProfile


def get_user_by_email(email: str) -> Optional[User]:
    """Retrieve user with profile by normalized email using select_related."""
    return User.objects.select_related("profile").filter(email=email.lower().strip()).first()


def get_user_by_id(user_id) -> Optional[User]:
    """Retrieve user with profile by UUID using select_related."""
    return User.objects.select_related("profile").filter(id=user_id).first()


def get_user_profile(user: User) -> UserProfile:
    """Retrieve or create user profile."""
    profile, _ = UserProfile.objects.select_related("user").get_or_create(user=user)
    return profile


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

