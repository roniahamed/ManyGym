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
    UserE2EEBackupSetSerializer,
    UserE2EEBackupRestoreSerializer,
    UserE2EEBackupChangeCodeSerializer,
)
from apps.messaging.selectors import (
    get_gym_public_key_bundle,
    get_user_public_key_bundle,
    get_user_e2ee_backup_public_key,
    get_user_e2ee_backup_status,
    get_user_e2ee_backup_for_fetch,
)
from apps.messaging.services import (
    register_gym_device_key,
    register_user_device_key,
    set_user_e2ee_backup,
    restore_user_e2ee_backup,
    change_user_e2ee_backup_secret,
    delete_user_e2ee_backup,
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
        backup_key = get_user_e2ee_backup_public_key(str(user_id))
        return Response(
            {
                "user_id": str(user_id),
                "devices": bundles,
                "backup_key": backup_key,
            },
            status=status.HTTP_200_OK,
        )


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


class UserE2EEBackupStatusView(APIView):
    """
    Returns whether the user has a Messenger-style PIN/password E2EE backup configured,
    along with KDF parameters and brute-force lockout status.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Get E2EE Backup Status",
        description="Checks whether a Messenger-style PIN/password E2EE key backup exists and returns KDF parameters.",
        responses={200: OpenApiResponse(description="Backup status retrieved.")},
    )
    def get(self, request):
        status_data = get_user_e2ee_backup_status(request.user)
        return Response(status_data, status=status.HTTP_200_OK)


class UserE2EEBackupView(APIView):
    """
    Manages the user's Messenger-style PIN/password-protected encrypted E2EE key backup.
    Allows setting, updating, fetching (for client-side restore), and deleting the backup.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Fetch E2EE Backup Metadata / Bundle",
        description=(
            "Fetches the user's E2EE backup parameters. If auth_proof gating is enabled, "
            "the encrypted_key_bundle is withheld until POST /keys/backup/restore/ verifies the PIN/password."
        ),
        responses={200: OpenApiResponse(description="E2EE backup fetched.")},
    )
    def get(self, request):
        backup = get_user_e2ee_backup_for_fetch(request.user)
        payload = {
            "backup_public_key": backup.backup_public_key,
            "backup_key_fingerprint": backup.backup_key_fingerprint,
            "salt": backup.salt,
            "kdf_algorithm": backup.kdf_algorithm,
            "kdf_iterations": backup.kdf_iterations,
            "cipher_algorithm": backup.cipher_algorithm,
            "secret_type": backup.secret_type,
            "pin_length": backup.pin_length,
            "key_version": backup.key_version,
            "requires_auth_proof": bool(backup.verifier_hash),
            "has_recovery_bundle": bool(backup.recovery_encrypted_bundle),
            "failed_attempts": backup.failed_attempts,
            "max_attempts": backup.max_attempts,
            "remaining_attempts": max(0, backup.max_attempts - backup.failed_attempts),
            "last_restored_at": backup.last_restored_at,
        }
        # Only expose encrypted_key_bundle directly on GET when no server-side auth_proof gate is configured
        if not backup.verifier_hash:
            payload["encrypted_key_bundle"] = backup.encrypted_key_bundle
            payload["nonce"] = backup.nonce
        return Response(payload, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Messaging"],
        summary="Set / Update Messenger-style 5-Digit E2EE Recovery Code",
        description="Configures a 5-digit numeric recovery code (or client-encrypted bundle) for cross-device E2EE message recovery.",
        request=UserE2EEBackupSetSerializer,
        responses={200: OpenApiResponse(description="E2EE backup saved successfully.")},
    )
    def post(self, request):
        serializer = UserE2EEBackupSetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        backup = set_user_e2ee_backup(
            user=request.user,
            backup_public_key=data.get("backup_public_key", ""),
            encrypted_key_bundle=data.get("encrypted_key_bundle", ""),
            nonce=data.get("nonce", ""),
            salt=data.get("salt", ""),
            kdf_algorithm=data.get("kdf_algorithm", "pbkdf2_sha256"),
            kdf_iterations=data.get("kdf_iterations", 310000),
            cipher_algorithm=data.get("cipher_algorithm", "chacha20_poly1305"),
            secret_type=data.get("secret_type", "pin"),
            auth_proof=data.get("auth_proof", ""),
            recovery_code=data.get("recovery_code", ""),
            pin_length=data.get("pin_length", 5),
            recovery_encrypted_bundle=data.get("recovery_encrypted_bundle", ""),
            recovery_nonce=data.get("recovery_nonce", ""),
            recovery_salt=data.get("recovery_salt", ""),
            max_attempts=data.get("max_attempts", 10),
        )
        return Response(
            {
                "message": "E2EE key backup configured successfully.",
                "backup_public_key": backup.backup_public_key,
                "backup_key_fingerprint": backup.backup_key_fingerprint,
                "secret_type": backup.secret_type,
                "pin_length": backup.pin_length,
                "key_version": backup.key_version,
                "requires_auth_proof": bool(backup.verifier_hash),
                "has_recovery_bundle": bool(backup.recovery_encrypted_bundle),
                "is_active": backup.is_active,
            },
            status=status.HTTP_200_OK,
        )

    def put(self, request):
        return self.post(request)

    @extend_schema(
        tags=["Messaging"],
        summary="Delete E2EE Backup",
        description="Deletes the authenticated user's E2EE key backup.",
        responses={200: OpenApiResponse(description="E2EE backup deleted.")},
    )
    def delete(self, request):
        delete_user_e2ee_backup(request.user)
        return Response({"message": "E2EE key backup deleted successfully."}, status=status.HTTP_200_OK)


