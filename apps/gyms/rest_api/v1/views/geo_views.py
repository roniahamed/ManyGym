from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter, OpenApiExample

from apps.gyms.rest_api.v1.serializers.geo_serializers import (
    GymSearchQuerySerializer,
    GymSearchItemSerializer,
    GymPublicDetailSerializer,
)
from apps.gyms.selectors.geo_selectors import (
    search_nearby_gyms,
    get_gym_public_details,
)
from common.pagination import StandardResultsSetPagination
from common.exceptions import ResourceNotFoundError
from common.serializers import ErrorDetailSerializer


class GymNearbySearchView(APIView):
    """
    Public discovery endpoint for searching gyms:
    1. By Live Location coordinates (using browser Geolocation API with user consent) within a configurable radius (defaults to 20 km).
       - Uses Redis Geospatial index for sub-millisecond retrieval.
       - Falls back gracefully to PostgreSQL / PostGIS Haversine distance calculations.
       - Returns results ordered by distance ascending with exact `distance_km`.
    2. By City name (e.g. Dhaka, New York, London).
    3. Filterable by Gym Category (e.g. strength_bodybuilding_gym, yoga_pilates_studio).
    4. Searchable by keyword matching name, bio, address, or city.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Nearby Gym Discovery & Search"],
        summary="Search Nearby Gyms (Live Location or City)",
        description="""
### Summary
Allows prospective gymgoers and members to discover gyms based on:
1. **Live Location Radius Search**: Provide `latitude` and `longitude` (obtained via browser/mobile live location sharing after user consent). By default searches within a **20 km radius** (customizable via `radius` parameter). Results are sorted ascending by distance from the user.
2. **City Search**: Provide `city` name (case-insensitive search) when location permission is not granted or user prefers manual city selection.
3. **Category Filter**: Filter gyms by primary/secondary type (`category`), e.g. `strength_bodybuilding_gym`, `functional_fitness_gym`, `yoga_pilates_studio`.
4. **Keyword Search**: Free-text query (`search` or `q`) matching gym name, description, address, or city.

### Architecture
- **Ultra-fast Geo Index (Redis GEO)**: Proximity queries are evaluated against Redis geospatial index (`GEOSEARCH`) in <1ms.
- **Resilient Fallback (PostGIS / Haversine)**: Automatically falls back to PostgreSQL spherical Haversine / PostGIS formulas on cache miss and warms up Redis.
- **Privacy & Safety**: Deactivated, unpublished, and soft-deleted gyms are automatically excluded. Gyms that have blocked the requesting user are hidden.
        """,
        parameters=[
            OpenApiParameter(
                name="latitude",
                description="Live user latitude from browser geolocation (-90.0 to 90.0). Required together with longitude.",
                required=False,
                type=float,
            ),
            OpenApiParameter(
                name="longitude",
                description="Live user longitude from browser geolocation (-180.0 to 180.0). Required together with latitude.",
                required=False,
                type=float,
            ),
            OpenApiParameter(
                name="radius",
                description="Search radius in kilometers (default: 20 km, min: 0.1, max: 500.0).",
                required=False,
                type=float,
            ),
            OpenApiParameter(
                name="category",
                description="Gym category choice (e.g. general_fitness_gym, strength_bodybuilding_gym, functional_fitness_gym, yoga_pilates_studio).",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="city",
                description="Filter by city name (e.g. Dhaka, New York). Used when user opts for city selection.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="search",
                description="Keyword search matching gym name, address, bio, or city.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="page",
                description="Page number for pagination (default: 1).",
                required=False,
                type=int,
            ),
            OpenApiParameter(
                name="page_size",
                description="Number of results per page (default: 20, max: 100).",
                required=False,
                type=int,
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=GymSearchItemSerializer,
                description="Paginated list of matching gyms.",
            ),
            400: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Validation failure (e.g. latitude provided without longitude, or invalid coordinates).",
            ),
        },
    )
    def get(self, request):
        serializer = GymSearchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data

        results = search_nearby_gyms(
            latitude=validated.get("latitude"),
            longitude=validated.get("longitude"),
            radius_km=validated.get("radius", 20.0),
            category=validated.get("category"),
            city=validated.get("city"),
            search=validated.get("search"),
            requesting_user=request.user if request.user.is_authenticated else None,
        )

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(results, request, view=self)
        item_serializer = GymSearchItemSerializer(
            page,
            many=True,
            context={"request": request},
        )
        return paginator.get_paginated_response(item_serializer.data)


class GymPublicDetailView(APIView):
    """
    Publicly accessible gym detail endpoint.
    Returns complete profile, multi-location addresses, 7-day operating hours,
    amenities breakdown, gallery items, active membership plans, and follower counts.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Nearby Gym Discovery & Search"],
        summary="Get Public Gym Details",
        description="""
### Summary
Retrieves comprehensive public view for a gym workspace:
- Core overview and branding images.
- Primary location and all branch addresses with coordinates.
- Full 7-day schedule with live `is_open_now` indicator based on the gym's timezone.
- Categorized amenities (complimentary vs paid).
- Media gallery assets with WebP optimized and thumbnail variants.
- Active membership plans and pricing tiers.
- Follower and member counts, including `is_following` flag for authenticated users.
        """,
        responses={
            200: OpenApiResponse(
                response=GymPublicDetailSerializer,
                description="Gym details retrieved successfully.",
            ),
            404: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Gym not found or inactive.",
            ),
        },
    )
    def get(self, request, gym_id):
        details = get_gym_public_details(
            gym_id=gym_id,
            requesting_user=request.user if request.user.is_authenticated else None,
        )
        if not details:
            raise ResourceNotFoundError("Gym not found or currently unavailable.")

        serializer = GymPublicDetailSerializer(
            details,
            context={"request": request},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

