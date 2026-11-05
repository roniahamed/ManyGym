from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample, OpenApiParameter

from apps.gyms.rest_api.v1.serializers import (
    GymGalleryItemSerializer,
    GymGalleryCreateSerializer,
    GymGalleryReorderSerializer,
)
from apps.gyms.services import (
    add_gallery_item,
    reorder_gallery,
    delete_gallery_item,
)
from apps.gyms.selectors import list_gallery_items
from apps.gyms.rest_api.v1.views.base_views import resolve_gym_context, check_gym_permission
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


class GymGalleryListView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        tags=["Gym Profile & Multi-Location"],
        summary="List Gallery Media Assets",
        description="Retrieves photos and videos, optionally filtered by category and ordered by order_index.",
        parameters=[
            OpenApiParameter(name="gym_id", description="Optional Gym UUID", required=False, type=str),
            OpenApiParameter(name="category", description="Filter by category (e.g. equipment, workout_areas)", required=False, type=str),
        ],
        responses={
            200: OpenApiResponse(response=GymGalleryItemSerializer(many=True), description="Gallery items."),
        },
    )
    def get(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:read")
        category = request.query_params.get("category")
        items = list_gallery_items(str(gym.id), category=category)
        return Response(GymGalleryItemSerializer(items, many=True, context={"request": request}).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Gym Profile & Multi-Location"],
        summary="Add Gallery Media Asset",
        description="Uploads/registers a gallery photo or video with caption (up to 200 chars) and category.",
        parameters=[
            OpenApiParameter(name="gym_id", description="Optional Gym UUID", required=False, type=str)
        ],
        request=GymGalleryCreateSerializer,
        responses={
            201: OpenApiResponse(response=GymGalleryItemSerializer, description="Media item added."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
        },
        examples=[
            OpenApiExample(
                name="Add Gallery Item Payload",
                value={
                    "media_url": "https://cdn.manygym.com/gyms/titan/equipment-1.jpg",
                    "media_type": "picture",
                    "category": "equipment",
                    "caption": "Brand new Olympic lifting platforms and calibrated plates.",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")

        serializer = GymGalleryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = add_gallery_item(gym=gym, **serializer.validated_data)
        return Response(GymGalleryItemSerializer(item, context={"request": request}).data, status=status.HTTP_201_CREATED)


class GymGalleryReorderView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Profile & Multi-Location"],
        summary="Reorder Gallery Assets",
        description="Bulk updates display sequential position indices for gallery assets.",
        parameters=[
            OpenApiParameter(name="gym_id", description="Optional Gym UUID", required=False, type=str)
        ],
        request=GymGalleryReorderSerializer,
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="Gallery order updated."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
        },
    )
    def patch(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")

        serializer = GymGalleryReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reorder_gallery(gym, serializer.validated_data["items"])
        return Response({"message": "Gallery order updated successfully."}, status=status.HTTP_200_OK)


class GymGalleryDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Profile & Multi-Location"],
        summary="Delete Gallery Media Asset",
        description="Removes a photo or video from the gym gallery.",
        parameters=[
            OpenApiParameter(name="gym_id", description="Optional Gym UUID", required=False, type=str)
        ],
        responses={
            200: OpenApiResponse(response=MessageResponseSerializer, description="Asset deleted."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Asset not found."),
        },
    )
    def delete(self, request, item_id):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")
        delete_gallery_item(gym, item_id=str(item_id))
        return Response({"message": "Gallery asset successfully removed."}, status=status.HTTP_200_OK)
