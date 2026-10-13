from django.urls import path
from apps.amenities.rest_api.v1.views import (
    AmenityCatalogListView,
    GymConfiguredAmenitiesView,
    GymAmenitiesSyncView,
)

app_name = "amenities_v1"

urlpatterns = [
    path("catalog/", AmenityCatalogListView.as_view(), name="amenity-catalog"),
    path("gym-amenities/", GymConfiguredAmenitiesView.as_view(), name="gym-amenities-configured"),
    path("gym-amenities/sync/", GymAmenitiesSyncView.as_view(), name="gym-amenities-sync"),
]
