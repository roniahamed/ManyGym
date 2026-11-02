from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.gyms.models import Gym
from apps.messaging.rest_api.v1.serializers import (
    EncryptedMessageSerializer,
    MarkReadSerializer,
    SendMessageSerializer,
)
from apps.messaging.selectors import (
    get_conversation_by_id,
    list_conversation_messages,
)
from apps.messaging.services import (
    mark_conversation_as_read,
    send_encrypted_message,
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
        messages = list_conversation_messages(str(conversation_id), request.user, gym=gym, limit=limit)
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
