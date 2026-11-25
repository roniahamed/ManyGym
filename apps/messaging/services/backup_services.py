import os
from datetime import timedelta
from typing import Optional, Dict, Any, List
from django.contrib.auth.hashers import make_password, check_password
from django.db import transaction
from django.utils import timezone

from apps.users.models import User
from apps.messaging.crypto import (
    b64_decode,
    b64_encode,
    calculate_key_fingerprint,
    decrypt_backup_bundle,
    derive_backup_keys,
    encrypt_backup_bundle,
    generate_x25519_keypair,
    validate_recovery_code,
)
from apps.messaging.models import UserE2EEBackup, UserDeviceKey
from apps.messaging.services.device_key_services import register_user_device_key
from common.exceptions import (
    DomainValidationError,
    PermissionDeniedError,
    ResourceNotFoundError,
)


LOCKOUT_MINUTES = 30
ALLOWED_KDF_ALGORITHMS = {"pbkdf2_sha256", "argon2id"}
ALLOWED_CIPHER_ALGORITHMS = {"chacha20_poly1305", "aes_256_gcm"}


@transaction.atomic
def set_user_e2ee_backup(
    user: User,
    backup_public_key: str = "",
    encrypted_key_bundle: str = "",
    nonce: str = "",
    salt: str = "",
    kdf_algorithm: str = "pbkdf2_sha256",
    kdf_iterations: int = 310000,
    cipher_algorithm: str = "chacha20_poly1305",
    secret_type: str = UserE2EEBackup.SECRET_TYPE_PIN,
    auth_proof: str = "",
    recovery_code: str = "",
    pin_length: int = 5,
    recovery_encrypted_bundle: str = "",
    recovery_nonce: str = "",
    recovery_salt: str = "",
    max_attempts: int = 10,
) -> UserE2EEBackup:
    """
    Creates or updates a user's Messenger-style 5-digit PIN/password E2EE key backup.
    Supports both:
    - 5-digit recovery_code mode (generates/encrypts Master X25519 + Search keys using PBKDF2+HKDF+ChaCha20Poly1305)
    - Zero-knowledge client-encrypted bundle mode (stores client-encrypted bundle + auth_proof)
    Plaintext recovery codes and unencrypted private keys are never persisted in the database.
    """
    if kdf_algorithm not in ALLOWED_KDF_ALGORITHMS:
        raise DomainValidationError(f"Unsupported kdf_algorithm '{kdf_algorithm}'.")
    if cipher_algorithm not in ALLOWED_CIPHER_ALGORITHMS:
        raise DomainValidationError(f"Unsupported cipher_algorithm '{cipher_algorithm}'.")
    if kdf_iterations < 10000:
        raise DomainValidationError("kdf_iterations must be at least 10000 for security.")
    if max_attempts < 3 or max_attempts > 20:
        raise DomainValidationError("max_attempts must be between 3 and 20.")

    if recovery_code:
        validate_recovery_code(recovery_code)
        secret_type = UserE2EEBackup.SECRET_TYPE_PIN
        pin_length = 5

        if not (encrypted_key_bundle and nonce and salt and backup_public_key):
            master_priv, master_pub = generate_x25519_keypair()
            search_key = os.urandom(32)
            bundle_payload = {
                "master_private_key": b64_encode(master_priv),
                "master_public_key": master_pub,
                "search_key": b64_encode(search_key),
            }
            enc = encrypt_backup_bundle(bundle_payload, secret=recovery_code, iterations=kdf_iterations)
            backup_public_key = master_pub
            encrypted_key_bundle = enc["encrypted_key_bundle"]
            nonce = enc["nonce"]
            salt = enc["salt"]
            kdf_algorithm = enc["kdf_algorithm"]
            cipher_algorithm = enc["cipher_algorithm"]
            auth_proof = enc["auth_proof"]
        elif not auth_proof:
            _, auth_proof = derive_backup_keys(
                secret=recovery_code,
                salt=b64_decode(salt),
                iterations=kdf_iterations,
            )

    if not (backup_public_key and encrypted_key_bundle and nonce and salt):
        raise DomainValidationError(
            "Provide either a 5-digit 'recovery_code' or complete encrypted backup bundle fields."
        )

    fingerprint = calculate_key_fingerprint(backup_public_key)
    verifier_hash = make_password(auth_proof) if auth_proof else ""

    existing = UserE2EEBackup.objects.select_for_update().filter(user=user).first()
    if existing:
        existing.backup_public_key = backup_public_key
        existing.backup_key_fingerprint = fingerprint
        existing.encrypted_key_bundle = encrypted_key_bundle
        existing.nonce = nonce
        existing.salt = salt
        existing.kdf_algorithm = kdf_algorithm
        existing.kdf_iterations = kdf_iterations
        existing.cipher_algorithm = cipher_algorithm
        existing.secret_type = secret_type
        existing.pin_length = pin_length
        existing.verifier_hash = verifier_hash
        existing.recovery_encrypted_bundle = recovery_encrypted_bundle or ""
        existing.recovery_nonce = recovery_nonce or ""
        existing.recovery_salt = recovery_salt or ""
        existing.key_version = existing.key_version + 1
        existing.failed_attempts = 0
        existing.max_attempts = max_attempts
        existing.locked_until = None
        existing.is_active = True
        existing.save()
        return existing

    return UserE2EEBackup.objects.create(
        user=user,
        backup_public_key=backup_public_key,
        backup_key_fingerprint=fingerprint,
        encrypted_key_bundle=encrypted_key_bundle,
        nonce=nonce,
        salt=salt,
        kdf_algorithm=kdf_algorithm,
        kdf_iterations=kdf_iterations,
        cipher_algorithm=cipher_algorithm,
        secret_type=secret_type,
        pin_length=pin_length,
        verifier_hash=verifier_hash,
        recovery_encrypted_bundle=recovery_encrypted_bundle or "",
        recovery_nonce=recovery_nonce or "",
        recovery_salt=recovery_salt or "",
        key_version=1,
        failed_attempts=0,
        max_attempts=max_attempts,
        is_active=True,
    )


