from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample

from apps.users.rest_api.v1.serializers import (
    UserRegistrationSerializer,
    VerifySignupOTPSerializer,
    ResendOTPSerializer,
    ForgotPasswordSerializer,
    VerifyResetOTPSerializer,
    ResetPasswordSerializer,
    ChangePasswordSerializer,
    UpdateProfileSerializer,
    UserSerializer,
    RegisterResponseSerializer,
    VerifySignupResponseSerializer,
    UserProfileMeResponseSerializer,
)
from apps.users.services import (
    register_user,
    verify_signup_otp,
    resend_signup_otp,
    request_password_reset,
    verify_password_reset_otp,
    reset_password,
    update_user_profile,
    change_password,
)
from apps.users.selectors import get_user_by_id
from apps.authentication.services import issue_context_token
from apps.gyms.selectors import get_accessible_gyms_for_user
from common.enums import TokenContextType
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer


class RegisterView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["User Identity & Onboarding"],
        summary="User Registration / Sign Up",
        description="""
### Summary
Creates a new customer account with unverified status and immediately queues an asynchronous verification OTP via SMTP email.

### Authentication & Authorization
- **Authentication**: None (Public endpoint).
- **Authorization**: Anyone may register.

### Business Rules & Workflow
1. Normalizes and validates uniqueness of `email`.
2. Password must be at least 8 characters.
3. Automatically provisions an empty `UserProfile` attached to the user.
4. Generates a cryptographic 6-digit numeric OTP valid for **15 minutes**.
5. Sets `is_verified=False` and status to `active`.

### Side Effects
- Dispatches a Celery background task (`send_email_task`) to deliver the verification code via configured SMTP backend.
        """,
        request=UserRegistrationSerializer,
        responses={
            201: OpenApiResponse(
                response=RegisterResponseSerializer,
                description="Account created successfully; verification OTP email queued.",
                examples=[
                    OpenApiExample(
                        name="Success 201 Response",
                        value={
                            "message": "Registration successful. A 6-digit verification code has been dispatched to your email.",
                            "email": "alex.morgan@manygym.com",
                        },
                    )
                ],
            ),
            400: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Input validation failure (e.g. weak password or invalid email format).",
                examples=[
                    OpenApiExample(
                        name="Validation Error Example",
                        value={
                            "code": "VALIDATION_ERROR",
                            "message": "Validation failed for the submitted data.",
                            "details": {"password": ["Ensure this field has at least 8 characters."]},
                        },
                    )
                ],
            ),
            409: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="An account with this email already exists.",
                examples=[
                    OpenApiExample(
                        name="Duplicate Email Conflict",
                        value={
                            "code": "RESOURCE_CONFLICT",
                            "message": "An account with this email address already exists.",
                            "details": {},
                        },
                    )
                ],
            ),
        },
        examples=[
            OpenApiExample(
                name="Valid Registration Request",
                value={
                    "email": "alex.morgan@manygym.com",
                    "password": "SecurePassword2026!",
                    "first_name": "Alex",
                    "last_name": "Morgan",
                    "phone": "+14155552671",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = register_user(**serializer.validated_data)
        return Response(
            {
                "message": "Registration successful. A 6-digit verification code has been dispatched to your email.",
                "email": user.email,
            },
            status=status.HTTP_201_CREATED,
        )


class VerifySignupOTPView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["User Identity & Onboarding"],
        summary="Verify Account Registration OTP",
        description="""
### Summary
Validates the 6-digit registration OTP, marks the account as verified, and immediately generates initial session JWT tokens in Personal Profile context.

### Authentication & Authorization
- **Authentication**: None.
- **Authorization**: Public endpoint.

### Business Rules & Workflow
1. Verifies OTP matching the email and purpose `signup_verification`.
2. Validates that OTP has not expired (within 15 minutes) and has not already been used.
3. Sets `user.is_verified = True`.
4. Invalidates the used OTP.
5. Issues a JWT access and refresh token pair signed with `context_type: personal`.
        """,
        request=VerifySignupOTPSerializer,
        responses={
            200: OpenApiResponse(
                response=VerifySignupResponseSerializer,
                description="Account verified; initial session tokens issued.",
                examples=[
                    OpenApiExample(
                        name="Verification Success Example",
                        value={
                            "message": "Account successfully verified.",
                            "user": {
                                "id": "b3e0c0fa-2384-48f8-b3d5-e357e62a0a20",
                                "email": "alex.morgan@manygym.com",
                                "first_name": "Alex",
                                "last_name": "Morgan",
                                "phone": "+14155552671",
                                "status": "active",
                                "is_verified": True,
                                "created_at": "2026-10-12T12:00:00Z",
                                "updated_at": "2026-10-12T12:05:00Z",
                                "profile": {
                                    "avatar_url": None,
                                    "address": None,
                                    "city": None,
                                    "country": None,
                                    "date_of_birth": None,
                                    "sex": None,
                                    "nationality": None,
                                },
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
                description="Invalid or expired OTP code.",
                examples=[
                    OpenApiExample(
                        name="Invalid OTP Example",
                        value={
                            "code": "VALIDATION_ERROR",
                            "message": "Invalid or expired verification OTP.",
                            "details": {},
                        },
                    )
                ],
            ),
            404: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="User with this email was not found.",
            ),
        },
        examples=[
            OpenApiExample(
                name="Valid Verification Payload",
                value={"email": "alex.morgan@manygym.com", "otp_code": "849201"},
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = VerifySignupOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = verify_signup_otp(
            email=serializer.validated_data["email"],
            otp_code=serializer.validated_data["otp_code"],
        )
        tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
        return Response(
            {
                "message": "Account successfully verified.",
                "user": UserSerializer(user).data,
                "tokens": tokens,
            },
            status=status.HTTP_200_OK,
        )


class ResendOTPView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["User Identity & Onboarding"],
        summary="Resend Registration OTP",
        description="""
### Summary
Invalidates prior unused registration OTPs and dispatches a fresh 6-digit OTP code to the user's email.

### Business Rules
- User must exist and not already be verified (`is_verified=False`).
- Generates a new 15-minute OTP and sends via SMTP.
        """,
        request=ResendOTPSerializer,
        responses={
            200: OpenApiResponse(
                response=MessageResponseSerializer,
                description="New verification code queued.",
            ),
            400: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Account is already verified.",
            ),
            404: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="User not found.",
            ),
        },
        examples=[
            OpenApiExample(
                name="Resend OTP Request",
                value={"email": "alex.morgan@manygym.com"},
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = ResendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resend_signup_otp(email=serializer.validated_data["email"])
        return Response(
            {"message": "A new verification code has been dispatched to your email."},
            status=status.HTTP_200_OK,
        )


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Password Management"],
        summary="Request Password Reset OTP",
        description="""
### Summary
Initiates self-service password recovery by generating a 6-digit password reset OTP and emailing it to the registered user.

### Security Note
For security against user enumeration, the endpoint always returns a generic 200 OK success message regardless of whether the email exists in the database.
        """,
        request=ForgotPasswordSerializer,
        responses={
            200: OpenApiResponse(
                response=MessageResponseSerializer,
                description="Password reset code queued if email exists.",
            ),
        },
        examples=[
            OpenApiExample(
                name="Forgot Password Request",
                value={"email": "alex.morgan@manygym.com"},
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_password_reset(email=serializer.validated_data["email"])
        return Response(
            {"message": "If an account exists with this email, a password reset code has been dispatched."},
            status=status.HTTP_200_OK,
        )


class VerifyResetOTPView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Password Management"],
        summary="Verify Password Reset OTP",
        description="""
### Summary
Pre-checks if a provided password reset OTP is currently valid and unexpired before presenting the new password entry form.
        """,
        request=VerifyResetOTPSerializer,
        responses={
            200: OpenApiResponse(
                response=MessageResponseSerializer,
                description="OTP is valid.",
            ),
            400: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Invalid or expired reset code.",
            ),
        },
        examples=[
            OpenApiExample(
                name="Verify Reset OTP Payload",
                value={"email": "alex.morgan@manygym.com", "otp_code": "592104"},
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = VerifyResetOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        verify_password_reset_otp(
            email=serializer.validated_data["email"],
            otp_code=serializer.validated_data["otp_code"],
        )
        return Response(
            {"message": "OTP verification successful. You may now submit your new password."},
            status=status.HTTP_200_OK,
        )


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Password Management"],
        summary="Reset Password with OTP",
        description="""
### Summary
Resets the account password to the provided `new_password` after re-verifying the OTP code.

### Business Rules
- `new_password` must be at least 8 characters long.
- Marks the OTP as used immediately.
- User can now login with their new password.
        """,
        request=ResetPasswordSerializer,
        responses={
            200: OpenApiResponse(
                response=MessageResponseSerializer,
                description="Password successfully updated.",
            ),
            400: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Invalid OTP or password requirement not met.",
            ),
            404: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="User not found.",
            ),
        },
        examples=[
            OpenApiExample(
                name="Reset Password Request",
                value={
                    "email": "alex.morgan@manygym.com",
                    "otp_code": "592104",
                    "new_password": "NewSecretPassword2026!",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reset_password(
            email=serializer.validated_data["email"],
            otp_code=serializer.validated_data["otp_code"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response(
            {"message": "Password reset successful. Please login with your new credentials."},
            status=status.HTTP_200_OK,
        )


class UserProfileMeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Profile"],
        summary="Get Current User Profile & Accessible Gyms",
        description="""
### Summary
Retrieves personal profile data, current active token context, and the full list of gyms accessible to the authenticated user (both owned gyms and staff assignments).

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- **Authorization**: Accessible to any authenticated user.
        """,
        responses={
            200: OpenApiResponse(
                response=UserProfileMeResponseSerializer,
                description="Current user profile and gym access directory.",
            ),
            401: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Authentication credentials were not provided or are invalid.",
            ),
        },
    )
    def get(self, request):
        user = get_user_by_id(request.user.id) or request.user
        accessible_gyms = get_accessible_gyms_for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "current_context": {
                    "type": getattr(request, "token_context", "personal"),
                    "gym_id": getattr(request, "gym_id", None),
                    "scopes": getattr(request, "scopes", []),
                },
                "accessible_gyms": accessible_gyms,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        tags=["User Profile"],
        summary="Update Current User Profile",
        description="""
### Summary
Updates mutable personal profile attributes (first_name, last_name, phone, address, city, country, avatar, sex, date_of_birth, nationality).

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
        """,
        request=UpdateProfileSerializer,
        responses={
            200: OpenApiResponse(
                response=UserProfileMeResponseSerializer,
                description="Profile successfully updated.",
            ),
            400: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Validation failure on updated profile values.",
            ),
            401: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Authentication required.",
            ),
        },
        examples=[
            OpenApiExample(
                name="Profile Update Payload",
                value={
                    "first_name": "Alexandra",
                    "phone": "+14155559988",
                    "city": "San Francisco",
                    "country": "United States",
                    "sex": "female",
                    "nationality": "American",
                },
                request_only=True,
            )
        ],
    )
    def patch(self, request):
        serializer = UpdateProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_user = update_user_profile(user=request.user, **serializer.validated_data)
        return Response(
            {
                "message": "Profile updated successfully.",
                "user": UserSerializer(updated_user).data,
            },
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Password Management"],
        summary="Change Password",
        description="""
### Summary
Allows an authenticated logged-in user to change their password by validating their `current_password` and setting a `new_password`.

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
        """,
        request=ChangePasswordSerializer,
        responses={
            200: OpenApiResponse(
                response=MessageResponseSerializer,
                description="Password successfully changed.",
            ),
            400: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Current password does not match or new password is too weak.",
            ),
            401: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Authentication required.",
            ),
        },
        examples=[
            OpenApiExample(
                name="Change Password Payload",
                value={
                    "current_password": "SecurePassword2026!",
                    "new_password": "SuperSecureNewPassword2026!",
                },
                request_only=True,
            )
        ],
    )
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        change_password(
            user=request.user,
            current_password=serializer.validated_data["current_password"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response(
            {"message": "Password changed successfully."},
            status=status.HTTP_200_OK,
        )
