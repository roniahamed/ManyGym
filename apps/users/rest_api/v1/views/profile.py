from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample

from apps.users.rest_api.v1.serializers import (
    UpdateProfileSerializer,
    UserSerializer,
    UserProfileMeResponseSerializer,
)
from apps.users.services import update_user_profile
from apps.users.selectors import get_user_by_id
from apps.gyms.selectors import get_accessible_gyms_for_user
from common.serializers import ErrorDetailSerializer


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