def _record_failed_attempt_and_raise(backup: UserE2EEBackup, message: str) -> None:
    """Increments failed restore attempts and locks the backup if max_attempts is reached."""
    backup.failed_attempts += 1
    now = timezone.now()
    if backup.failed_attempts >= backup.max_attempts:
        backup.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
    backup.save(update_fields=["failed_attempts", "locked_until", "updated_at"])

    remaining = max(0, backup.max_attempts - backup.failed_attempts)
    raise PermissionDeniedError(
        message,
        details={
            "failed_attempts": backup.failed_attempts,
            "max_attempts": backup.max_attempts,
            "remaining_attempts": remaining,
            "is_locked": backup.locked_until is not None and backup.locked_until > now,
            "locked_until": backup.locked_until.isoformat() if backup.locked_until else None,
        },
    )


def _assert_not_locked(backup: UserE2EEBackup) -> None:
    now = timezone.now()
    if backup.locked_until and backup.locked_until > now:
        raise PermissionDeniedError(
            "E2EE backup restore is temporarily locked due to too many failed attempts.",
            details={
                "is_locked": True,
                "locked_until": backup.locked_until.isoformat(),
                "failed_attempts": backup.failed_attempts,
                "max_attempts": backup.max_attempts,
                "remaining_attempts": 0,
            },
        )
    if backup.locked_until and backup.locked_until <= now:
        backup.locked_until = None
        backup.failed_attempts = 0
        backup.save(update_fields=["locked_until", "failed_attempts", "updated_at"])


