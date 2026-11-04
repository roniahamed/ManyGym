from rest_framework.throttling import SimpleRateThrottle


class AuthRateThrottle(SimpleRateThrottle):
    """
    Base rate throttle for sensitive authentication and OTP endpoints.
    Combines client IP and normalized email from request body when present
    to prevent credential stuffing and targeted brute-force attacks.
    """

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        email = ""
        if hasattr(request, "data") and isinstance(request.data, dict):
            email_val = request.data.get("email")
            if isinstance(email_val, str) and email_val.strip():
                email = email_val.strip().lower()

        if email:
            ident = f"{ident}:{email}"

        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }


class LoginRateThrottle(AuthRateThrottle):
    scope = "login"


class OTPVerifyRateThrottle(AuthRateThrottle):
    scope = "otp_verify"


class OTPRequestRateThrottle(AuthRateThrottle):
    scope = "otp_request"


class TokenRefreshRateThrottle(SimpleRateThrottle):
    scope = "token_refresh"

    def get_cache_key(self, request, view):
        ident = self.get_ident(request)
        return self.cache_format % {
            "scope": self.scope,
            "ident": ident,
        }

