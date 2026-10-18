from django.urls import path
from apps.leads.rest_api.v1.views import (
    LeadListCreateView,
    LeadMetricsView,
    LeadReasonsView,
    LeadDetailUpdateDeleteView,
    LeadNextMoveListCreateView,
    LeadNextMoveDetailView,
    LeadNoteCreateView,
    LeadConvertView,
)

urlpatterns = [
    # Directory & Collection Endpoints
    path("", LeadListCreateView.as_view(), name="lead-list-create"),
    path("metrics/", LeadMetricsView.as_view(), name="lead-metrics"),
    path("reasons/", LeadReasonsView.as_view(), name="lead-reasons"),

    # Single Lead Dossier Operations
    path("<uuid:lead_id>/", LeadDetailUpdateDeleteView.as_view(), name="lead-detail-update-delete"),
    path("<uuid:lead_id>/next-moves/", LeadNextMoveListCreateView.as_view(), name="lead-next-moves-create"),
    path("<uuid:lead_id>/next-moves/<uuid:move_id>/", LeadNextMoveDetailView.as_view(), name="lead-next-move-detail"),
    path("<uuid:lead_id>/notes/", LeadNoteCreateView.as_view(), name="lead-notes-create"),
    path("<uuid:lead_id>/convert/", LeadConvertView.as_view(), name="lead-convert"),
]
