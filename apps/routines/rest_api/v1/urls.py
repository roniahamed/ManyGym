from django.urls import path
from apps.routines.rest_api.v1.views import (
    RoutineTemplateListCreateView,
    RoutineTemplateDetailView,
    MemberRoutineListView,
    MemberRoutineAssignView,
    MemberRoutineDetailView,
)

urlpatterns = [
    # 6.1 Routine Templates
    path("routine-templates/", RoutineTemplateListCreateView.as_view(), name="routine-template-list-create"),
    path("routine-templates/<uuid:template_id>/", RoutineTemplateDetailView.as_view(), name="routine-template-detail"),

    # 6.2 Member Routine Prescription
    path("members/<uuid:member_id>/routines/", MemberRoutineListView.as_view(), name="member-routine-list"),
    path("members/<uuid:member_id>/routines/assign/", MemberRoutineAssignView.as_view(), name="member-routine-assign"),
    path("members/<uuid:member_id>/routines/<uuid:routine_id>/", MemberRoutineDetailView.as_view(), name="member-routine-detail"),
]
