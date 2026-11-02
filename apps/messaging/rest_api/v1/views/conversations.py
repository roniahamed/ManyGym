from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.messaging.rest_api.v1.serializers import (
    ConversationCreateSerializer,
    ConversationListSerializer,
)
from apps.messaging.selectors import (
    get_conversation_by_id,
    list_conversations_for_entity,
)
from apps.messaging.services import initiate_conversation
from apps.messaging.rest_api.v1.views.base import resolve_gym_context


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
