from django.urls import path
from apps.users.rest_api.v1.views import (
    RegisterView,
    VerifySignupOTPView,
    ResendOTPView,
    ForgotPasswordView,
    VerifyResetOTPView,
    ResetPasswordView,
    UserProfileMeView,
    ChangePasswordView,
    UserFollowToggleView,
    UserFollowersListView,
    UserFollowingListView,
    UnifiedFollowView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("verify-signup-otp/", VerifySignupOTPView.as_view(), name="verify-signup-otp"),
    path("resend-otp/", ResendOTPView.as_view(), name="resend-otp"),
    path("forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("verify-reset-otp/", VerifyResetOTPView.as_view(), name="verify-reset-otp"),
    path("reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    path("me/", UserProfileMeView.as_view(), name="me"),
    path("change-password/", ChangePasswordView.as_view(), name="change-password"),
    # Social follow routes
    path("follow/", UnifiedFollowView.as_view(), name="user-unified-follow"),
    path("<uuid:user_id>/follow/", UserFollowToggleView.as_view(), name="user-follow-toggle"),
    path("<uuid:user_id>/followers/", UserFollowersListView.as_view(), name="user-followers-list"),
    path("<uuid:user_id>/following/", UserFollowingListView.as_view(), name="user-following-list"),
]

