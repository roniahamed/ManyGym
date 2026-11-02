"""
API Views for End-to-End Encrypted (E2EE) Messaging.
Adheres to thin-view architecture: authentication, input validation, service/selector delegation, and response serialization.
"""

from typing import Optional
import uuid

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.gyms.models import Gym
from apps.messaging.rest_api.v1.serializers import (
    ConversationCreateSerializer,
    ConversationListSerializer,
    EncryptedMessageSerializer,
    GymDeviceKeyRegisterSerializer,
    MarkReadSerializer,
    PublicKeyBundleSerializer,
    SendMessageSerializer,
    UserDeviceKeyRegisterSerializer,
)
from apps.messaging.selectors import (
    get_conversation_by_id,
    get_gym_public_key_bundle,
    get_user_public_key_bundle,
    list_conversation_messages,
    list_conversations_for_entity,
)
from apps.messaging.services import (
    initiate_conversation,
    mark_conversation_as_read,
    register_gym_device_key,
    register_user_device_key,
    send_encrypted_message,
)
from common.enums import MessageSenderTypeEnum
from common.exceptions import DomainValidationError, ResourceNotFoundError


def resolve_gym_context(request) -> Optional[Gym]:
    """Helper to determine target gym from gym context header, query parameter, or request body."""
    gym_id = (
        request.query_params.get("gym_id")
        or getattr(request, "gym_id", None)
        or (request.data.get("gym_id") if isinstance(request.data, dict) else None)
    )
    if not gym_id:
        return None
    try:
        uuid_obj = uuid.UUID(str(gym_id))
        return Gym.objects.filter(id=uuid_obj).first()
    except (ValueError, TypeError, AttributeError):
        return None


class UserDeviceKeyRegisterView(APIView):
    """
    Registers or updates the E2EE public cryptographic key bundle for the authenticated user's device.
    Private keys must remain stored securely on the user's client device.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Register User Device E2EE Key Bundle",
        description="Registers public Identity Key, Signed Prekey, and One-Time Prekeys for client-side E2EE.",
        request=UserDeviceKeyRegisterSerializer,
        responses={200: OpenApiResponse(description="Device E2EE keys registered successfully.")},
    )
    def post(self, request):
        serializer = UserDeviceKeyRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        key_obj = register_user_device_key(
            user=request.user,
            device_id=serializer.validated_data["device_id"],
            identity_key=serializer.validated_data["identity_key"],
            signed_prekey=serializer.validated_data["signed_prekey"],
            signed_prekey_signature=serializer.validated_data.get("signed_prekey_signature", ""),
            one_time_prekeys=serializer.validated_data.get("one_time_prekeys", []),
            device_name=serializer.validated_data.get("device_name", ""),
        )

        return Response(
            {
                "message": "Device E2EE keys registered successfully.",
                "device_id": key_obj.device_id,
                "algorithm": key_obj.algorithm,
                "is_active": key_obj.is_active,
            },
            status=status.HTTP_200_OK,
        )


class GymDeviceKeyRegisterView(APIView):
    """
    Registers or updates the E2EE public cryptographic key bundle for a Gym entity.
    Requires gym owner or staff authorization with messaging scopes.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Register Gym E2EE Key Bundle",
        description="Registers public cryptographic keys for a Gym entity to enable encrypted messaging with users and gyms.",
        request=GymDeviceKeyRegisterSerializer,
        responses={200: OpenApiResponse(description="Gym E2EE keys registered successfully.")},
    )
    def post(self, request):
        serializer = GymDeviceKeyRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            gym = Gym.objects.get(id=serializer.validated_data["gym_id"])
        except Gym.DoesNotExist:
            raise ResourceNotFoundError("Gym not found.")

        key_obj = register_gym_device_key(
            gym=gym,
            user=request.user,
            device_id=serializer.validated_data["device_id"],
            identity_key=serializer.validated_data["identity_key"],
            signed_prekey=serializer.validated_data["signed_prekey"],
            signed_prekey_signature=serializer.validated_data.get("signed_prekey_signature", ""),
            one_time_prekeys=serializer.validated_data.get("one_time_prekeys", []),
            device_name=serializer.validated_data.get("device_name", ""),
        )

        return Response(
            {
                "message": "Gym E2EE keys registered successfully.",
                "gym_id": str(gym.id),
                "device_id": key_obj.device_id,
                "is_active": key_obj.is_active,
            },
            status=status.HTTP_200_OK,
        )


class UserPublicKeyBundleView(APIView):
    """
    Retrieves the public key bundle of all active devices for a recipient user.
    Used by clients to perform X25519 / Triple Diffie-Hellman handshakes before message transmission.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Get User E2EE Public Key Bundle",
        description="Fetches public keys for recipient user's registered devices.",
        parameters=[
            OpenApiParameter(name="user_id", description="Account UUID or Profile UUID of recipient user", required=True, type=str, location=OpenApiParameter.PATH),
        ],
        responses={200: PublicKeyBundleSerializer(many=True)},
    )
    def get(self, request, user_id):
        bundles = get_user_public_key_bundle(str(user_id))
        return Response({"user_id": str(user_id), "devices": bundles}, status=status.HTTP_200_OK)


class GymPublicKeyBundleView(APIView):
    """
    Retrieves the public key bundle for a recipient Gym entity.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Get Gym E2EE Public Key Bundle",
        description="Fetches public keys for recipient gym.",
        parameters=[
            OpenApiParameter(name="gym_id", description="UUID of recipient Gym entity", required=True, type=str, location=OpenApiParameter.PATH),
        ],
        responses={200: PublicKeyBundleSerializer(many=True)},
    )
    def get(self, request, gym_id):
        bundles = get_gym_public_key_bundle(str(gym_id))
        return Response({"gym_id": str(gym_id), "devices": bundles}, status=status.HTTP_200_OK)


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
