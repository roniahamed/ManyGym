from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.gyms.models import Gym
from apps.messaging.rest_api.v1.serializers import (
    ConversationListSerializer,
    EncryptedMessageSerializer,
    MarkReadSerializer,
    SendMessageSerializer,
    ChatHistorySearchSerializer,
    MessageSearchIndexBatchSerializer,
)
from apps.messaging.selectors import (
    get_conversation_by_id,
    list_conversation_messages,
    search_chat_history,
)
from apps.messaging.services import (
    mark_conversation_as_read,
    send_encrypted_message,
    index_message_search_tokens,
)
from apps.messaging.rest_api.v1.views.base_views import resolve_gym_context
from common.enums import MessageSenderTypeEnum
from common.exceptions import DomainValidationError, ResourceNotFoundError


class ConversationMessagesView(APIView):
    """
    Lists encrypted messages or dispatches a new E2EE encrypted message payload.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Get Encrypted Message History",
        description="Retrieves chronological encrypted messages for the conversation.",
        parameters=[
            OpenApiParameter(name="conversation_id", description="UUID of the conversation", required=True, type=str, location=OpenApiParameter.PATH),
            OpenApiParameter(name="limit", description="Pagination limit for message history (max 100, default 50)", required=False, type=int),
            OpenApiParameter(name="before", description="Cursor (message UUID or ISO timestamp) to fetch older messages", required=False, type=str),
            OpenApiParameter(name="after", description="Cursor (message UUID or ISO timestamp) to fetch newer messages", required=False, type=str),
            OpenApiParameter(name="order", description="Sort order: 'asc' (default) or 'desc' (newest first)", required=False, type=str),
            OpenApiParameter(name="gym_id", description="Optional Gym context UUID", required=False, type=str),
        ],
        responses={200: EncryptedMessageSerializer(many=True)},
    )
    def get(self, request, conversation_id):
        gym = resolve_gym_context(request)
        limit_param = request.query_params.get("limit")
        limit = 50
        if limit_param is not None:
            try:
                parsed = int(limit_param)
                if parsed > 0:
                    limit = min(parsed, 100)
            except (ValueError, TypeError):
                limit = 50
        before = request.query_params.get("before")
        after = request.query_params.get("after")
        order = request.query_params.get("order", "asc")
        messages = list_conversation_messages(
            str(conversation_id),
            request.user,
            gym=gym,
            limit=limit,
            before=before,
            after=after,
            order=order,
        )
        serializer = EncryptedMessageSerializer(messages, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Messaging"],
        summary="Send Encrypted Message",
        description="Sends an E2EE encrypted message to the conversation with real-time broadcast.",
        parameters=[
            OpenApiParameter(name="conversation_id", description="UUID of the conversation", required=True, type=str, location=OpenApiParameter.PATH),
            OpenApiParameter(name="gym_id", description="Optional Gym context UUID", required=False, type=str),
        ],
        request=SendMessageSerializer,
        responses={201: EncryptedMessageSerializer},
    )
    def post(self, request, conversation_id):
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        gym = resolve_gym_context(request)
        conv = get_conversation_by_id(str(conversation_id), request.user, gym=gym, prefetch_participants=False)

        sender_gym = None
        if data.get("sender_type") == MessageSenderTypeEnum.GYM:
            sender_gym_id = data.get("sender_gym_id") or (gym.id if gym else None)
            if not sender_gym_id:
                raise DomainValidationError("sender_gym_id is required when sender_type is 'gym'.")
            try:
                sender_gym = Gym.objects.get(id=sender_gym_id)
            except Gym.DoesNotExist:
                raise ResourceNotFoundError("Sender gym not found.")

        msg = send_encrypted_message(
            conversation=conv,
            sender_user=request.user,
            sender_type=data.get("sender_type", MessageSenderTypeEnum.USER),
            ciphertext=data["ciphertext"],
            nonce=data["nonce"],
            ephemeral_public_key=data.get("ephemeral_public_key", ""),
            recipient_key_fingerprint=data.get("recipient_key_fingerprint", ""),
            sender_device_id=data.get("sender_device_id", ""),
            encrypted_keys=data.get("encrypted_keys", {}),
            sender_gym=sender_gym,
            search_tokens=data.get("search_tokens", []),
            shared_search_tokens=data.get("shared_search_tokens", []),
        )

        out_serializer = EncryptedMessageSerializer(msg)
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


class ConversationMarkReadView(APIView):
    """
    Marks messages in a conversation as read, resetting unread badges and broadcasting read receipts.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Mark Conversation Read",
        parameters=[
            OpenApiParameter(name="conversation_id", description="UUID of the conversation", required=True, type=str, location=OpenApiParameter.PATH),
        ],
        request=MarkReadSerializer,
        responses={200: OpenApiResponse(description="Read count confirmed")},
    )
    def post(self, request, conversation_id):
        serializer = MarkReadSerializer(data=request.data if isinstance(request.data, dict) else {})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        gym = resolve_gym_context(request)
        conv = get_conversation_by_id(str(conversation_id), request.user, gym=gym, prefetch_participants=False)

        up_to_message_id = data.get("up_to_message_id")
        updated_count = mark_conversation_as_read(
            conversation=conv,
            user=request.user,
            gym=gym,
            up_to_message_id=str(up_to_message_id) if up_to_message_id else None,
        )

        return Response(
            {
                "message": "Conversation marked as read.",
                "read_count": updated_count,
            },
            status=status.HTTP_200_OK,
        )


