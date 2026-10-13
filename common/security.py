import hashlib
import hmac
from django.conf import settings


def hash_otp(email: str, otp_code: str) -> str:
    """
    Computes a cryptographic HMAC-SHA256 digest of the OTP code
    salted with the normalized email and keyed with Django's SECRET_KEY.
    Prevents rainbow table attacks, offline brute forcing, and database leakage exposure.
    """
    secret = settings.SECRET_KEY.encode("utf-8")
    message = f"{str(email).lower().strip()}:{str(otp_code).strip()}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()
