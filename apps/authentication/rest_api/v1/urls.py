from django.urls import path
from apps.authentication.rest_api.v1.views import (
    LoginView,
    SwitchContextView,
    LogoutView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("switch-context/", SwitchContextView.as_view(), name="switch-context"),
    path("logout/", LogoutView.as_view(), name="logout"),
]
