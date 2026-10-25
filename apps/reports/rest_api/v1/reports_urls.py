from django.urls import path
from apps.reports.rest_api.v1.views import (
    RevenueReportView,
    MembershipGrowthReportView,
    LeadFunnelReportView,
    TrainerWorkloadReportView,
)

urlpatterns = [
    path("revenue/", RevenueReportView.as_view(), name="reports-revenue"),
    path("membership-growth/", MembershipGrowthReportView.as_view(), name="reports-membership-growth"),
    path("leads-funnel/", LeadFunnelReportView.as_view(), name="reports-leads-funnel"),
    path("trainer-workload/", TrainerWorkloadReportView.as_view(), name="reports-trainer-workload"),
]
