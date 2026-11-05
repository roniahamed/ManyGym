from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample, inline_serializer

from apps.access_control.selectors import list_permissions_by_topic
from apps.access_control.rest_api.v1.serializers import PermissionSerializer
from common.serializers import ErrorDetailSerializer


class PermissionsListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Access Control & RBAC"],
        summary="List System Permissions Grouped by Topic",
        description="""
### Summary
Retrieves all system permission scopes organized across the 9 core topics:
1. **Studio**
2. **Reports**
3. **Gym Profile**
4. **Subscription Plans**
5. **Members**
6. **Leads**
7. **Trainers**
8. **Routine Templates**
9. **People & Roles**

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- Used by UI when gym administrators select permission checkboxes to create or edit custom roles.
        """,
        responses={
            200: OpenApiResponse(
                response=inline_serializer(
                    name="SystemPermissionsByTopicResponse",
                    fields={
                        "Studio": PermissionSerializer(many=True),
                        "Reports": PermissionSerializer(many=True),
                        "Gym Profile": PermissionSerializer(many=True),
                        "Subscription Plans": PermissionSerializer(many=True),
                        "Members": PermissionSerializer(many=True),
                        "Leads": PermissionSerializer(many=True),
                        "Trainers": PermissionSerializer(many=True),
                        "Routine Templates": PermissionSerializer(many=True),
                        "People & Roles": PermissionSerializer(many=True),
                    },
                ),
                description="Permissions grouped by topic dictionary.",
                examples=[
                    OpenApiExample(
                        name="Permissions Grouped Example",
                        value={
                            "Members": [
                                {
                                    "id": "6190cfd4-05b2-4aee-bf73-a2744d1c6607",
                                    "scope_code": "members:read",
                                    "name": "View Members",
                                    "description": "Read member directory and member details.",
                                },
                                {
                                    "id": "850ed65e-7f29-4342-b770-3ec7bf7a7f39",
                                    "scope_code": "members:edit",
                                    "name": "Edit Members",
                                    "description": "Edit member profile, status, or subscription.",
                                },
                            ],
                            "Routine Templates": [
                                {
                                    "id": "50e65f4e-4a78-4394-98ac-e9c4f96e8ad3",
                                    "scope_code": "routines:assign",
                                    "name": "Assign Routines",
                                    "description": "Assign routines to gym members.",
                                }
                            ],
                        },
                    )
                ],
            ),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
    )
    def get(self, request):
        data = list_permissions_by_topic()
        return Response(data, status=status.HTTP_200_OK)
