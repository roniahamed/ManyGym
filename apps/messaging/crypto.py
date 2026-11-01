"""
End-to-End Encryption (E2EE) Cryptographic Primitives and Helpers.

Implements industry-standard asymmetric + symmetric hybrid cryptography:
- X25519 (Curve25519 Diffie-Hellman) for key exchange
- Ed25519 for digital signatures (Signed Pre-Keys verification)
- HKDF-SHA256 for key derivation
- ChaCha20-Poly1305 / AES-GCM for authenticated symmetric encryption
"""

import os
import base64
import hashlib
from typing import Tuple, Dict, Any

from cryptography.hazmat.primitives.asymmetric import x25519, ed25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305, AESGCM

from common.exceptions import DomainValidationError


def b64_encode(data: bytes) -> str:
    """Encodes bytes into a URL-safe or standard Base64 string."""
    return base64.b64encode(data).decode("utf-8")


def b64_decode(data_str: str) -> bytes:
    """Decodes a Base64 string to bytes."""
    try:
        return base64.b64decode(data_str.encode("utf-8"))
    except Exception as exc:
        raise DomainValidationError(f"Invalid Base64 payload: {str(exc)}")


def generate_x25519_keypair() -> Tuple[bytes, str]:
    """
    Generates a Curve25519 (X25519) key pair.
    Returns:
        (private_key_bytes, public_key_base64)
    """
    private_key = x25519.X25519PrivateKey.generate()
    public_key = private_key.public_key()
    return (
        private_key.private_bytes_raw(),
        b64_encode(public_key.public_bytes_raw()),
    )


def generate_ed25519_keypair() -> Tuple[bytes, str]:
    """
    Generates an Ed25519 signature key pair.
    Returns:
        (private_bytes, public_key_base64)
    """
    signing_key = ed25519.Ed25519PrivateKey.generate()
    verify_key = signing_key.public_key()
    return (
        signing_key.private_bytes_raw(),
        b64_encode(verify_key.public_bytes_raw()),
    )


def sign_prekey(ed25519_private_bytes: bytes, prekey_b64: str) -> str:
    """Signs an X25519 pre-key with an Ed25519 private key."""
    signing_key = ed25519.Ed25519PrivateKey.from_private_bytes(ed25519_private_bytes)
    prekey_bytes = b64_decode(prekey_b64)
    signature = signing_key.sign(prekey_bytes)
    return b64_encode(signature)


def verify_signed_prekey(
    ed25519_public_b64: str,
    prekey_b64: str,
    signature_b64: str,
) -> bool:
    """Verifies that an X25519 prekey was signed by the owner of the Ed25519 public key."""
    try:
        verify_key = ed25519.Ed25519PublicKey.from_public_bytes(b64_decode(ed25519_public_b64))
        verify_key.verify(b64_decode(signature_b64), b64_decode(prekey_b64))
        return True
    except Exception:
        return False


def calculate_key_fingerprint(public_key_b64: str) -> str:
    """Calculates a SHA-256 fingerprint for a public key."""
    raw = b64_decode(public_key_b64)
    return hashlib.sha256(raw).hexdigest()[:16]


def derive_shared_symmetric_key(
    our_x25519_private_bytes: bytes,
    peer_x25519_public_b64: str,
    salt: bytes = b"ManyGym-E2EE-v1",
) -> bytes:
    """Derives a 256-bit symmetric session key via X25519 Diffie-Hellman + HKDF-SHA256."""
    our_priv = x25519.X25519PrivateKey.from_private_bytes(our_x25519_private_bytes)
    peer_pub = x25519.X25519PublicKey.from_public_bytes(b64_decode(peer_x25519_public_b64))
    shared_secret = our_priv.exchange(peer_pub)

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"ManyGym-DirectMessaging",
    )
    return hkdf.derive(shared_secret)


def hybrid_encrypt(
    recipient_public_key_b64: str,
    plaintext: str,
) -> Dict[str, str]:
    """
    Encrypts a plaintext string for the recipient using X25519 ephemeral key + ChaCha20-Poly1305.
    Returns:
        {
            "ciphertext": base64_str,
            "nonce": base64_str,
            "ephemeral_public_key": base64_str,
            "recipient_key_fingerprint": hex_str
        }
    """
    ephemeral_priv_bytes, ephemeral_pub_b64 = generate_x25519_keypair()
    session_key = derive_shared_symmetric_key(
        our_x25519_private_bytes=ephemeral_priv_bytes,
        peer_x25519_public_b64=recipient_public_key_b64,
    )

    nonce = os.urandom(12)
    cipher = ChaCha20Poly1305(session_key)
    ciphertext = cipher.encrypt(nonce, plaintext.encode("utf-8"), None)

    return {
        "ciphertext": b64_encode(ciphertext),
        "nonce": b64_encode(nonce),
        "ephemeral_public_key": ephemeral_pub_b64,
        "recipient_key_fingerprint": calculate_key_fingerprint(recipient_public_key_b64),
    }


def hybrid_decrypt(
    recipient_private_bytes: bytes,
    ephemeral_public_key_b64: str,
    ciphertext_b64: str,
    nonce_b64: str,
) -> str:
    """
    Decrypts a ciphertext payload using recipient's X25519 private key and sender's ephemeral public key.
    """
    session_key = derive_shared_symmetric_key(
        our_x25519_private_bytes=recipient_private_bytes,
        peer_x25519_public_b64=ephemeral_public_key_b64,
    )

    nonce = b64_decode(nonce_b64)
    ciphertext = b64_decode(ciphertext_b64)

    cipher = ChaCha20Poly1305(session_key)
    decrypted_bytes = cipher.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode("utf-8")
