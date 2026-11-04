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
    UserAboutResponseSerializer,
    UserAboutUpdateSerializer,
    UserEducationSerializer,
    UserEducationInputSerializer,
    UserSocialLinkSerializer,
    UserSocialLinkInputSerializer,
)
from apps.users.services import (
    update_user_profile,
    update_user_about,
    create_user_education,
    update_user_education,
    delete_user_education,
    create_user_social_link,
    update_user_social_link,
    delete_user_social_link,
)
from apps.users.selectors import (
    get_user_by_id,
    get_user_about_profile,
    list_user_educations,
    get_user_education_by_id,
    list_user_social_links,
    get_user_social_link_by_id,
)
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


class UserAboutMeView(APIView):
    """
    API endpoint for retrieving and updating the authenticated user's Public Profile -> About details.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserAboutResponseSerializer

    @extend_schema(
        tags=["User Profile -> About"],
        summary="Get Current User 'About' Profile",
        description="""
### Summary
Retrieves the current user's complete Public Profile -> About details across all 5 sections:
1. **Personal Details**: Current address, home town, date of birth, gender.
2. **Education**: University name, from year, till year (optional if continuing), subject, graduated status.
3. **Hobbies**: List of user hobbies (free text items).
4. **Contact Info**: Phone number, social links (platform + link URL), and registered account email (read-only).
5. **Details About You**: About you description (max 320 chars) and favourite quote (max 160 chars).

### Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- **Authorization**: Current authenticated user.
        """,
        responses={
            200: OpenApiResponse(
                response=UserAboutResponseSerializer,
                description="Complete user about profile data.",
                examples=[
                    OpenApiExample(
                        name="Full About Profile Example",
                        value={
                            "user_id": "b3e0c0fa-2384-48f8-b3d5-e357e62a0a20",
                            "first_name": "Alex",
                            "last_name": "Morgan",
                            "avatar_url": "https://cdn.manygym.com/avatars/alex.webp",
                            "is_private": False,
                            "personal_details": {
                                "current_address": "123 Market Street, Apt 4B",
                                "home_town": "San Francisco",
                                "date_of_birth": "1994-06-15",
                                "gender": "male",
                            },
                            "education_list": [
                                {
                                    "id": "18c2f1ab-2233-4455-6677-8899aabbccdd",
                                    "university_name": "Stanford University",
                                    "from_year": "2012-09-01",
                                    "till_year": "2016-06-15",
                                    "subject": "Kinesiology and Sports Science",
                                    "graduated": True,
                                    "created_at": "2026-10-12T12:00:00Z",
                                    "updated_at": "2026-10-12T12:00:00Z",
                                }
                            ],
                            "hobbies": [
                                "Weightlifting",
                                "Trail Running",
                                "Nutrition Research",
                            ],
                            "contact_info": {
                                "social_links": [
                                    {
                                        "id": "29d4e2bc-3344-5566-7788-99aabbccddee",
                                        "platform": "instagram",
                                        "link": "https://instagram.com/alex_fitness",
                                        "created_at": "2026-10-12T12:00:00Z",
                                        "updated_at": "2026-10-12T12:00:00Z",
                                    }
                                ],
                                "phone_number": "+14155552671",
                                "email": "alex.morgan@manygym.com",
                            },
                            "details_about_you": {
                                "about_you": "Dedicated strength athlete and fitness coach helping members transform their physical capacity and mental endurance.",
                                "favourite_quote": "Discipline is choosing between what you want now and what you want most.",
                            },
                        },
                    )
                ],
            ),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication credentials required."),
        },
    )
    def get(self, request):
        user = get_user_about_profile(request.user, requesting_user=request.user)
        return Response(UserAboutResponseSerializer(user).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["User Profile -> About"],
        summary="Update Current User 'About' Profile",
        description="""