class UserE2EEBackupRestoreView(APIView):
    """
    Restores the user's E2EE backup on a new device using their PIN/password auth_proof
    (or recovery bundle), optionally registering the new device's public key in the same request.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Restore E2EE Backup on New Device",
        description="Verifies backup PIN/password proof, returns the encrypted key bundle, and optionally registers the new device.",
        request=UserE2EEBackupRestoreSerializer,
        responses={200: OpenApiResponse(description="Backup restored successfully.")},
    )
    def post(self, request):
        serializer = UserE2EEBackupRestoreSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        result = restore_user_e2ee_backup(
            user=request.user,
            auth_proof=data.get("auth_proof", ""),
            recovery_code=data.get("recovery_code", ""),
            success=data.get("success"),
            use_recovery=data.get("use_recovery", False),
            device_id=data.get("device_id", ""),
            device_name=data.get("device_name", ""),
            identity_key=data.get("identity_key", ""),
            signed_prekey=data.get("signed_prekey", ""),
            signed_prekey_signature=data.get("signed_prekey_signature", ""),
            one_time_prekeys=data.get("one_time_prekeys", []),
        )
        backup = result["backup"]
        device_key = result["device_key"]
        restored_keys = result.get("restored_keys")

        if result["mode"] == "recovery":
            return Response(
                {
                    "message": "Recovery key bundle fetched successfully.",
                    "mode": "recovery",
                    "recovery_encrypted_bundle": backup.recovery_encrypted_bundle,
                    "recovery_nonce": backup.recovery_nonce,
                    "recovery_salt": backup.recovery_salt,
                    "kdf_algorithm": backup.kdf_algorithm,
                    "kdf_iterations": backup.kdf_iterations,
                    "cipher_algorithm": backup.cipher_algorithm,
                    "backup_public_key": backup.backup_public_key,
                    "backup_key_fingerprint": backup.backup_key_fingerprint,
                    "key_version": backup.key_version,
                },
                status=status.HTTP_200_OK,
            )

        response_payload = {
            "message": "E2EE key backup restored successfully.",
            "mode": "secret",
            "encrypted_key_bundle": backup.encrypted_key_bundle,
            "nonce": backup.nonce,
            "salt": backup.salt,
            "kdf_algorithm": backup.kdf_algorithm,
            "kdf_iterations": backup.kdf_iterations,
            "cipher_algorithm": backup.cipher_algorithm,
            "secret_type": backup.secret_type,
            "pin_length": backup.pin_length,
            "backup_public_key": backup.backup_public_key,
            "backup_key_fingerprint": backup.backup_key_fingerprint,
            "key_version": backup.key_version,
            "last_restored_at": backup.last_restored_at,
            "registered_device": (
                {
                    "device_id": device_key.device_id,
                    "device_name": device_key.device_name,
                    "algorithm": device_key.algorithm,
                    "is_active": device_key.is_active,
                }
                if device_key
                else None
            ),
        }
        if restored_keys is not None:
            response_payload["restored_keys"] = restored_keys

        return Response(response_payload, status=status.HTTP_200_OK)


class UserE2EEBackupChangeCodeView(APIView):
    """
    Changes the 5-digit recovery code / password protecting the user's E2EE key backup.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Messaging"],
        summary="Change 5-Digit E2EE Recovery Code",
        request=UserE2EEBackupChangeCodeSerializer,
        responses={200: OpenApiResponse(description="E2EE backup code updated successfully.")},
    )
    def post(self, request):
        serializer = UserE2EEBackupChangeCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        backup = change_user_e2ee_backup_secret(
            user=request.user,
            current_auth_proof=data.get("current_auth_proof", ""),
            current_recovery_code=data.get("current_recovery_code", ""),
            new_recovery_code=data.get("new_recovery_code", ""),
            encrypted_key_bundle=data.get("encrypted_key_bundle", ""),
            nonce=data.get("nonce", ""),
            salt=data.get("salt", ""),
            new_auth_proof=data.get("new_auth_proof", ""),
            kdf_algorithm=data.get("kdf_algorithm", "pbkdf2_sha256"),
            kdf_iterations=data.get("kdf_iterations", 310000),
            cipher_algorithm=data.get("cipher_algorithm", "chacha20_poly1305"),
            secret_type=data.get("secret_type"),
            backup_public_key=data.get("backup_public_key") or None,
        )
        return Response(
            {
                "message": "E2EE backup PIN/password updated successfully.",
                "key_version": backup.key_version,
                "secret_type": backup.secret_type,
                "pin_length": backup.pin_length,
                "backup_key_fingerprint": backup.backup_key_fingerprint,
            },
            status=status.HTTP_200_OK,
        )
