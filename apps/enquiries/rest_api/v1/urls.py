from django.urls import path
from apps.enquiries.rest_api.v1.views import (
    EnquiryListCreateView,
    EnquiryDetailView,
    EnquiryAddNoteView,
)

urlpatterns = [
    path("", EnquiryListCreateView.as_view(), name="enquiry-list-create"),
    path("<uuid:enquiry_id>/", EnquiryDetailView.as_view(), name="enquiry-detail"),
    path("<uuid:enquiry_id>/notes/", EnquiryAddNoteView.as_view(), name="enquiry-add-note"),
]