def restore_user_e2ee_backup(
    user: User,
    auth_proof: str = "",
    recovery_code: str = "",
    success: Optional[bool] = None,
    use_recovery: bool = False,
    device_id: str = "",
    device_name: str = "",
    identity_key: str = "",
    signed_prekey: str = "",
    signed_prekey_signature: str = "",
    one_time_prekeys: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Verifies a restore attempt on a new device using either the 5-digit recovery_code
    or client-derived auth_proof, enforces attempt lockouts, returns the encrypted backup bundle
    (plus decrypted key bundle when recovery_code is supplied), and optionally registers the new device.
    """
    backup = UserE2EEBackup.objects.filter(user=user, is_active=True).first()
    if not backup:
        raise ResourceNotFoundError("No active E2EE backup found for this account.")

    _assert_not_locked(backup)

    if use_recovery:
        if not backup.recovery_encrypted_bundle:
            raise ResourceNotFoundError("No secondary recovery bundle is configured for this account.")
        return {
            "backup": backup,
            "device_key": None,
            "restored_keys": None,
            "mode": "recovery",
        }

    if recovery_code:
        validate_recovery_code(recovery_code)
        if not auth_proof:
            _, auth_proof = derive_backup_keys(
                secret=recovery_code,
                salt=b64_decode(backup.salt),
                iterations=backup.kdf_iterations,
            )

    if backup.verifier_hash:
        if not auth_proof or not check_password(auth_proof, backup.verifier_hash):
            _record_failed_attempt_and_raise(
                backup,
                "Invalid 5-digit recovery code / E2EE backup secret.",
            )
    elif success is False:
        _record_failed_attempt_and_raise(
            backup,
            "E2EE backup decryption failed on client.",
        )

    restored_keys: Optional[Dict[str, Any]] = None
    if recovery_code:
        try:
            restored_keys = decrypt_backup_bundle(
                encrypted_bundle_b64=backup.encrypted_key_bundle,
                nonce_b64=backup.nonce,
                salt_b64=backup.salt,
                secret=recovery_code,
                iterations=backup.kdf_iterations,
                cipher_algorithm=backup.cipher_algorithm,
            )
        except Exception:
            _record_failed_attempt_and_raise(
                backup,
                "Invalid 5-digit recovery code / E2EE backup secret.",
            )

    device_key: Optional[UserDeviceKey] = None
    with transaction.atomic():
        backup.failed_attempts = 0
        backup.locked_until = None
        backup.last_restored_at = timezone.now()
        backup.save(update_fields=["failed_attempts", "locked_until", "last_restored_at", "updated_at"])

        if device_id and identity_key and signed_prekey:
            device_key = register_user_device_key(
                user=user,
                device_id=device_id,
                identity_key=identity_key,
                signed_prekey=signed_prekey,
                signed_prekey_signature=signed_prekey_signature,
                one_time_prekeys=one_time_prekeys or [],
                device_name=device_name,
            )

    return {
        "backup": backup,
        "device_key": device_key,
        "restored_keys": restored_keys,
        "mode": "secret",
    }


def change_user_e2ee_backup_secret(
    user: User,
    current_auth_proof: str = "",
    current_recovery_code: str = "",
    new_recovery_code: str = "",
    encrypted_key_bundle: str = "",
    nonce: str = "",
    salt: str = "",
    new_auth_proof: str = "",
    kdf_algorithm: str = "pbkdf2_sha256",
    kdf_iterations: int = 310000,
    cipher_algorithm: str = "chacha20_poly1305",
    secret_type: Optional[str] = None,
    backup_public_key: Optional[str] = None,
) -> UserE2EEBackup:
    """
    Rotates the 5-digit recovery code / E2EE password protecting the backup while preserving
    the underlying Master Keypair & Search Key so historical messages remain decryptable.
    """
    backup = UserE2EEBackup.objects.filter(user=user, is_active=True).first()
    if not backup:
        raise ResourceNotFoundError("No active E2EE backup found for this account.")

    _assert_not_locked(backup)

    if current_recovery_code:
        validate_recovery_code(current_recovery_code)
        if not current_auth_proof:
            _, current_auth_proof = derive_backup_keys(
                secret=current_recovery_code,
                salt=b64_decode(backup.salt),
                iterations=backup.kdf_iterations,
            )

    if backup.verifier_hash:
        if not current_auth_proof or not check_password(current_auth_proof, backup.verifier_hash):
            _record_failed_attempt_and_raise(
                backup,
                "Current 5-digit recovery code / E2EE backup secret is incorrect.",
            )

    if new_recovery_code:
        validate_recovery_code(new_recovery_code)
        if not (encrypted_key_bundle and nonce and salt):
            if not current_recovery_code:
                raise DomainValidationError(
                    "current_recovery_code is required to re-encrypt the existing key bundle with new_recovery_code."
                )
            try:
                existing_bundle = decrypt_backup_bundle(
                    encrypted_bundle_b64=backup.encrypted_key_bundle,
                    nonce_b64=backup.nonce,
                    salt_b64=backup.salt,
                    secret=current_recovery_code,
                    iterations=backup.kdf_iterations,
                    cipher_algorithm=backup.cipher_algorithm,
                )
            except Exception:
                _record_failed_attempt_and_raise(
                    backup,
                    "Current 5-digit recovery code / E2EE backup secret is incorrect.",
                )
            re_enc = encrypt_backup_bundle(
                existing_bundle,
                secret=new_recovery_code,
                iterations=kdf_iterations,
            )
            encrypted_key_bundle = re_enc["encrypted_key_bundle"]
            nonce = re_enc["nonce"]
            salt = re_enc["salt"]
            kdf_algorithm = re_enc["kdf_algorithm"]
            cipher_algorithm = re_enc["cipher_algorithm"]
            new_auth_proof = re_enc["auth_proof"]
            secret_type = UserE2EEBackup.SECRET_TYPE_PIN

    if not (encrypted_key_bundle and nonce and salt):
        raise DomainValidationError(
            "Provide either 'current_recovery_code' + 'new_recovery_code' or re-encrypted bundle fields."
        )

    if kdf_algorithm not in ALLOWED_KDF_ALGORITHMS:
        raise DomainValidationError(f"Unsupported kdf_algorithm '{kdf_algorithm}'.")
    if cipher_algorithm not in ALLOWED_CIPHER_ALGORITHMS:
        raise DomainValidationError(f"Unsupported cipher_algorithm '{cipher_algorithm}'.")
    if kdf_iterations < 10000:
        raise DomainValidationError("kdf_iterations must be at least 10000 for security.")

    with transaction.atomic():
        if backup_public_key:
            backup.backup_public_key = backup_public_key
            backup.backup_key_fingerprint = calculate_key_fingerprint(backup_public_key)
        backup.encrypted_key_bundle = encrypted_key_bundle
        backup.nonce = nonce
        backup.salt = salt
        backup.kdf_algorithm = kdf_algorithm
        backup.kdf_iterations = kdf_iterations
        backup.cipher_algorithm = cipher_algorithm
        if secret_type:
            backup.secret_type = secret_type
        backup.verifier_hash = make_password(new_auth_proof) if new_auth_proof else ""
        backup.key_version += 1
        backup.failed_attempts = 0
        backup.locked_until = None
        backup.save()

    return backup


@transaction.atomic
def delete_user_e2ee_backup(user: User) -> None:
    """Deletes the user's E2EE backup."""
    deleted_count, _ = UserE2EEBackup.objects.filter(user=user).delete()
    if not deleted_count:
        raise ResourceNotFoundError("No E2EE backup found to delete.")