### Summary
Updates the current user's Public Profile -> About details.
Supports both structured nested sections (`personal_details`, `education_list`, `hobbies`, `contact_info`, `details_about_you`) and direct flat properties.

### Validation Invariants
- **Email**: Immutable. Registered account email cannot be changed.
- **About You**: Maximum 320 characters.
- **Favourite Quote**: Maximum 160 characters.
- **Education Dates**: `till_year` cannot be earlier than `from_year`.
- **Social Platforms**: Must be one of the supported platform identifiers (`facebook`, `instagram`, `twitter_x`, `linkedin`, `youtube`, `tiktok`, `github`, `website`, `other`).
- **Gender**: Must be one of the supported enum choices (`male`, `female`, `other`, `prefer_not_to_say`).
        """,
        request=UserAboutUpdateSerializer,
        responses={
            200: OpenApiResponse(response=UserAboutResponseSerializer, description="About profile successfully updated."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
        },
        examples=[
            OpenApiExample(
                name="Update About Profile Payload (Nested Structure)",
                value={
                    "personal_details": {
                        "current_address": "450 Broadway, Apt 12",
                        "home_town": "Austin, Texas",
                        "date_of_birth": "1993-08-20",
                        "gender": "male",
                    },
                    "education_list": [
                        {
                            "university_name": "University of Texas at Austin",
                            "from_year": "2011-09-01",
                            "till_year": "2015-05-20",
                            "subject": "Exercise Physiology",
                            "graduated": True,
                        }
                    ],
                    "hobbies": ["Powerlifting", "Hiking", "Reading"],
                    "contact_info": {
                        "phone_number": "+15125550198",
                        "social_links": [
                            {"platform": "instagram", "link": "https://instagram.com/alex_lifts"},
                            {"platform": "linkedin", "link": "https://linkedin.com/in/alex-morgan"},
                        ],
                    },
                    "details_about_you": {
                        "about_you": "Competitive powerlifter and strength conditioning coach.",
                        "favourite_quote": "Consistency over intensity.",
                    },
                },
                request_only=True,
            ),
            OpenApiExample(
                name="Update About Profile Payload (Flat Structure)",
                value={
                    "current_address": "450 Broadway, Apt 12",
                    "home_town": "Austin, Texas",
                    "date_of_birth": "1993-08-20",
                    "gender": "male",
                    "hobbies": ["Powerlifting", "Hiking"],
                    "phone_number": "+15125550198",
                    "about_you": "Competitive powerlifter and coach.",
                    "favourite_quote": "Consistency over intensity.",
                },
                request_only=True,
            ),
        ],
    )
    def patch(self, request):
        serializer = UserAboutUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_user = update_user_about(request.user, **serializer.validated_data)
        # Reload with prefetch for clean response representation
        preloaded_user = get_user_about_profile(updated_user, requesting_user=request.user)
        return Response(UserAboutResponseSerializer(preloaded_user).data, status=status.HTTP_200_OK)

    def put(self, request):
        return self.patch(request)


class UserPublicAboutView(APIView):
    """
    API endpoint for viewing another user's Public Profile -> About details.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = UserAboutResponseSerializer

    @extend_schema(
        tags=["User Profile -> About"],
        summary="Get Target User Public 'About' Profile",
        description="""
### Summary
Retrieves the public "About" section for a specific user by UUID.

### Privacy & Access Rules
- **Soft-Deleted**: Returns `404 Not Found`.
- **Deactivated**: Returns `400 Bad Request` unless viewed by the account owner.
- **Blocked Users**: Returns `403 Forbidden` if the target user has blocked the requester.
- **Private Profiles**: Returns `403 Forbidden` if `is_private=True` and requester is not following the target user.
        """,
        responses={
            200: OpenApiResponse(response=UserAboutResponseSerializer, description="Public about profile."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Target account is deactivated."),
            401: OpenApiResponse(response=ErrorDetailSerializer, description="Authentication required."),
            403: OpenApiResponse(response=ErrorDetailSerializer, description="Target user is private or has blocked you."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="User not found."),
        },
    )
    def get(self, request, user_id):
        user = get_user_about_profile(user_id, requesting_user=request.user)
        return Response(UserAboutResponseSerializer(user).data, status=status.HTTP_200_OK)


class UserEducationListCreateView(APIView):
    """
    API endpoint for listing and creating education records for the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Profile -> Education"],
        summary="List User Education Records",
        responses={200: OpenApiResponse(response=UserEducationSerializer(many=True))},
    )
    def get(self, request):
        educations = list_user_educations(request.user)
        return Response(UserEducationSerializer(educations, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["User Profile -> Education"],
        summary="Create User Education Record",
        request=UserEducationInputSerializer,
        responses={
            201: OpenApiResponse(response=UserEducationSerializer, description="Education created."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
        },
    )
    def post(self, request):
        serializer = UserEducationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("id", None)
        edu = create_user_education(user=request.user, **data)
        return Response(UserEducationSerializer(edu).data, status=status.HTTP_201_CREATED)


class UserEducationDetailView(APIView):
    """
    API endpoint for updating or deleting an individual education record.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Profile -> Education"],
        summary="Update User Education Record",
        request=UserEducationInputSerializer,
        responses={
            200: OpenApiResponse(response=UserEducationSerializer, description="Education updated."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Record not found."),
        },
    )
    def patch(self, request, education_id):
        serializer = UserEducationInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("id", None)
        edu = update_user_education(user=request.user, education_id=education_id, **data)
        return Response(UserEducationSerializer(edu).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["User Profile -> Education"],
        summary="Delete User Education Record",
        responses={
            200: OpenApiResponse(description="Education successfully deleted."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Record not found."),
        },
    )
    def delete(self, request, education_id):
        delete_user_education(user=request.user, education_id=education_id)
        return Response({"message": "Education record deleted successfully."}, status=status.HTTP_200_OK)


class UserSocialLinkListCreateView(APIView):
    """
    API endpoint for listing and creating social links for the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Profile -> Social Links"],
        summary="List User Social Links",
        responses={200: OpenApiResponse(response=UserSocialLinkSerializer(many=True))},
    )
    def get(self, request):
        links = list_user_social_links(request.user)
        return Response(UserSocialLinkSerializer(links, many=True).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["User Profile -> Social Links"],
        summary="Create User Social Link",
        request=UserSocialLinkInputSerializer,
        responses={
            201: OpenApiResponse(response=UserSocialLinkSerializer, description="Social link created."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
        },
    )
    def post(self, request):
        serializer = UserSocialLinkInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("id", None)
        link = create_user_social_link(user=request.user, **data)
        return Response(UserSocialLinkSerializer(link).data, status=status.HTTP_201_CREATED)


class UserSocialLinkDetailView(APIView):
    """
    API endpoint for updating or deleting an individual social link.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["User Profile -> Social Links"],
        summary="Update User Social Link",
        request=UserSocialLinkInputSerializer,
        responses={
            200: OpenApiResponse(response=UserSocialLinkSerializer, description="Social link updated."),
            400: OpenApiResponse(response=ErrorDetailSerializer, description="Validation failure."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Record not found."),
        },
    )
    def patch(self, request, link_id):
        serializer = UserSocialLinkInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("id", None)
        link = update_user_social_link(user=request.user, link_id=link_id, **data)
        return Response(UserSocialLinkSerializer(link).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["User Profile -> Social Links"],
        summary="Delete User Social Link",
        responses={
            200: OpenApiResponse(description="Social link successfully deleted."),
            404: OpenApiResponse(response=ErrorDetailSerializer, description="Record not found."),
        },
    )
    def delete(self, request, link_id):
        delete_user_social_link(user=request.user, link_id=link_id)
        return Response({"message": "Social link deleted successfully."}, status=status.HTTP_200_OK)
