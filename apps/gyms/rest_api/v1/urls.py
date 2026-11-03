from django.urls import path
from apps.gyms.rest_api.v1.views import (
    GymCreateView,
    GymProfileOverviewView,
    GymLocationView,
    GymOpeningHoursView,
    GymGalleryListView,
    GymGalleryReorderView,
    GymGalleryDetailView,
    GymSettingsView,
    GymBlockedUsersListView,
    GymBlockedUserDetailView,
    GymSearchUsersToBlockView,
    GymAccessControlActionView,
    GymFollowToggleView,
    GymFollowersListView,
    GymFollowingListView,
    UserFollowedGymsListView,
    GymMembersListView,
    GymMemberJoiningRequestView,
    GymFollowerBlockView,
    GymAdminLogsListView,
    GymAdminLogDetailView,
    GymAdminLogsMetricsView,
    GymAdminLogsActionTypesView,
)

app_name = "gyms_v1"

urlpatterns = [
    path("", GymCreateView.as_view(), name="gym-create"),
    path("profile/", GymProfileOverviewView.as_view(), name="gym-profile-default"),
    path("profile/overview/", GymProfileOverviewView.as_view(), name="gym-profile-overview"),
    path("profile/location/", GymLocationView.as_view(), name="gym-profile-location"),
    path("opening-hours/", GymOpeningHoursView.as_view(), name="gym-opening-hours"),
    path("gallery/", GymGalleryListView.as_view(), name="gym-gallery-list"),
    path("gallery/reorder/", GymGalleryReorderView.as_view(), name="gym-gallery-reorder"),
    path("gallery/<uuid:item_id>/", GymGalleryDetailView.as_view(), name="gym-gallery-detail"),
    path("settings/", GymSettingsView.as_view(), name="gym-settings"),
    path("settings/blocked-users/", GymBlockedUsersListView.as_view(), name="gym-settings-blocked-users"),
    path("settings/blocked-users/<uuid:user_id>/", GymBlockedUserDetailView.as_view(), name="gym-settings-blocked-user-detail"),
    path("settings/blocked-users/search/", GymSearchUsersToBlockView.as_view(), name="gym-settings-blocked-users-search"),
    path("settings/access-control/", GymAccessControlActionView.as_view(), name="gym-settings-access-control"),
    # Alerts & Logs -> Admin Logs routes
    path("logs/admin/", GymAdminLogsListView.as_view(), name="gym-admin-logs-list"),
    path("logs/admin/metrics/", GymAdminLogsMetricsView.as_view(), name="gym-admin-logs-metrics"),
    path("logs/admin/actions/", GymAdminLogsActionTypesView.as_view(), name="gym-admin-logs-actions"),
    path("logs/admin/<uuid:log_id>/", GymAdminLogDetailView.as_view(), name="gym-admin-log-detail"),
    # Convenient aliases matching "admin-logs" convention
    path("admin-logs/", GymAdminLogsListView.as_view(), name="gym-admin-logs-alias-list"),
    path("admin-logs/metrics/", GymAdminLogsMetricsView.as_view(), name="gym-admin-logs-alias-metrics"),
    path("admin-logs/actions/", GymAdminLogsActionTypesView.as_view(), name="gym-admin-logs-alias-actions"),
    path("admin-logs/<uuid:log_id>/", GymAdminLogDetailView.as_view(), name="gym-admin-log-alias-detail"),
    # Social follow & audience routes
    path("followed/", UserFollowedGymsListView.as_view(), name="gym-followed-list"),
    path("<uuid:gym_id>/follow/", GymFollowToggleView.as_view(), name="gym-follow-toggle"),
    path("<uuid:gym_id>/followers/", GymFollowersListView.as_view(), name="gym-followers-list"),
    path("<uuid:gym_id>/followers/<uuid:user_id>/block/", GymFollowerBlockView.as_view(), name="gym-follower-block"),
    path("<uuid:gym_id>/following/", GymFollowingListView.as_view(), name="gym-following-list"),
    path("<uuid:gym_id>/members/", GymMembersListView.as_view(), name="gym-members-list"),
    path("<uuid:gym_id>/join-request/", GymMemberJoiningRequestView.as_view(), name="gym-join-request"),
]

