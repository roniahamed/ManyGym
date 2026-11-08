from django.urls import path
from apps.authentication.rest_api.v1.views import (
    LoginView,
    SwitchContextView,
    LogoutView,
    TokenRefreshView,
    Verify2FAView,
    Resend2FAView,
)

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),
    path("verify-2fa/", Verify2FAView.as_view(), name="verify-2fa"),
    path("resend-2fa/", Resend2FAView.as_view(), name="resend-2fa"),
    path("switch-context/", SwitchContextView.as_view(), name="switch-context"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh-alias"),
]
