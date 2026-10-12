from typing import Optional
from apps.users.models import User, UserProfile


def get_user_by_email(email: str) -> Optional[User]:
    """Retrieve user by normalized email."""
    return User.objects.filter(email=email.lower().strip()).first()


def get_user_by_id(user_id) -> Optional[User]:
    """Retrieve user with profile by UUID."""
    return User.objects.select_related("profile").filter(id=user_id).first()


def get_user_profile(user: User) -> UserProfile:
    """Retrieve or create user profile."""
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile
