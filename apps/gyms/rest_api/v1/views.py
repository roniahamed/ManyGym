from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample, OpenApiParameter

from apps.gyms.models import Gym, GymGallery
from apps.gyms.rest_api.v1.serializers import (
    GymCreateSerializer,
    GymDetailSerializer,
    GymOverviewUpdateSerializer,
    GymLocationSerializer,
    GymLocationUpdateSerializer,
    GymOpeningHoursItemSerializer,
    GymOpeningHoursBulkUpdateSerializer,
    GymGalleryItemSerializer,
    GymGalleryCreateSerializer,
    GymGalleryReorderSerializer,
)
from apps.gyms.services import (
    create_gym,
    update_gym_overview,
    update_gym_location,
    bulk_update_opening_hours,
    add_gallery_item,
    reorder_gallery,
    delete_gallery_item,
)
from apps.gyms.selectors import (
    get_gym_overview,
    get_gym_location,
    get_opening_hours,
    list_gallery_items,
)
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


def resolve_gym_context(request) -> Gym:
    """Helper to determine the target gym from active token context or query param, with request-level caching."""
    cached = getattr(request, "_resolved_gym", None)
    if cached is not None:
        return cached

    gym_id = getattr(request, "gym_id", None) or request.query_params.get("gym_id")
    if not gym_id:
        raise DomainValidationError("An active Gym context token or 'gym_id' query parameter is required.")
    try:
        import uuid
        uuid.UUID(str(gym_id))
        gym = Gym.objects.only("id", "owner_user_id", "name", "timezone").get(id=gym_id)
    except (Gym.DoesNotExist, ValueError, AttributeError):
        raise ResourceNotFoundError("Gym not found.")
    request._resolved_gym = gym
    return gym


def check_gym_permission(request, gym: Gym, required_scope: str = None) -> None:
    """Enforces owner or scope-based authorization."""
    if gym.owner_user_id == request.user.id or request.user.is_superuser:
        return
    scopes = getattr(request, "scopes", [])
    if required_scope and required_scope not in scopes:
        raise PermissionDeniedError(f"You do not possess the required '{required_scope}' scope for this gym operation.")


class GymCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Profile & Multi-Location"],
        summary="Create New Gym Workspace",
        description="""
### Summary
Creates a new gym workspace entity, sets the creator as the Owner, provisions the initial primary location, seeds the default 7-day operating hours, and grants the Administrator role.

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- Any authenticated user can create a new gym.
        """,
        request=GymCreateSerializer,
        responses={
            201: OpenApiResponse(response=GymDetailSerializer, description="Gym successfully created."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
        },
        examples=[
            OpenApiExample(
                name="Create Gym Payload",
                value={
                    "name": "Titan Strength & Fitness Club",
                    "primary_type": "strength_bodybuilding_gym",
                    "short_description": "Titan Strength & Fitness Club offers world-class bodybuilding equipment, powerlifting platforms, dynamic functional fitness spaces, dedicated recovery saunas, and personalized nutrition guidance for all levels.",
                    "gender_required": "everyone",
                    "min_age": 16,
                    "address": "450 Broadway, New York, NY",
                    "latitude": 40.7198,
                    "longitude": -74.0003,
                    "city": "New York",
                    "country": "United States",
                    "postal_code": "10013",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = GymCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        gym = create_gym(
            owner_user=request.user,
            **serializer.validated_data,
        )
        return Response(GymDetailSerializer(gym).data, status=status.HTTP_201_CREATED)


class GymProfileOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Profile & Multi-Location"],
        summary="Get Gym Profile Overview",
        description="""
### Summary
Retrieves complete gym profile overview including physical location, operating hours count, and media gallery count.
        """,
        parameters=[
            OpenApiParameter(
                name="gym_id",
                description="Optional Gym UUID if not using a Gym context token",
                required=False,
                type=str,
            )
        ],
        responses={
            200: OpenApiResponse(response=GymDetailSerializer, description="Gym profile details."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def get(self, request):
        gym_id = getattr(request, "gym_id", None) or request.query_params.get("gym_id")
        if not gym_id:
            raise DomainValidationError("An active Gym context token or 'gym_id' query parameter is required.")
        gym_overview = get_gym_overview(str(gym_id))
        if not gym_overview:
            raise ResourceNotFoundError("Gym not found.")
        check_gym_permission(request, gym_overview, required_scope="gym_profile:read")
        request._resolved_gym = gym_overview
        return Response(GymDetailSerializer(gym_overview).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Gym Profile & Multi-Location"],
        summary="Update Gym Overview Tab",
        description="""
### Summary
Updates core overview attributes: name, types (primary & secondary), description (min 120 chars), age restriction (1-99), gender requirements, and branding photos.

### Authorization
- Requires Gym Ownership or `gym_profile:edit` scope.
        """,
        parameters=[
            OpenApiParameter(name="gym_id", description="Optional Gym UUID", required=False, type=str)
        ],
        request=GymOverviewUpdateSerializer,
        responses={
            200: OpenApiResponse(response=GymDetailSerializer, description="Overview updated."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure (e.g. description under 120 chars)."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
        },
    )
    def patch(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")

        serializer = GymOverviewUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_gym = update_gym_overview(gym, **serializer.validated_data)
        return Response(GymDetailSerializer(updated_gym).data, status=status.HTTP_200_OK)


class GymLocationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Profile & Multi-Location"],
        summary="Get Gym Physical Location",
        description="Retrieves the primary map coordinates and address data.",
        parameters=[
            OpenApiParameter(name="gym_id", description="Optional Gym UUID", required=False, type=str)
        ],
        responses={
            200: OpenApiResponse(response=GymLocationSerializer, description="Location data."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Gym not found."),
        },
    )
    def get(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:read")
        loc = get_gym_location(str(gym.id))
        return Response(GymLocationSerializer(loc).data if loc else {}, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Gym Profile & Multi-Location"],
        summary="Update Gym Location & Map Coordinates",
        description="""
### Summary
Saves live map pinpoint coordinates (`latitude`, `longitude`) while maintaining custom edits to the address string.

### Authorization
- Requires Gym Ownership or `gym_profile:edit` scope.
        """,
        parameters=[
            OpenApiParameter(name="gym_id", description="Optional Gym UUID", required=False, type=str)
        ],
        request=GymLocationUpdateSerializer,
        responses={
            200: OpenApiResponse(response=GymLocationSerializer, description="Location updated."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
        },
    )
    def patch(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")

        serializer = GymLocationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        loc = update_gym_location(gym, **serializer.validated_data)
        return Response(GymLocationSerializer(loc).data, status=status.HTTP_200_OK)


class GymOpeningHoursView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Gym Profile & Multi-Location"],
        summary="Get Weekly Operating Hours",
        description="Retrieves the full 7-day schedule (Sunday=0 through Saturday=6).",
        parameters=[
            OpenApiParameter(name="gym_id", description="Optional Gym UUID", required=False, type=str)
        ],
        responses={
            200: OpenApiResponse(response=GymOpeningHoursItemSerializer(many=True), description="7-day operating schedule."),
        },
    )
    def get(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:read")
        hours = get_opening_hours(str(gym.id))
        return Response(GymOpeningHoursItemSerializer(hours, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Gym Profile & Multi-Location"],
        summary="Bulk Update Weekly Operating Hours",
        description="""
### Summary
Atomically updates the operating hours for all 7 days of the week.

### Business Rules
- `day_of_week` values range from 0 (Sunday) to 6 (Saturday).
- When `is_closed=False`, both `start_time` and `end_time` are required, and `start_time < end_time`.
- When `is_closed=True`, times are cleared automatically.
        """,
        parameters=[
            OpenApiParameter(name="gym_id", description="Optional Gym UUID", required=False, type=str)
        ],
        request=GymOpeningHoursBulkUpdateSerializer,
        responses={
            200: OpenApiResponse(response=GymOpeningHoursItemSerializer(many=True), description="Operating hours updated."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Time validation failure."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Permission denied."),
        },
        examples=[
            OpenApiExample(
                name="Bulk Hours Payload",
                value={
                    "hours": [
                        {"day_of_week": 0, "start_time": "08:00:00", "end_time": "18:00:00", "is_closed": False},
                        {"day_of_week": 1, "start_time": "06:00:00", "end_time": "22:00:00", "is_closed": False},
                        {"day_of_week": 2, "start_time": "06:00:00", "end_time": "22:00:00", "is_closed": False},
                        {"day_of_week": 3, "start_time": "06:00:00", "end_time": "22:00:00", "is_closed": False},
                        {"day_of_week": 4, "start_time": "06:00:00", "end_time": "22:00:00", "is_closed": False},
                        {"day_of_week": 5, "start_time": "06:00:00", "end_time": "21:00:00", "is_closed": False},
                        {"day_of_week": 6, "start_time": None, "end_time": None, "is_closed": True},
                    ]
                },
                request_only=True,
            )
        ],
    )
    def put(self, request):
        gym = resolve_gym_context(request)
        check_gym_permission(request, gym, required_scope="gym_profile:edit")

        serializer = GymOpeningHoursBulkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_records = bulk_update_opening_hours(gym, serializer.validated_data["hours"])
        return Response(GymOpeningHoursItemSerializer(updated_records, many=True).data, status=status.HTTP_200_OK)


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
        return Response(GymGalleryItemSerializer(items, many=True).data, status=status.HTTP_200_OK)

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
        return Response(GymGalleryItemSerializer(item).data, status=status.HTTP_201_CREATED)


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