class ChatHistorySearchView(APIView):
    """
    WhatsApp-style zero-knowledge chat history search across all conversations.
    Matches blinded HMAC-SHA256 keyword tokens and returns conversations grouped with matching messages.
    """
    permission_classes = [IsAuthenticated]

    def _serialize_search_response(self, request, gym, search_result):
        serialized_groups = []
        for entry in search_result["results"]:
            conv_data = ConversationListSerializer(
                entry["conversation"],
                context={"request": request, "gym": gym},
            ).data
            matches_data = EncryptedMessageSerializer(entry["matches"], many=True).data
            serialized_groups.append(
                {
                    "conversation": conv_data,
                    "match_count": entry["match_count"],
                    "latest_match_at": entry["latest_match_at"],
                    "matches": matches_data,
                }
            )
        return {
            "total_conversations": search_result["total_conversations"],
            "total_matches": search_result["total_matches"],
            "results": serialized_groups,
        }

    @extend_schema(
        tags=["Messaging"],
        summary="Search E2EE Chat History (GET)",
        description=(
            "Searches across all accessible conversations using blinded HMAC-SHA256 keyword token(s) "
            "and returns matching chats grouped with their matched encrypted messages (WhatsApp-style)."
        ),
        parameters=[
            OpenApiParameter(name="token", description="Single blinded HMAC-SHA256 keyword token", required=False, type=str),
            OpenApiParameter(name="tokens", description="Comma-separated blinded HMAC-SHA256 keyword tokens", required=False, type=str),
            OpenApiParameter(name="match_mode", description="'all' (default) or 'any'", required=False, type=str),
            OpenApiParameter(name="conversation_id", description="Optional conversation UUID to search within", required=False, type=str),
            OpenApiParameter(name="gym_id", description="Optional Gym context UUID", required=False, type=str),
            OpenApiParameter(name="limit", description="Max conversations to return (default 20, max 50)", required=False, type=int),
            OpenApiParameter(name="matches_per_chat", description="Max matched messages per conversation (default 5, max 20)", required=False, type=int),
        ],
        responses={200: OpenApiResponse(description="Grouped chat search results.")},
    )
    def get(self, request):
        tokens = []
        single_token = request.query_params.get("token")
        if single_token:
            tokens.append(single_token)
        raw_tokens = request.query_params.getlist("tokens")
        for item in raw_tokens:
            for part in str(item).split(","):
                if part.strip():
                    tokens.append(part.strip())

        payload = {
            "tokens": tokens,
            "match_mode": request.query_params.get("match_mode", "all"),
            "conversation_id": request.query_params.get("conversation_id") or None,
            "gym_id": request.query_params.get("gym_id") or None,
        }
        for int_key, default_val in (("limit", 20), ("matches_per_chat", 5)):
            raw_val = request.query_params.get(int_key)
            if raw_val is not None:
                try:
                    payload[int_key] = int(raw_val)
                except (ValueError, TypeError):
                    raise DomainValidationError(f"Invalid integer value for '{int_key}'.")
            else:
                payload[int_key] = default_val

        serializer = ChatHistorySearchSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        gym = resolve_gym_context(request)
        result = search_chat_history(
            user=request.user,
            tokens=data["tokens"],
            gym=gym,
            conversation_id=str(data["conversation_id"]) if data.get("conversation_id") else None,
            match_mode=data.get("match_mode", "all"),
            limit=data.get("limit", 20),
            matches_per_chat=data.get("matches_per_chat", 5),
        )
        return Response(self._serialize_search_response(request, gym, result), status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Messaging"],
        summary="Search E2EE Chat History (POST)",
        description=(
            "Searches across all accessible conversations using blinded HMAC-SHA256 keyword token(s) "
            "and returns matching chats grouped with their matched encrypted messages (WhatsApp-style)."
        ),
        request=ChatHistorySearchSerializer,
        responses={200: OpenApiResponse(description="Grouped chat search results.")},
    )
    def post(self, request):
        serializer = ChatHistorySearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        gym = resolve_gym_context(request)
        result = search_chat_history(
            user=request.user,
            tokens=data["tokens"],
            gym=gym,
            conversation_id=str(data["conversation_id"]) if data.get("conversation_id") else None,
            match_mode=data.get("match_mode", "all"),
            limit=data.get("limit", 20),
            matches_per_chat=data.get("matches_per_chat", 5),
        )
        return Response(self._serialize_search_response(request, gym, result), status=status.HTTP_200_OK)


class ChatSearchIndexView(APIView):
    """
    Batch-indexes blinded HMAC-SHA256 search tokens for messages decrypted on the user's client device
    (including received messages and restored history on new devices).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Index Blinded Search Tokens for Messages",
        request=MessageSearchIndexBatchSerializer,
        responses={200: OpenApiResponse(description="Tokens indexed successfully.")},
    )
    def post(self, request):
        serializer = MessageSearchIndexBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        gym = resolve_gym_context(request)
        indexed_count = index_message_search_tokens(
            user=request.user,
            items=data["items"],
            gym=gym,
        )
        return Response(
            {
                "message": "Search tokens indexed successfully.",
                "indexed_count": indexed_count,
            },
            status=status.HTTP_200_OK,
        )
