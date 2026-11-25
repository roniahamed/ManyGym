from django.urls import path

from apps.search.rest_api.v1.views import CentralSearchView

app_name = "search_v1"

urlpatterns = [
    path("", CentralSearchView.as_view(), name="central-search"),
]
