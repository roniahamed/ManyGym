import uuid
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from apps.users.models import User
from apps.gyms.models import Gym
from apps.messaging.services import (
    register_user_device_key,
    register_gym_device_key,
    get_or_create_user_to_user_conversation,
    get_or_create_user_to_gym_conversation,
    get_or_create_gym_to_gym_conversation,
    send_encrypted_message,
    mark_conversation_as_read,
)
from apps.messaging.selectors import (
    get_user_public_key_bundle,
    get_gym_public_key_bundle,
    list_conversations_for_entity,
    get_conversation_by_id,
    list_conversation_messages,
    resolve_user_instance,
)
from apps.messaging.rest_api.v1.serializers import (
    UserDeviceKeyRegisterSerializer,
    GymDeviceKeyRegisterSerializer,
    PublicKeyBundleSerializer,
    ConversationListSerializer,
    ConversationCreateSerializer,
    SendMessageSerializer,
    EncryptedMessageSerializer,
    MarkReadSerializer,
)
from common.enums import ConversationTypeEnum, MessageSenderTypeEnum
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)


def resolve_gym_context(request) -> Gym | None:
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
        summary="Register User Device E2EE Key Bundle",
        description="Registers public Identity Key, Signed Prekey, and One-Time Prekeys for client-side E2EE.",
        request=UserDeviceKeyRegisterSerializer,
        responses={200: UserDeviceKeyRegisterSerializer},
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
        summary="Register Gym E2EE Key Bundle",
        description="Registers public cryptographic keys for a Gym entity to enable encrypted messaging with users and gyms.",
        request=GymDeviceKeyRegisterSerializer,
        responses={200: GymDeviceKeyRegisterSerializer},
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
        summary="Get User E2EE Public Key Bundle",
        description="Fetches public keys for recipient user's registered devices.",
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
        summary="Get Gym E2EE Public Key Bundle",
        description="Fetches public keys for recipient gym.",
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
    - Gym to Gym (gym_to_gym)
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="List Conversations",
        description="Lists active conversations for the authenticated user or active gym context.",
        parameters=[
            OpenApiParameter(name="gym_id", description="Optional Gym context UUID", required=False, type=str),
        ],
        responses={200: ConversationListSerializer(many=True)},
    )
    def get(self, request):
        gym = resolve_gym_context(request)
        conversations = list_conversations_for_entity(request.user, gym=gym)
        serializer = ConversationListSerializer(
            conversations,
            many=True,
            context={"request": request, "gym": gym},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Create / Get Conversation",
        description="Initiates or retrieves a conversation across supported channel types.",
        request=ConversationCreateSerializer,
        responses={200: ConversationListSerializer, 201: ConversationListSerializer},
    )
    def post(self, request):
        serializer = ConversationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        source_gym_id = data.get("source_gym_id") or getattr(resolve_gym_context(request), "id", None)
        target_user_id = data.get("target_user_id")
        target_gym_id = data.get("target_gym_id")
        conv_type = data.get("conversation_type", "")

        # Auto-detect conversation_type if omitted by client
        if not conv_type:
            if source_gym_id and target_gym_id:
                conv_type = ConversationTypeEnum.GYM_TO_GYM
            elif (source_gym_id and target_user_id) or target_gym_id:
                conv_type = ConversationTypeEnum.USER_TO_GYM
            elif target_user_id:
                conv_type = ConversationTypeEnum.USER_TO_USER
            else:
                raise DomainValidationError("Please provide target_user_id or target_gym_id to start a conversation.")

        if conv_type == ConversationTypeEnum.USER_TO_USER:
            target_user_id = data.get("target_user_id")
            if not target_user_id:
                raise DomainValidationError("target_user_id is required for User to User messaging.")
            target_user = resolve_user_instance(target_user_id)
            conversation = get_or_create_user_to_user_conversation(request.user, target_user)

        elif conv_type == ConversationTypeEnum.USER_TO_GYM:
            source_gym_id = data.get("source_gym_id") or getattr(resolve_gym_context(request), "id", None)
            target_user_id = data.get("target_user_id")
            target_gym_id = data.get("target_gym_id")

            if source_gym_id and target_user_id:
                # Gym initiating chat with User (Gym -> User)
                try:
                    source_gym = Gym.objects.get(id=source_gym_id)
                except Gym.DoesNotExist:
                    raise ResourceNotFoundError("Gym not found.")
                target_user = resolve_user_instance(target_user_id)

                conversation = get_or_create_user_to_gym_conversation(
                    user=target_user,
                    gym=source_gym,
                    initiated_by="gym",
                    initiator_user=request.user,
                )
            elif target_gym_id:
                # User initiating chat with Gym (User -> Gym)
                try:
                    target_gym = Gym.objects.get(id=target_gym_id)
                except Gym.DoesNotExist:
                    raise ResourceNotFoundError("Target gym not found.")

                conversation = get_or_create_user_to_gym_conversation(
                    user=request.user,
                    gym=target_gym,
                    initiated_by="user",
                    initiator_user=request.user,
                )
            else:
                raise DomainValidationError(
                    "Either 'target_gym_id' (for User -> Gym) or 'source_gym_id' with 'target_user_id' (for Gym -> User) must be provided."
                )

        elif conv_type == ConversationTypeEnum.GYM_TO_GYM:
            source_gym_id = data.get("source_gym_id")
            target_gym_id = data.get("target_gym_id")
            if not source_gym_id or not target_gym_id:
                raise DomainValidationError("source_gym_id and target_gym_id are required for Gym to Gym messaging.")

            try:
                source_gym = Gym.objects.get(id=source_gym_id)
                target_gym = Gym.objects.get(id=target_gym_id)
            except Gym.DoesNotExist:
                raise ResourceNotFoundError("Gym not found.")

            conversation = get_or_create_gym_to_gym_conversation(request.user, source_gym, target_gym)

        else:
            raise DomainValidationError(f"Unsupported conversation type: {conv_type}")

        out_serializer = ConversationListSerializer(
            conversation,
            context={"request": request, "gym": resolve_gym_context(request)},
        )
        return Response(out_serializer.data, status=status.HTTP_201_CREATED)


class ConversationDetailView(APIView):
    """
    Retrieves full details for a conversation.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get Conversation Detail",
        responses={200: ConversationListSerializer},
    )
    def get(self, request, conversation_id):
        gym = resolve_gym_context(request)
        conv = get_conversation_by_id(str(conversation_id), request.user, gym=gym)
        serializer = ConversationListSerializer(conv, context={"request": request, "gym": gym})
        return Response(serializer.data, status=status.HTTP_200_OK)


class ConversationMessagesView(APIView):
    """
    Lists encrypted messages or dispatches a new E2EE encrypted message payload.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get Encrypted Message History",
        description="Retrieves chronological encrypted messages for the conversation.",
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
        summary="Send Encrypted Message",
        description="Sends an E2EE encrypted message to the conversation with real-time broadcast.",
        request=SendMessageSerializer,
        responses={201: EncryptedMessageSerializer},
    )
    def post(self, request, conversation_id):
        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        gym = resolve_gym_context(request)
        conv = get_conversation_by_id(str(conversation_id), request.user, gym=gym)

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
        summary="Mark Conversation Read",
        request=MarkReadSerializer,
        responses={200: OpenApiResponse(description="Read count confirmed")},
    )
    def post(self, request, conversation_id):
        serializer = MarkReadSerializer(data=request.data if isinstance(request.data, dict) else {})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        gym = resolve_gym_context(request)
        conv = get_conversation_by_id(str(conversation_id), request.user, gym=gym)

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
