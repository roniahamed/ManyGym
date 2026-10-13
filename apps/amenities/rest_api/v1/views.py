from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample, OpenApiParameter

from apps.amenities.rest_api.v1.serializers import (
    AmenityCatalogItemSerializer,
    GymAmenitiesConfiguredSerializer,
    SyncGymAmenitiesSerializer,
    SyncGymAmenitiesResponseSerializer,
)
from apps.amenities.services import sync_gym_amenities
from apps.amenities.selectors import get_master_catalog, get_gym_configured_amenities
from apps.gyms.rest_api.v1.views import resolve_gym_context, check_gym_permission
from common.serializers import ErrorDetailSerializer


class AmenityCatalogListView(APIView):
    """
    Public or authenticated catalog endpoint to retrieve the full master list of amenities
    grouped by their official category (Changing & Storage, Wellness & Recovery, etc.).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get Master Amenities Catalog",
        description="Returns system-wide master amenities categorized into 7 domains for UI rendering.",
        tags=["Amenities"],
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                description="Master catalog grouped by domain category."
            ),
        },
    )
    def get(self, request):
        data = get_master_catalog()
        return Response(data, status=status.HTTP_200_OK)


class GymConfiguredAmenitiesView(APIView):
    """
    Retrieves the currently selected/configured amenities for a gym,
    broken down into free and paid amenities.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get Gym's Configured Amenities",
        description="Returns all free and paid amenities enabled for the specified Gym.",
        tags=["Amenities"],
        parameters=[
            OpenApiParameter(
                name="gym_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Target gym UUID (if not inferred from active gym JWT context).",
            )
        ],
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=GymAmenitiesConfiguredSerializer,
                description="Active configured amenities list.",
            ),
            status.HTTP_404_NOT_FOUND: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:read")
        configured = get_gym_configured_amenities(str(gym.id))
        serializer = GymAmenitiesConfiguredSerializer(configured)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GymAmenitiesSyncView(APIView):
    """
    Synchronizes free and paid amenities for a gym.
    Enforces the core business invariant: An amenity cannot be simultaneously free and paid.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Sync Gym Amenities (Free & Paid)",
        description="Full sync of enabled amenities for a gym. Replaces previous selection. Enforces mutual exclusion.",
        tags=["Amenities"],
        parameters=[
            OpenApiParameter(
                name="gym_id",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Target gym UUID (if not inferred from active gym JWT context).",
            )
        ],
        request=SyncGymAmenitiesSerializer,
        responses={
            status.HTTP_200_OK: SyncGymAmenitiesResponseSerializer,
            status.HTTP_400_BAD_REQUEST: ErrorDetailSerializer,
            status.HTTP_403_FORBIDDEN: ErrorDetailSerializer,
        },
        examples=[
            OpenApiExample(
                name="Sync Request Example",
                value={
                    "free_amenity_ids": [
                        "11111111-1111-1111-1111-111111111111",
                        "22222222-2222-2222-2222-222222222222"
                    ],
                    "paid_amenities": [
                        {
                            "amenity_id": "33333333-3333-3333-3333-333333333333",
                            "default_price": "5.00"
                        }
                    ]
                },
                request_only=True,
            )
        ]
    )
    def put(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")

        serializer = SyncGymAmenitiesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = sync_gym_amenities(
            gym=gym,
            free_amenity_ids=serializer.validated_data.get("free_amenity_ids", []),
            paid_amenities=serializer.validated_data.get("paid_amenities", []),
        )

        response_data = {
            "message": "Amenities synchronized successfully.",
            "free_count": result["free_count"],
            "paid_count": result["paid_count"],
        }
        return Response(response_data, status=status.HTTP_200_OK)
