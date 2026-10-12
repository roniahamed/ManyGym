from django.urls import path
from apps.access_control.rest_api.v1.views import (
    PermissionsListView,
    RoleListCreateView,
    RoleDetailView,
    StaffListInviteView,
    StaffDetailView,
)


urlpatterns = [
    path("permissions/", PermissionsListView.as_view(), name="permissions-list"),
    path("roles/", RoleListCreateView.as_view(), name="roles-list-create"),
    path("roles/<uuid:role_id>/", RoleDetailView.as_view(), name="role-detail"),
    path("staff/", StaffListInviteView.as_view(), name="staff-list-invite"),
    path("staff/<uuid:assignment_id>/", StaffDetailView.as_view(), name="staff-detail"),
]
