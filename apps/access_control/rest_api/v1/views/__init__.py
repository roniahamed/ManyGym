from apps.access_control.rest_api.v1.views.base import resolve_request_gym
from apps.access_control.rest_api.v1.views.permissions import PermissionsListView
from apps.access_control.rest_api.v1.views.roles import (
    RoleListCreateView,
    RoleDetailView,
)
from apps.access_control.rest_api.v1.views.staff import (
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
