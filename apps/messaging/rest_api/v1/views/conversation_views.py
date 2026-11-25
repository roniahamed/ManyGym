from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.messaging.rest_api.v1.serializers import (
    ConversationCreateSerializer,
    ConversationListSerializer,
    PeopleSearchResultSerializer,
)
from apps.messaging.selectors import (
    get_conversation_by_id,
    list_conversations_for_entity,
    search_people_to_message,
)
from apps.messaging.services import initiate_conversation
from apps.messaging.rest_api.v1.views.base_views import resolve_gym_context


class ConversationListCreateView(APIView):
    """
    Lists existing conversations or initiates a new encrypted conversation channel.
    Supports:
    - User to User (user_to_user)
    - User to Gym (user_to_gym)
    - Gym to User (gym_to_user)
    - Gym to Gym (gym_to_gym)
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="List Conversations",
        description="Lists active conversations for the authenticated user or active gym context with zero N+1 queries.",
        parameters=[
            OpenApiParameter(name="gym_id", description="Optional Gym context UUID", required=False, type=str),
            OpenApiParameter(name="limit", description="Optional pagination limit (1-100)", required=False, type=int),
        ],
        responses={200: ConversationListSerializer(many=True)},
    )
    def get(self, request):
        gym = resolve_gym_context(request)
        limit_param = request.query_params.get("limit")
        limit = None
        if limit_param is not None:
            try:
                parsed = int(limit_param)
                if parsed > 0:
                    limit = min(parsed, 100)
            except (ValueError, TypeError):
                limit = None

        conversations = list_conversations_for_entity(request.user, gym=gym, limit=limit)
        serializer = ConversationListSerializer(
            conversations,
            many=True,
            context={"request": request, "gym": gym},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Messaging"],
        summary="Create / Get Conversation",
        description="Initiates or retrieves an encrypted conversation across supported channel types.",
        request=ConversationCreateSerializer,
        responses={201: ConversationListSerializer},
    )
    def post(self, request):
        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        gym = resolve_gym_context(request)
        conversation = initiate_conversation(
            initiator_user=request.user,
            validated_data=serializer.validated_data,
            gym_context=gym,
        )

        out_serializer = ConversationListSerializer(
            conversation,
            context={"request": request, "gym": gym},
        )
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


class ConversationDetailView(APIView):
    """
    Retrieves full details for a conversation.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Get Conversation Detail",
        parameters=[
            OpenApiParameter(name="conversation_id", description="UUID of the conversation", required=True, type=str, location=OpenApiParameter.PATH),
            OpenApiParameter(name="gym_id", description="Optional Gym context UUID", required=False, type=str),
        ],
        responses={200: ConversationListSerializer},
    )
    def get(self, request, conversation_id):
        gym = resolve_gym_context(request)
        conv = get_conversation_by_id(str(conversation_id), request.user, gym=gym, prefetch_participants=True)
        serializer = ConversationListSerializer(conv, context={"request": request, "gym": gym})
        return Response(serializer.data, status=status.HTTP_200_OK)


class FindPeopleToMessageView(APIView):
    """
    Searches people to message strictly from the authenticated user's Follows + Followers.
    Designed to power the inbox 'Find people to message' modal/offcanvas without a dedicated page.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Find People to Message (Follows + Followers Only)",
        description=(
            "Searches users strictly within the authenticated user's Follows and Followers lists "
            "for starting or jumping into a direct conversation from an offcanvas/modal."
        ),
        parameters=[
            OpenApiParameter(name="q", description="Search query matching name or email.", required=False, type=str),
            OpenApiParameter(name="limit", description="Max results to return (default 20, max 50).", required=False, type=int),
        ],
        responses={200: PeopleSearchResultSerializer(many=True)},
    )
    def get(self, request):
        query = request.query_params.get("q")
        if query is None:
            query = request.query_params.get("search")

        limit_param = request.query_params.get("limit")
        limit = 20
        if limit_param is not None:
            try:
                parsed = int(limit_param)
                if parsed > 0:
                    limit = min(parsed, 50)
            except (ValueError, TypeError):
                limit = 20

        people = search_people_to_message(request.user, query=query, limit=limit)
        serializer = PeopleSearchResultSerializer(people, many=True)
        return Response(
            {
                "count": len(serializer.data),
                "results": serializer.data,
            },
            status=status.HTTP_200_OK,
        )
