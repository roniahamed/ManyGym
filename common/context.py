import contextvars
from typing import Optional, Any

_current_user_var: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar("current_user", default=None)


def set_current_user(user) -> None:
    """Sets the current authenticated user in context storage."""
    _current_user_var.set(user)


def get_current_user():
    """Retrieves the current authenticated user from context storage if present."""
    return _current_user_var.get()


def clear_current_user() -> None:
    """Clears context storage."""
    _current_user_var.set(None)
