from rest_framework.permissions import BasePermission
from common.enums import TokenContextType


def make_scope_permission(scope_code: str):
    """
    Factory to create a dynamic DRF permission checking for a specific scope.
    """
    class ScopePermission(BasePermission):
        message = f"You do not possess the required '{scope_code}' scope for this gym operation."

        def has_permission(self, request, view):
            if not request.user or not request.user.is_authenticated:
                return False

            if request.user.is_superuser:
                return True

            # If user is in gym context and is the gym owner
            if getattr(request, "gym", None) and request.gym.owner_user_id == request.user.id:
                return True

            scopes = getattr(request, "scopes", [])
            return scope_code in scopes

    return ScopePermission


class IsGymContextActive(BasePermission):
    """
    Ensures that the current request is executed with an active Gym Context token.
    """
    message = "This operation requires an active Gym context token. Please switch context to a gym."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request, "token_context", "") == TokenContextType.GYM
            and getattr(request, "gym_id", None) is not None
        )


class IsGymOwnerOrAdmin(BasePermission):
    """
    Permits access if the user is the owner of the active gym or possesses administrator permissions.
    """
    message = "Only the gym owner or an administrator can perform this action."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.is_superuser:
            return True

        gym = getattr(request, "gym", None)
        if gym and gym.owner_user_id == request.user.id:
            return True

        scopes = getattr(request, "scopes", [])
        return "people_roles:manage" in scopes or "people_roles:read" in scopes
