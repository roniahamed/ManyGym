from apps.access_control.rest_api.v1.views.base_views import resolve_request_gym
from apps.access_control.rest_api.v1.views.permission_views import PermissionsListView
from apps.access_control.rest_api.v1.views.role_views import (
    RoleListCreateView,
    RoleDetailView,
)
from apps.access_control.rest_api.v1.views.staff_views import (
    StaffListInviteView,
    StaffDetailView,
)

__all__ = [
    "resolve_request_gym",
    "PermissionsListView",
    "RoleListCreateView",
    "RoleDetailView",
    "StaffListInviteView",
    "StaffDetailView",
]
