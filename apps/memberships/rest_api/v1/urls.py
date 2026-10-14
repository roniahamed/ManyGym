from django.urls import path
from apps.memberships.rest_api.v1.views import (
    MembershipPlanListCreateView,
    MembershipPlanDetailView,
    MembershipPlanStatusView,
    MembershipPlanAmenitiesSyncView,
    MembershipPlanMetricsView,
)

urlpatterns = [
    path("", MembershipPlanListCreateView.as_view(), name="membership-plans-list-create"),
    path("metrics/", MembershipPlanMetricsView.as_view(), name="membership-plans-metrics"),
    path("<uuid:plan_id>/", MembershipPlanDetailView.as_view(), name="membership-plan-detail"),
    path("<uuid:plan_id>/status/", MembershipPlanStatusView.as_view(), name="membership-plan-status"),
    path("<uuid:plan_id>/amenities/", MembershipPlanAmenitiesSyncView.as_view(), name="membership-plan-amenities-sync"),
]
