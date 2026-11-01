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
]
