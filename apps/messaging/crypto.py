"""
End-to-End Encryption (E2EE) Cryptographic Primitives and Helpers.

Implements industry-standard asymmetric + symmetric hybrid cryptography:
- X25519 (Curve25519 Diffie-Hellman) for key exchange
- Ed25519 for digital signatures (Signed Pre-Keys verification)
- HKDF-SHA256 for key derivation
- ChaCha20-Poly1305 / AES-GCM for authenticated symmetric encryption
"""

import os
import re
import json
import hmac
import base64
import hashlib
from typing import Tuple, Dict, Any, List

from cryptography.hazmat.primitives.asymmetric import x25519, ed25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
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


_FIVE_DIGIT_PIN_RE = re.compile(r"^\d{5}$")


def validate_recovery_code(code: str) -> str:
    """Validates that a Messenger-style recovery code is strictly a 5-digit numeric string."""
    if not isinstance(code, str) or not _FIVE_DIGIT_PIN_RE.match(code):
        raise DomainValidationError("Recovery code must be a 5-digit number (e.g., '12345').")
    return code


def derive_backup_keys(
    secret: str,
    salt: bytes,
    iterations: int = 310000,
) -> Tuple[bytes, str]:
    """
    Derives a 256-bit Key Encryption Key (KEK) and a domain-separated AuthProof (Base64)
    from a user's Messenger-style E2EE PIN/password using PBKDF2-HMAC-SHA256 + HKDF-SHA256.
    """
    if not secret or not isinstance(secret, str):
        raise DomainValidationError("Backup secret code/password must be a non-empty string.")
    if not salt or len(salt) < 16:
        raise DomainValidationError("Salt must be at least 16 bytes.")

    pbkdf2 = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    master_secret = pbkdf2.derive(secret.encode("utf-8"))

    kek = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"ManyGym-E2EE-Backup-KEK-v1",
    ).derive(master_secret)

    auth_proof_bytes = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"ManyGym-E2EE-Backup-Auth-v1",
    ).derive(master_secret)

    return kek, b64_encode(auth_proof_bytes)


def encrypt_backup_bundle(
    bundle_data: Dict[str, Any],
    secret: str,
    iterations: int = 310000,
) -> Dict[str, Any]:
    """
    Encrypts a JSON-serializable E2EE key bundle (identity private key, search key, etc.)
    using a Messenger-style PIN/password-derived KEK and ChaCha20-Poly1305.
    """
    salt = os.urandom(16)
    kek, auth_proof = derive_backup_keys(secret=secret, salt=salt, iterations=iterations)
    nonce = os.urandom(12)
    plaintext_bytes = json.dumps(bundle_data, sort_keys=True).encode("utf-8")
    ciphertext = ChaCha20Poly1305(kek).encrypt(nonce, plaintext_bytes, None)

    return {
        "encrypted_key_bundle": b64_encode(ciphertext),
        "nonce": b64_encode(nonce),
        "salt": b64_encode(salt),
        "kdf_algorithm": "pbkdf2_sha256",
        "kdf_iterations": iterations,
        "cipher_algorithm": "chacha20_poly1305",
        "auth_proof": auth_proof,
    }


def decrypt_backup_bundle(
    encrypted_bundle_b64: str,
    nonce_b64: str,
    salt_b64: str,
    secret: str,
    iterations: int = 310000,
    cipher_algorithm: str = "chacha20_poly1305",
) -> Dict[str, Any]:
    """
    Decrypts an E2EE key backup bundle on a new device using the user's PIN/password.
    """
    salt = b64_decode(salt_b64)
    kek, _ = derive_backup_keys(secret=secret, salt=salt, iterations=iterations)
    nonce = b64_decode(nonce_b64)
    ciphertext = b64_decode(encrypted_bundle_b64)

    if cipher_algorithm == "aes_256_gcm":
        plaintext_bytes = AESGCM(kek).decrypt(nonce, ciphertext, None)
    else:
        plaintext_bytes = ChaCha20Poly1305(kek).decrypt(nonce, ciphertext, None)

    return json.loads(plaintext_bytes.decode("utf-8"))


_TOKEN_WORD_RE = re.compile(r"[\w]+", re.UNICODE)


def normalize_search_keyword(keyword: str) -> str:
    """Normalizes a search keyword consistently before computing a blinded HMAC search token."""
    return (keyword or "").strip().lower()


def compute_search_token(search_key_bytes: bytes, keyword: str) -> str:
    """Computes a deterministic blinded HMAC-SHA256 hex digest for a single normalized keyword."""
    normalized = normalize_search_keyword(keyword)
    if not normalized:
        raise DomainValidationError("Search keyword cannot be empty.")
    return hmac.new(search_key_bytes, normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def compute_search_tokens(search_key_bytes: bytes, text: str, max_tokens: int = 200) -> List[str]:
    """
    Tokenizes plaintext on the client and returns unique blinded HMAC-SHA256 tokens
    for zero-knowledge chat history search.
    """
    if not text:
        return []
    words = _TOKEN_WORD_RE.findall(text.lower())
    seen = set()
    tokens: List[str] = []
    for word in words:
        if word in seen:
            continue
        seen.add(word)
        tokens.append(compute_search_token(search_key_bytes, word))
        if len(tokens) >= max_tokens:
            break
    return tokens
