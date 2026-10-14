from django.urls import path
from apps.members.rest_api.v1.views import (
    MemberListCreateView,
    MemberDetailView,
    MemberResendInvitationView,
    MemberAcceptInvitationView,
    MemberSubscriptionCreateView,
    MemberSubscriptionStatusView,
    MemberSubscriptionPaymentCreateView,
    MemberSubscriptionExtraAmenitiesView,
    MemberMetricsView,
)

urlpatterns = [
    path("", MemberListCreateView.as_view(), name="member-list-create"),
    path("metrics/", MemberMetricsView.as_view(), name="member-metrics"),
    path("accept-invitation/", MemberAcceptInvitationView.as_view(), name="member-accept-invitation"),
    path("<uuid:member_id>/", MemberDetailView.as_view(), name="member-detail"),
    path("<uuid:member_id>/resend-invitation/", MemberResendInvitationView.as_view(), name="member-resend-invitation"),
    path("<uuid:member_id>/subscriptions/", MemberSubscriptionCreateView.as_view(), name="member-subscription-create"),
    path("subscriptions/<uuid:subscription_id>/status/", MemberSubscriptionStatusView.as_view(), name="member-subscription-status"),
    path("subscriptions/<uuid:subscription_id>/payments/", MemberSubscriptionPaymentCreateView.as_view(), name="member-subscription-payment-create"),
    path("subscriptions/<uuid:subscription_id>/extra-amenities/", MemberSubscriptionExtraAmenitiesView.as_view(), name="member-subscription-extra-amenities"),
]
