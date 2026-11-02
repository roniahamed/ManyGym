from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
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
    FollowUserItemSerializer,
    UserFollowActionResponseSerializer,
    FollowActionSerializer,
    FollowActionResponseSerializer,
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
    follow_user,
    unfollow_user,
)
from apps.gyms.services import (
    follow_gym,
    unfollow_gym,
)
from apps.users.selectors import (
    get_user_by_id,
    list_user_followers,
    list_user_following,
    is_following_user,
)
import uuid

from apps.gyms.models import Gym
from apps.users.models import User
from apps.authentication.services import issue_context_token
from apps.gyms.selectors import (
    get_accessible_gyms_for_user,
    list_gym_followers,
    list_user_followed_gyms,
    is_following_gym,
)
from apps.gyms.rest_api.v1.serializers import GymFollowerItemSerializer
from common.enums import TokenContextType
from common.exceptions import DomainValidationError, ResourceNotFoundError, PermissionDeniedError
from common.serializers import ErrorDetailSerializer, MessageResponseSerializer
from common.pagination import StandardResultsSetPagination



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
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @extend_schema(
        tags=["User Profile"],
        summary="Get Current User Profile & Accessible Gyms",
        description="""
### Summary
Retrieves personal profile data, current active token context, and the full list of gyms accessible to the authenticated user (both owned gyms and staff assignments).

### Context Awareness & Behavior
1. **Gym Context**: When the session token represents a specific gym context (`type: 'gym'`), `current_context` contains `gym_id`, `gym_name`, and `profile_picture_url`.
2. **Context Sorting**: The active gym is automatically sorted to the top of `accessible_gyms` (index 0) for seamless UI dropdown rendering.
3. **Personal Context**: In personal context (`type: 'personal'`), `gym_id`, `gym_name`, and `profile_picture_url` are `null`.

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- **Authorization**: Accessible to any authenticated user.
        """,
        responses={
            200: OpenApiResponse(
                response=UserProfileMeResponseSerializer,
                description="Current user profile and gym access directory.",
                examples=[
                    OpenApiExample(
                        name="Gym Context Example (Active Gym Sorted First)",
                        value={
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
                                    "avatar_url": "https://cdn.manygym.com/avatars/alex.jpg",
                                    "address": "123 Market Street",
                                    "city": "San Francisco",
                                    "country": "United States",
                                    "date_of_birth": "1994-06-15",
                                    "sex": "male",
                                    "nationality": "American",
                                },
                            },
                            "current_context": {
                                "type": "gym",
                                "gym_id": "31d57929-e58f-49b0-9bf7-fa5d07c08285",
                                "gym_name": "Apex Fitness Club",
                                "profile_picture_url": "https://cdn.manygym.com/gyms/apex.jpg",
                                "scopes": ["gym:read", "members:manage", "people_roles:manage"],
                            },
                            "accessible_gyms": [
                                {
                                    "gym_id": "31d57929-e58f-49b0-9bf7-fa5d07c08285",
                                    "name": "Apex Fitness Club",
                                    "role": "Owner",
                                    "is_owner": True,
                                    "primary_type": "general_fitness_gym",
                                    "profile_picture_url": "https://cdn.manygym.com/gyms/apex.jpg",
                                },
                                {
                                    "gym_id": "8f3b201a-1122-4a55-bcde-9922a1b2c3d4",
                                    "name": "CrossFit Box",
                                    "role": "Trainer",
                                    "is_owner": False,
                                    "primary_type": "crossfit_box",
                                    "profile_picture_url": "https://cdn.manygym.com/gyms/crossfit.jpg",
                                },
                            ],
                        },
                    ),
                    OpenApiExample(
                        name="Personal Context Example",
                        value={
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
                            "current_context": {
                                "type": "personal",
                                "gym_id": None,
                                "gym_name": None,
                                "profile_picture_url": None,
                                "scopes": [],
                            },
                            "accessible_gyms": [
                                {
                                    "gym_id": "31d57929-e58f-49b0-9bf7-fa5d07c08285",
                                    "name": "Apex Fitness Club",
                                    "role": "Owner",
                                    "is_owner": True,
                                    "primary_type": "general_fitness_gym",
                                    "profile_picture_url": "https://cdn.manygym.com/gyms/apex.jpg",
                                },
                            ],
                        },
                    ),
                ],
            ),
            401: OpenApiResponse(
                response=ErrorDetailSerializer,
                description="Authentication credentials were not provided or are invalid.",
            ),
        },
    )
    def get(self, request):
        user = request.user
        if not hasattr(user, "_profile_cache") and not hasattr(user, "profile"):
            user = get_user_by_id(request.user.id) or request.user
        accessible_gyms = get_accessible_gyms_for_user(user)

        current_gym_id = getattr(request, "gym_id", None)
        current_gym_item = None
        if current_gym_id:
            for gym in accessible_gyms:
                if str(gym.get("gym_id")) == str(current_gym_id):
                    current_gym_item = gym
                    break

            if current_gym_item:
                accessible_gyms.sort(
                    key=lambda g: 0 if str(g.get("gym_id")) == str(current_gym_id) else 1
                )

        return Response(
            {
                "user": UserSerializer(user).data,
                "current_context": {
                    "type": getattr(request, "token_context", "personal"),
                    "gym_id": current_gym_id,
                    "gym_name": current_gym_item.get("name") if current_gym_item else None,
                    "profile_picture_url": (
                        current_gym_item.get("profile_picture_url")
                        if current_gym_item
                        else None
                    ),
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

### File Upload Specifications (`avatar`)
- **Supported Content-Types**: `multipart/form-data` or `application/json`.
- **Accepted Formats**: `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.bmp`, `.gif`, `.tiff`, `.jfif`, `.avif`.
- **Maximum File Size**: 10MB.
- **Processing Behavior**: Synchronous. Camera/smartphone EXIF orientation is automatically corrected (prevents rotated/sideways photos), and the image is converted directly to optimized WebP (`.webp`) format.
- **Alternative**: An existing external image URL can be passed via `avatar_url`.

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
        validated_data = dict(serializer.validated_data)
        avatar = request.FILES.get("avatar") or request.FILES.get("avatar_file") or validated_data.get("avatar")
        if avatar:
            validated_data["avatar"] = avatar
        updated_user = update_user_profile(user=request.user, **validated_data)
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


class UserFollowToggleView(APIView):
    """
    API endpoint for following or unfollowing a public user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Social & Follow"],
        summary="Follow a User",
        request=None,
        description="Follows a target user if the target user account is public and active.",
        responses={
            201: OpenApiResponse(response=UserFollowActionResponseSerializer, description="Successfully followed user."),
            200: OpenApiResponse(response=UserFollowActionResponseSerializer, description="Already following user."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Invalid request (e.g. self-follow)."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Target user is private."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Target user not found."),
        },
    )
    def post(self, request, user_id):
        follow_obj, created = follow_user(follower=request.user, target_user_id=user_id)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        message = "Successfully followed user." if created else "Already following user."
        return Response(
            {
                "message": message,
                "is_following": True,
                "target_user_id": str(user_id),
            },
            status=status_code,
        )

    @extend_schema(
        tags=["User Social & Follow"],
        summary="Unfollow a User",
        description="Unfollows a target user that was previously followed.",
        responses={
            200: OpenApiResponse(response=UserFollowActionResponseSerializer, description="Successfully unfollowed user."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Invalid target user ID."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Not currently following user or user not found."),
        },
    )
    def delete(self, request, user_id):
        unfollow_user(follower=request.user, target_user_id=user_id)
        return Response(
            {
                "message": "Successfully unfollowed user.",
                "is_following": False,
                "target_user_id": str(user_id),
            },
            status=status.HTTP_200_OK,
        )


class UserFollowersListView(APIView):
    """
    API endpoint for listing followers of a specific user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Social & Follow"],
        summary="List User Followers",
        description="Lists all users who follow the specified user. Restricted if the target user is private.",
        responses={
            200: OpenApiResponse(response=FollowUserItemSerializer(many=True), description="List of user followers."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="User account is private."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="User not found."),
        },
    )
    def get(self, request, user_id):
        target = request.user if str(user_id) == str(request.user.id) else user_id
        followers_qs = list_user_followers(user_id=target, requesting_user=request.user)

        if request.query_params.get("page") or request.query_params.get("page_size"):
            paginator = StandardResultsSetPagination()
            page_results = paginator.paginate_queryset(followers_qs, request)
            data = [
                {
                    "user_id": f.follower.id,
                    "email": f.follower.email,
                    "first_name": f.follower.first_name,
                    "last_name": f.follower.last_name,
                    "full_name": f"{f.follower.first_name} {f.follower.last_name}".strip(),
                    "avatar_url": getattr(getattr(f.follower, "profile", None), "avatar_url", None),
                    "is_private": getattr(getattr(f.follower, "profile", None), "is_private", False),
                    "followed_at": f.created_at,
                }
                for f in page_results
            ]
            return paginator.get_paginated_response(FollowUserItemSerializer(data, many=True).data)

        data = [
            {
                "user_id": f.follower.id,
                "email": f.follower.email,
                "first_name": f.follower.first_name,
                "last_name": f.follower.last_name,
                "full_name": f"{f.follower.first_name} {f.follower.last_name}".strip(),
                "avatar_url": getattr(getattr(f.follower, "profile", None), "avatar_url", None),
                "is_private": getattr(getattr(f.follower, "profile", None), "is_private", False),
                "followed_at": f.created_at,
            }
            for f in followers_qs
        ]
        return Response(FollowUserItemSerializer(data, many=True).data, status=status.HTTP_200_OK)


class UserFollowingListView(APIView):
    """
    API endpoint for listing accounts followed by a specific user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Social & Follow"],
        summary="List User Following",
        description="Lists all users that the specified user is following. Restricted if the target user is private.",
        responses={
            200: OpenApiResponse(response=FollowUserItemSerializer(many=True), description="List of users followed."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="User account is private."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="User not found."),
        },
    )
    def get(self, request, user_id):
        target = request.user if str(user_id) == str(request.user.id) else user_id
        following_qs = list_user_following(user_id=target, requesting_user=request.user)

        if request.query_params.get("page") or request.query_params.get("page_size"):
            paginator = StandardResultsSetPagination()
            page_results = paginator.paginate_queryset(following_qs, request)
            data = [
                {
                    "user_id": f.followed_user.id,
                    "email": f.followed_user.email,
                    "first_name": f.followed_user.first_name,
                    "last_name": f.followed_user.last_name,
                    "full_name": f"{f.followed_user.first_name} {f.followed_user.last_name}".strip(),
                    "avatar_url": getattr(getattr(f.followed_user, "profile", None), "avatar_url", None),
                    "is_private": getattr(getattr(f.followed_user, "profile", None), "is_private", False),
                    "followed_at": f.created_at,
                }
                for f in page_results
            ]
            return paginator.get_paginated_response(FollowUserItemSerializer(data, many=True).data)

        data = [
            {
                "user_id": f.followed_user.id,
                "email": f.followed_user.email,
                "first_name": f.followed_user.first_name,
                "last_name": f.followed_user.last_name,
                "full_name": f"{f.followed_user.first_name} {f.followed_user.last_name}".strip(),
                "avatar_url": getattr(getattr(f.followed_user, "profile", None), "avatar_url", None),
                "is_private": getattr(getattr(f.followed_user, "profile", None), "is_private", False),
                "followed_at": f.created_at,
            }
            for f in following_qs
        ]
        return Response(FollowUserItemSerializer(data, many=True).data, status=status.HTTP_200_OK)


class ResolvedTarget(tuple):
    """
    Tuple subclass representing (target_type, target_uuid) while holding the loaded entity
    to eliminate redundant subsequent database round-trips.
    """
    def __new__(cls, target_type, target_uuid, entity=None):
        return super().__new__(cls, (target_type, target_uuid))

    def __init__(self, target_type, target_uuid, entity=None):
        self.target_type = target_type
        self.target_uuid = target_uuid
        self.entity = entity


def resolve_target_entity(target_id, target_type=None) -> ResolvedTarget:
    """
    Validates target_id and auto-detects whether the entity is a Gym or a User.
    Optimized with single query execution, field projections, and relationship prefetching.
    """
    if isinstance(target_id, Gym):
        return ResolvedTarget("gym", target_id.id, target_id)
    if isinstance(target_id, User):
        return ResolvedTarget("user", target_id.id, target_id)

    try:
        target_uuid = uuid.UUID(str(target_id))
    except (ValueError, TypeError, AttributeError):
        raise DomainValidationError("Invalid target ID format. Must be a valid UUID.")

    resolved_type = (target_type or "").strip().lower()

    if resolved_type == "gym":
        gym = (
            Gym.objects.select_related("settings")
            .only(
                "id",
                "name",
                "owner_user_id",
                "settings__id",
                "settings__is_deleted",
                "settings__is_deactivated",
                "settings__who_can_see_followers",
                "settings__who_can_see_following",
            )
            .filter(id=target_uuid)
            .first()
        )
        if not gym:
            raise ResourceNotFoundError("Target entity (Gym) not found.")
        return ResolvedTarget("gym", target_uuid, gym)

    if resolved_type == "user":
        user = (
            User.objects.select_related("profile")
            .only(
                "id",
                "first_name",
                "last_name",
                "is_active",
                "profile__id",
                "profile__is_private",
            )
            .filter(id=target_uuid)
            .first()
        )
        if not user:
            raise ResourceNotFoundError("Target entity (User) not found.")
        return ResolvedTarget("user", target_uuid, user)

    # Auto-detect whether target_id is a Gym or User in minimal DB round-trips
    gym = (
        Gym.objects.select_related("settings")
        .only(
            "id",
            "name",
            "owner_user_id",
            "settings__id",
            "settings__is_deleted",
            "settings__is_deactivated",
            "settings__who_can_see_followers",
            "settings__who_can_see_following",
        )
        .filter(id=target_uuid)
        .first()
    )
    if gym:
        return ResolvedTarget("gym", target_uuid, gym)

    user = (
        User.objects.select_related("profile")
        .only(
            "id",
            "first_name",
            "last_name",
            "is_active",
            "profile__id",
            "profile__is_private",
        )
        .filter(id=target_uuid)
        .first()
    )
    if user:
        return ResolvedTarget("user", target_uuid, user)

    raise ResourceNotFoundError("Target entity (User or Gym) not found.")


class UnifiedFollowView(APIView):
    """
    Unified API endpoint for following and unfollowing Users or Gyms.
    Target entity type (user vs gym) is automatically detected if omitted.
    Supports both POST (follow/unfollow) and DELETE (unfollow).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["Unified Social Follow"],
        summary="Follow or Unfollow a User or Gym",
        description="""
### Summary
Unified single endpoint to follow or unfollow any public User or Gym.

### Auto-Detection
`target_type` is **automatically detected** from the database (whether UUID is a Gym or User).

### Request
- Pass `target_id` (or `id`) in JSON body (`{"target_id": "<uuid>"}`) or directly in URL path (`/api/v1/follows/<target_id>/`).
- Optional `action`: `"follow"` (default) or `"unfollow"`.
        """,
        request=FollowActionSerializer,
        responses={
            201: OpenApiResponse(response=FollowActionResponseSerializer, description="Successfully followed target."),
            200: OpenApiResponse(response=FollowActionResponseSerializer, description="Successfully unfollowed target or already following."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure or self-follow attempt."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Target user is private or user is blocked by gym."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Target entity not found."),
        },
    )
    def post(self, request, target_id=None):
        data = {}
        if request.query_params:
            data.update(request.query_params.dict())
        if request.data and isinstance(request.data, dict):
            data.update(request.data)
        if target_id:
            data["target_id"] = str(target_id)
        serializer = FollowActionSerializer(data=data, context={"target_id": target_id})
        serializer.is_valid(raise_exception=True)

        raw_id = serializer.validated_data["target_id"]
        raw_type = serializer.validated_data.get("target_type")
        action = serializer.validated_data.get("action", "follow").lower()

        target_info = resolve_target_entity(raw_id, raw_type)
        target_type, resolved_id = target_info
        entity = getattr(target_info, "entity", None)

        if action == "unfollow":
            return self._perform_unfollow(request.user, target_type, resolved_id)
        return self._perform_follow(request.user, target_type, entity or resolved_id)

    @extend_schema(
        tags=["Unified Social Follow"],
        summary="Unfollow a User or Gym",
        description="""
### Summary
Unfollows a previously followed User or Gym.

### Auto-Detection
`target_type` is **automatically detected**.

### Parameters
Parameters can be sent via:
1. URL path: `/api/v1/follows/<target_id>/`
2. JSON body: `{"target_id": "<uuid>"}`
3. Query param: `?target_id=<uuid>`
        """,
        request=FollowActionSerializer,
        responses={
            200: OpenApiResponse(response=FollowActionResponseSerializer, description="Successfully unfollowed target."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Not currently following target or target not found."),
        },
    )
    def delete(self, request, target_id=None):
        data = {}
        if request.query_params:
            data.update(request.query_params.dict())
        if request.data and isinstance(request.data, dict):
            data.update(request.data)
        if target_id:
            data["target_id"] = str(target_id)
        serializer = FollowActionSerializer(data=data, context={"target_id": target_id})
        serializer.is_valid(raise_exception=True)

        raw_id = serializer.validated_data["target_id"]
        raw_type = serializer.validated_data.get("target_type")

        target_info = resolve_target_entity(raw_id, raw_type)
        target_type, resolved_id = target_info
        return self._perform_unfollow(request.user, target_type, resolved_id)

    @extend_schema(
        tags=["Unified Social Follow"],
        summary="Get Followers or Following List",
        description="""
### Summary
- If `target_id` is supplied (in URL path or query param), returns the **followers list** of the target User or Gym. Target entity type is **automatically detected**. Respects target privacy settings (returns 403 if restricted).
- If `target_id` is omitted, returns the list of entities (Users and Gyms) followed by the current authenticated user.
        """,
        responses={
            200: OpenApiResponse(description="Followers or following list."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Target is private or restricted by settings."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Target entity not found."),
        },
    )
    def get(self, request, target_id=None):
        raw_id = target_id or request.query_params.get("target_id") or request.query_params.get("id")
        if not raw_id:
            # Return current user's followed accounts (passing request.user eliminates extra DB query)
            user_following_qs = list_user_following(user_id=request.user, requesting_user=request.user)
            followed_gyms_qs = list_user_followed_gyms(user=request.user)

            if request.query_params.get("page") or request.query_params.get("page_size"):
                paginator = StandardResultsSetPagination()
                page_users = paginator.paginate_queryset(user_following_qs, request)
                page_gyms = list(followed_gyms_qs[:paginator.get_page_size(request) or 20])
                users_data = [
                    {
                        "user_id": f.followed_user.id,
                        "email": f.followed_user.email,
                        "first_name": f.followed_user.first_name,
                        "last_name": f.followed_user.last_name,
                        "full_name": f"{f.followed_user.first_name} {f.followed_user.last_name}".strip(),
                        "avatar_url": getattr(getattr(f.followed_user, "profile", None), "avatar_url", None),
                        "is_private": getattr(getattr(f.followed_user, "profile", None), "is_private", False),
                        "followed_at": f.created_at,
                    }
                    for f in page_users
                ]
                gyms_data = [
                    {
                        "gym_id": f.gym.id,
                        "name": f.gym.name,
                        "primary_type": f.gym.primary_type,
                        "profile_picture_url": f.gym.profile_picture_url,
                        "followed_at": f.created_at,
                    }
                    for f in page_gyms
                ]
                return paginator.get_paginated_response({
                    "followed_users": users_data,
                    "followed_gyms": gyms_data,
                    "total_followed_users": user_following_qs.count(),
                    "total_followed_gyms": followed_gyms_qs.count(),
                })

            users_data = [
                {
                    "user_id": f.followed_user.id,
                    "email": f.followed_user.email,
                    "first_name": f.followed_user.first_name,
                    "last_name": f.followed_user.last_name,
                    "full_name": f"{f.followed_user.first_name} {f.followed_user.last_name}".strip(),
                    "avatar_url": getattr(getattr(f.followed_user, "profile", None), "avatar_url", None),
                    "is_private": getattr(getattr(f.followed_user, "profile", None), "is_private", False),
                    "followed_at": f.created_at,
                }
                for f in user_following_qs
            ]
            gyms_data = [
                {
                    "gym_id": f.gym.id,
                    "name": f.gym.name,
                    "primary_type": f.gym.primary_type,
                    "profile_picture_url": f.gym.profile_picture_url,
                    "followed_at": f.created_at,
                }
                for f in followed_gyms_qs
            ]
            return Response(
                {
                    "followed_users": users_data,
                    "followed_gyms": gyms_data,
                    "total_followed_users": len(users_data),
                    "total_followed_gyms": len(gyms_data),
                },
                status=status.HTTP_200_OK,
            )

        target_info = resolve_target_entity(raw_id)
        target_type, resolved_id = target_info
        entity = getattr(target_info, "entity", None)

        if target_type == "user":
            followers_qs = list_user_followers(user_id=entity or resolved_id, requesting_user=request.user)

            if request.query_params.get("page") or request.query_params.get("page_size"):
                paginator = StandardResultsSetPagination()
                page_results = paginator.paginate_queryset(followers_qs, request)
                data = [
                    {
                        "user_id": f.follower.id,
                        "email": f.follower.email,
                        "first_name": f.follower.first_name,
                        "last_name": f.follower.last_name,
                        "full_name": f"{f.follower.first_name} {f.follower.last_name}".strip(),
                        "avatar_url": getattr(getattr(f.follower, "profile", None), "avatar_url", None),
                        "is_private": getattr(getattr(f.follower, "profile", None), "is_private", False),
                        "followed_at": f.created_at,
                    }
                    for f in page_results
                ]
                is_following = is_following_user(request.user, resolved_id)
                return paginator.get_paginated_response({
                    "target_type": "user",
                    "target_id": str(resolved_id),
                    "followers_count": paginator.page.paginator.count,
                    "is_following": is_following,
                    "followers": data,
                })

            data = [
                {
                    "user_id": f.follower.id,
                    "email": f.follower.email,
                    "first_name": f.follower.first_name,
                    "last_name": f.follower.last_name,
                    "full_name": f"{f.follower.first_name} {f.follower.last_name}".strip(),
                    "avatar_url": getattr(getattr(f.follower, "profile", None), "avatar_url", None),
                    "is_private": getattr(getattr(f.follower, "profile", None), "is_private", False),
                    "followed_at": f.created_at,
                }
                for f in followers_qs
            ]
            if request.user.id == resolved_id:
                is_following = False
            else:
                user_in_data = any(item["user_id"] == request.user.id for item in data)
                is_following = True if user_in_data else is_following_user(request.user, resolved_id)

            return Response(
                {
                    "target_type": "user",
                    "target_id": str(resolved_id),
                    "followers_count": len(data),
                    "is_following": is_following,
                    "followers": data,
                },
                status=status.HTTP_200_OK,
            )

        # target_type == "gym"
        followers_qs = list_gym_followers(gym_id=entity or resolved_id, requesting_user=request.user)

        if request.query_params.get("page") or request.query_params.get("page_size"):
            paginator = StandardResultsSetPagination()
            page_results = paginator.paginate_queryset(followers_qs, request)
            data = [
                {
                    "user_id": f.user.id,
                    "email": f.user.email,
                    "first_name": f.user.first_name,
                    "last_name": f.user.last_name,
                    "full_name": f"{f.user.first_name} {f.user.last_name}".strip(),
                    "avatar_url": getattr(getattr(f.user, "profile", None), "avatar_url", None),
                    "followed_at": f.created_at,
                }
                for f in page_results
            ]
            return paginator.get_paginated_response({
                "target_type": "gym",
                "target_id": str(resolved_id),
                "followers_count": paginator.page.paginator.count,
                "is_following": is_following_gym(request.user, resolved_id),
                "followers": data,
            })

        data = [
            {
                "user_id": f.user.id,
                "email": f.user.email,
                "first_name": f.user.first_name,
                "last_name": f.user.last_name,
                "full_name": f"{f.user.first_name} {f.user.last_name}".strip(),
                "avatar_url": getattr(getattr(f.user, "profile", None), "avatar_url", None),
                "followed_at": f.created_at,
            }
            for f in followers_qs
        ]
        user_in_data = any(item["user_id"] == request.user.id for item in data)
        is_following = True if user_in_data else is_following_gym(request.user, resolved_id)

        return Response(
            {
                "target_type": "gym",
                "target_id": str(resolved_id),
                "followers_count": len(data),
                "is_following": is_following,
                "followers": data,
            },
            status=status.HTTP_200_OK,
        )

    def _perform_follow(self, user, target_type: str, target_id):
        if target_type == "user":
            follow_obj, created = follow_user(follower=user, target_user_id=target_id)
            target_name = f"{follow_obj.followed_user.first_name} {follow_obj.followed_user.last_name}".strip()
            status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            message = "Successfully followed user." if created else "Already following user."
        elif target_type == "gym":
            follow_obj, created = follow_gym(user=user, gym_id=target_id)
            target_name = follow_obj.gym.name
            status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            message = "Successfully followed gym." if created else "Already following gym."
        else:
            raise DomainValidationError(f"Invalid target_type '{target_type}'. Must be 'user' or 'gym'.")

        return Response(
            {
                "message": message,
                "is_following": True,
                "target_type": target_type,
                "target_id": str(getattr(target_id, "id", target_id)),
                "target_name": target_name,
            },
            status=status_code,
        )

    def _perform_unfollow(self, user, target_type: str, target_id):
        resolved_uuid = getattr(target_id, "id", target_id)
        if target_type == "user":
            unfollow_user(follower=user, target_user_id=resolved_uuid)
            message = "Successfully unfollowed user."
        elif target_type == "gym":
            unfollow_gym(user=user, gym_id=resolved_uuid)
            message = "Successfully unfollowed gym."
        else:
            raise DomainValidationError(f"Invalid target_type '{target_type}'. Must be 'user' or 'gym'.")

        return Response(
            {
                "message": message,
                "is_following": False,
                "target_type": target_type,
                "target_id": str(resolved_uuid),
                "target_name": None,
            },
            status=status.HTTP_200_OK,
        )



