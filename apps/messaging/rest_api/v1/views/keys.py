from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.gyms.models import Gym
from apps.messaging.rest_api.v1.serializers import (
    GymDeviceKeyRegisterSerializer,
    PublicKeyBundleSerializer,
    UserDeviceKeyRegisterSerializer,
)
from apps.messaging.selectors import (
    get_gym_public_key_bundle,
    get_user_public_key_bundle,
)
from apps.messaging.services import (
    register_gym_device_key,
    register_user_device_key,
)
from common.exceptions import ResourceNotFoundError


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
