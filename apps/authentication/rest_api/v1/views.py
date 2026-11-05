from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample

from apps.authentication.rest_api.v1.serializers import (
    LoginSerializer,
    SwitchContextSerializer,
    LogoutSerializer,
    LoginResponseSerializer,
    SwitchContextResponseSerializer,
    RefreshTokenSerializer,
    RefreshTokenResponseSerializer,
)
from apps.authentication.services import (
    authenticate_user,
    switch_gym_context,
    switch_to_personal_context,
    revoke_token,
    refresh_context_token,
)
from apps.users.rest_api.v1.serializers import UserSerializer
from common.enums import TokenContextType
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer
from common.throttling import LoginRateThrottle, TokenRefreshRateThrottle


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    @extend_schema(
        tags=["Authentication & Sessions"],
        summary="User Authentication & Login",
        description="""
### Summary
Authenticates user credentials and issues a contextual JWT access & refresh token pair (defaulting to Personal Profile context).

### Authentication & Authorization
- **Authentication**: None.
- **Authorization**: Public endpoint.

### Business Rules
1. Verifies that credentials match an active user.
2. Checks that `is_verified=True` (if unverified, rejects login with 400 instructions to verify OTP).
3. Checks that user status is `active`.
4. Registers session in `auth_tokens` registry.
5. Returns Personal context JWT tokens.
6. Enforces rate limiting and account lockout after 5 consecutive failed login attempts (returns 429 with `Retry-After` backoff).
        """,
        request=LoginSerializer,
        responses={
            200: OpenApiResponse(
                response=LoginResponseSerializer,
                description="Authentication successful; session tokens issued.",
                examples=[
                    OpenApiExample(
                        name="Login Success Example",
                        value={
                            "message": "Login successful.",
                            "user": {
                                "id": "b3e0c0fa-2384-48f8-b3d5-e357e62a0a20",
                                "email": "alex.morgan@manygym.com",
                                "first_name": "Alex",
                                "last_name": "Morgan",
                                "phone": "+14155552671",
                                "status": "active",
                                "is_verified": True,
                            },
                            "tokens": {
                                "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                                "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                                "context_type": "personal",
                                "gym_id": None,
                                "gym_name": None,
                                "scopes": [],
                            },
                        },
                    )
                ],
            ),
            400: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Invalid credentials or unverified account.",
                examples=[
                    OpenApiExample(
                        name="Invalid Credentials Example",
                        value={
                            "code": "VALIDATION_ERROR",
                            "message": "Invalid email or password.",
                            "details": {},
                        },
                    ),
                    OpenApiExample(
                        name="Unverified Account Example",
                        value={
                            "code": "VALIDATION_ERROR",
                            "message": "Your account has not been verified yet. Please verify your OTP.",
                            "details": {},
                        },
                    ),
                ],
            ),
            429: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Account locked or rate limit exceeded due to consecutive failed attempts.",
                examples=[
                    OpenApiExample(
                        name="Account Lockout Example",
                        value={
                            "code": "THROTTLED",
                            "message": "Request was throttled due to rate limiting.",
                            "details": {
                                "detail": "Account locked due to consecutive failed login attempts. Try again in 300 seconds."
                            },
                        },
                    )
                ],
            ),
        },
        examples=[
            OpenApiExample(
                name="Login Payload Example",
                value={
                    "email": "alex.morgan@manygym.com",
                    "password": "SecurePassword2026!",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reactivate = serializer.validated_data.get("reactivate", False)
        restore = serializer.validated_data.get("restore", False)
        user, tokens = authenticate_user(
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
            reactivate=reactivate,
            restore=restore,
        )
        from apps.gyms.models import Gym
        deactivated_gyms = list(
            Gym.objects.filter(owner_user=user, settings__is_deactivated=True)
            .values("id", "name")
        )
        if restore:
            message = "Your account has been restored successfully."
        elif reactivate:
            message = "Your account has been reactivated successfully."
        else:
            message = "Login successful."
        response_data = {
            "message": message,
            "user": UserSerializer(user).data,
            "tokens": tokens,
        }
        if deactivated_gyms:
            notice = f"Your gym '{deactivated_gyms[0]['name']}' is deactivated. Do you want to reactivate it? If so, please reactivate it from Settings."
            response_data["deactivation_notice"] = notice
            response_data["has_deactivated_gym"] = True
            response_data["deactivated_gyms"] = [
                {
                    "id": str(g["id"]),
                    "name": g["name"],
                    "message": f"Gym '{g['name']}' is deactivated. Do you want to reactivate it? If so, please reactivate it from Settings.",
                }
                for g in deactivated_gyms
            ]
        return Response(response_data, status=status.HTTP_200_OK)


class SwitchContextView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Authentication & Sessions"],
        summary="Switch Token Context (Personal vs Gym)",
        description="""
### Summary
Dynamically switches user operational context between Personal Profile and specific Gym accounts. Issues a new JWT access & refresh token pair carrying context claims and computed permission scopes.

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- **Authorization**: User must be the Gym Owner or an active Gym Staff member for the specified `gym_id`.

### Business Rules & Token Scopes
1. If `context_type` is `"personal"`, `gym_id` is set to null and `scopes` is empty.
2. If `context_type` is `"gym"`:
   - Validates user relationship to the gym.
   - If user is Gym Owner: granted **ALL** permissions across all 9 topics.
   - If user is Staff Member: granted the permissions linked to their assigned active Role.
3. Token carries claims: `{"context_type": "gym", "gym_id": "...", "scopes": ["members:read", ...]}`.
        """,
        request=SwitchContextSerializer,
        responses={
            200: OpenApiResponse(
                response=SwitchContextResponseSerializer,
                description="Context switched; newly scoped token issued.",
                examples=[
                    OpenApiExample(
                        name="Switch to Gym Context Example",
                        value={
                            "message": "Successfully switched to gym context.",
                            "tokens": {
                                "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                                "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                                "context_type": "gym",
                                "gym_id": "31d57929-e58f-49b0-9bf7-fa5d07c08285",
                                "gym_name": "Apex Fitness Club",
                                "scopes": [
                                    "members:read",
                                    "members:edit",
                                    "routines:assign",
                                    "studio:read",
                                ],
                            },
                        },
                    )
                ],
            ),
            400: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Missing gym_id when switching to gym context.",
            ),
            401: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="User does not have access rights to the requested gym.",
                examples=[
                    OpenApiExample(
                        name="Unauthorized Gym Example",
                        value={
                            "code": "UNAUTHORIZED_CONTEXT",
                            "message": "You do not have access rights to gym 'Apex Fitness Club'.",
                            "details": {},
                        },
                    )
                ],
            ),
            404: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Target gym not found.",
            ),
        },
        examples=[
            OpenApiExample(
                name="Switch to Gym Request",
                value={
                    "context_type": "gym",
                    "gym_id": "31d57929-e58f-49b0-9bf7-fa5d07c08285",
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Switch to Personal Request",
                value={"context_type": "personal"},
                request_only=True,
            ),
        ],
    )
    def post(self, request):
        serializer = SwitchContextSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        context_type = serializer.validated_data["context_type"]
        gym_id = serializer.validated_data.get("gym_id")

        # Capture caller's previous access token to invalidate on successful switch (Issue 17b)
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        prev_access_token = ""
        if auth_header.startswith("Bearer "):
            prev_access_token = auth_header.split(" ", 1)[1].strip()
        elif hasattr(request, "auth") and request.auth:
            prev_access_token = str(request.auth)

        if context_type == TokenContextType.GYM:
            tokens = switch_gym_context(user=request.user, gym_id=str(gym_id))
            if prev_access_token:
                revoke_token(access_token_str=prev_access_token)
            gym_obj = tokens.pop("_gym", None)
            is_deactivated = False
            if gym_obj:
                settings_obj = getattr(gym_obj, "settings", None)
                if settings_obj:
                    is_deactivated = getattr(settings_obj, "is_deactivated", False)
            if is_deactivated:
                notice = "This gym is deactivated. Do you want to reactivate it? If so, please reactivate it from Settings."
                return Response(
                    {
                        "message": notice,
                        "deactivation_notice": notice,
                        "is_deactivated": True,
                        "tokens": tokens,
                    },
                    status=status.HTTP_200_OK,
                )
            return Response(
                {
                    "message": f"Successfully switched to {context_type} context.",
                    "tokens": tokens,
                },
                status=status.HTTP_200_OK,
            )
        else:
            tokens = switch_to_personal_context(user=request.user)
            if prev_access_token:
                revoke_token(access_token_str=prev_access_token)
            return Response(
                {
                    "message": f"Successfully switched to {context_type} context.",
                    "tokens": tokens,
                },
                status=status.HTTP_200_OK,
            )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Authentication & Sessions"],
        summary="User Logout & Token Revocation",
        description="""
### Summary
Invalidates the current session access token and optional refresh token by adding them to the server-side denylist and removing them from the active `auth_tokens` registry.

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
        """,
        request=LogoutSerializer,
        responses={
            200: OpenApiResponse(
                response=MessageResponseSerializer,
                description="Session successfully invalidated.",
            ),
            401: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Authentication required or token revoked.",
            ),
        },
        examples=[
            OpenApiExample(
                name="Logout Payload Example",
                value={"refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."},
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refresh_token = serializer.validated_data.get("refresh", "")

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        access_token = ""
        if auth_header.startswith("Bearer "):
            access_token = auth_header.split(" ")[1]

        revoke_token(access_token_str=access_token, refresh_token_str=refresh_token)

        return Response(
            {"message": "Logged out successfully."},
            status=status.HTTP_200_OK,
        )


class TokenRefreshView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [TokenRefreshRateThrottle]

    @extend_schema(
        tags=["Authentication & Sessions"],
        summary="Refresh Contextual JWT Token",
        description="""
### Summary
Exchanges an active refresh token for a fresh access and refresh token pair while preserving all tenant context claims (`context_type`, `gym_id`, and `scopes`). The provided refresh token is rotated and revoked.

### Authentication & Authorization
- **Authentication**: None (Public endpoint, refresh token provided in payload).
- **Authorization**: Public.
        """,
        request=RefreshTokenSerializer,
        responses={
            200: OpenApiResponse(
                response=RefreshTokenResponseSerializer,
                description="Token refreshed successfully; fresh session pair issued.",
            ),
            400: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Invalid or missing refresh token.",
            ),
            401: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Refresh token has expired or was revoked.",
            ),
            429: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Too many refresh requests; rate limit throttled.",
            ),
        },
        examples=[
            OpenApiExample(
                name="Refresh Token Payload",
                value={"refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."},
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = RefreshTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tokens = refresh_context_token(serializer.validated_data["refresh"])
        return Response(
            {
                "message": "Token refreshed successfully.",
                "tokens": tokens,
            },
            status=status.HTTP_200_OK,
        )
