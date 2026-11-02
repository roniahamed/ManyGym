from apps.routines.rest_api.v1.views.base import (
    resolve_routine_gym,
    check_routine_permission,
)
from apps.routines.rest_api.v1.views.template import (
    RoutineTemplateListCreateView,
    RoutineTemplateDetailView,
)
from apps.routines.rest_api.v1.views.assignment import (
    MemberRoutineListView,
    MemberRoutineAssignView,
    MemberRoutineDetailView,
)

__all__ = [
    "resolve_routine_gym",
    "check_routine_permission",
    "RoutineTemplateListCreateView",
    "RoutineTemplateDetailView",
    "MemberRoutineListView",
    "MemberRoutineAssignView",
    "MemberRoutineDetailView",
]
