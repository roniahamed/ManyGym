from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.gyms.rest_api.v1.serializers.geo_serializers import GymSearchItemSerializer
from apps.posts.rest_api.v1.serializers import GymPostListSerializer
from apps.search.rest_api.v1.serializers import (
    AmenitySearchItemSerializer,
    CentralSearchAllResponseSerializer,
    CentralSearchQuerySerializer,
    MembershipPlanSearchItemSerializer,
    PersonSearchItemSerializer,
)
from apps.search.selectors import (
    SEARCH_FILTER_ALL,
    SEARCH_FILTER_AMENITY,
    SEARCH_FILTER_GYM,
    SEARCH_FILTER_PEOPLE,
    SEARCH_FILTER_PLAN,
    SEARCH_FILTER_POST,
    execute_central_search,
)
from common.pagination import StandardResultsSetPagination
from common.serializers import ErrorDetailSerializer

_FILTER_SERIALIZER_MAP = {
    SEARCH_FILTER_GYM: GymSearchItemSerializer,
    SEARCH_FILTER_PEOPLE: PersonSearchItemSerializer,
    SEARCH_FILTER_POST: GymPostListSerializer,
    SEARCH_FILTER_PLAN: MembershipPlanSearchItemSerializer,
    SEARCH_FILTER_AMENITY: AmenitySearchItemSerializer,
}


class CentralSearchPagination(StandardResultsSetPagination):
    """
    Standard pagination enriched with search metadata and per-tab counts
    for the dedicated search result page.
    """

    def get_paginated_response(self, data, *, query: str = "", search_filter: str = "", counts: dict | None = None):
        return Response({
            "query": query,
            "filter": search_filter,
            "counts": counts or {},
            "count": self.page.paginator.count,
            "total_pages": self.page.paginator.num_pages,
            "current_page": self.page.number,
            "next": self.get_next_link(),
            "previous": self.get_previous_link(),
            "results": data,
        })


class CentralSearchView(APIView):
    """
    Central search endpoint serving both the global search bar preview (filter='all')
    and the dedicated paginated search result page (filter='gym'|'people'|'post'|'plan'|'amenity').
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Central Search"],
        summary="Central Search (Gyms, People, Posts, Plans & Amenities)",
        description=(
            "Unified authenticated search across Gyms, People, Community Posts, Active Membership Plans, "
            "and Gym Amenities.\n\n"
            "- Use `filter=all` (default) to receive grouped top results (controlled by `limit`, default 5) "
            "plus live per-category `counts` for the search bar dropdown and 'All' tab.\n"
            "- Use `filter=gym|people|post|plan|amenity` to receive paginated results (`page`, `page_size`) "
            "alongside live `counts` for the dedicated search result page tabs.\n"
            "- Enforces all visibility, privacy, age-restriction, and mutual blocklist rules."
        ),
        parameters=[CentralSearchQuerySerializer],
        responses={
            200: OpenApiResponse(
                response=CentralSearchAllResponseSerializer,
                description="Grouped results (when filter='all') or paginated category results with tab counts.",
            ),
            400: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Invalid filter value, malformed coordinates, or invalid query parameter.",
            ),
            401: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Authentication credentials were not provided or are invalid.",
            ),
        },
    )
    def get(self, request):
        query_serializer = CentralSearchQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        params = query_serializer.validated_data

        outcome = execute_central_search(
            requesting_user=request.user,
            params=params,
        )

        social_ctx = outcome["social_ctx"]
        request._user_social_context = social_ctx
        serializer_context = {"request": request, **social_ctx}
        search_filter = outcome["filter"]

        if search_filter == SEARCH_FILTER_ALL:
            grouped = outcome["results"]
            payload = {
                "query": outcome["query"],
                "filter": search_filter,
                "counts": outcome["counts"],
                "results": {
                    "gyms": GymSearchItemSerializer(grouped["gyms"], many=True, context=serializer_context).data,
                    "people": PersonSearchItemSerializer(grouped["people"], many=True, context=serializer_context).data,
                    "posts": GymPostListSerializer(grouped["posts"], many=True, context=serializer_context).data,
                    "membership_plans": MembershipPlanSearchItemSerializer(
                        grouped["membership_plans"], many=True, context=serializer_context
                    ).data,
                    "amenities": AmenitySearchItemSerializer(
                        grouped["amenities"], many=True, context=serializer_context
                    ).data,
                },
            }
            return Response(payload, status=status.HTTP_200_OK)

        item_serializer_cls = _FILTER_SERIALIZER_MAP[search_filter]
        paginator = CentralSearchPagination()
        page = paginator.paginate_queryset(outcome["target_results"], request, view=self)
        serialized = item_serializer_cls(page, many=True, context=serializer_context).data
        return paginator.get_paginated_response(
            serialized,
            query=outcome["query"],
            search_filter=search_filter,
            counts=outcome["counts"],
        )
