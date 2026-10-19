import uuid
from django.db.models import Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.gyms.models import Gym
from apps.access_control.models import GymStaffAssignment
from apps.members.models import Member
from apps.posts.models import GymPost, GymPostMedia
from apps.posts.selectors import (
    list_gym_feed,
    get_post_detail,
    get_post_media_by_id,
)
from apps.posts.services import (
    create_post,
    update_post,
    delete_post,
    update_video_thumbnail,
)
from apps.posts.rest_api.v1.serializers import (
    GymPostListSerializer,
    GymPostDetailSerializer,
    GymPostCreateSerializer,
    GymPostUpdateSerializer,
    GymPostMediaSerializer,
    CustomVideoThumbnailSerializer,
)
from common.pagination import StandardResultsSetPagination
from common.enums import StaffStatus
from common.exceptions import (
    DomainValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
)
from common.serializers import ErrorDetailSerializer


def resolve_post_gym(request) -> Gym:
    """Helper to determine target gym from query param, active JWT context, or request body."""
    cached = getattr(request, "_resolved_gym", None)
    if cached is not None:
        return cached

    gym_id = (
        request.query_params.get("gym_id")
        or getattr(request, "gym_id", None)
        or (request.data.get("gym_id") if isinstance(request.data, dict) else None)
    )
    if not gym_id:
        raise DomainValidationError("An active Gym context token or 'gym_id' parameter is required.")
    try:
        uuid.UUID(str(gym_id))
        gym = Gym.objects.only("id", "owner_user_id", "name", "timezone").get(id=gym_id)
    except (Gym.DoesNotExist, ValueError, AttributeError):
        raise ResourceNotFoundError("Gym not found.")
    request._resolved_gym = gym
    return gym


def check_user_is_member_or_staff(request, gym: Gym) -> bool:
    """Returns True if the requesting user is the gym owner, staff member, or active member."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return False

    if gym.owner_user_id == user.id or user.is_superuser:
        return True

    # Active staff check
    if GymStaffAssignment.objects.filter(gym=gym, user=user, status=StaffStatus.ACTIVE).exists():
        return True

    # Active gym member check
    if Member.objects.filter(gym=gym).filter(Q(email=user.email) | Q(user=user)).exists():
        return True

    return False


def check_post_management_permission(request, gym: Gym) -> None:
    """Enforces that only gym owner, superuser, or staff with 'posts:manage' scope can mutate posts."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        raise PermissionDeniedError("Authentication credentials were not provided.")

    if gym.owner_user_id == user.id or user.is_superuser:
        return

    assignment = GymStaffAssignment.objects.filter(
        gym=gym,
        user=user,
        status=StaffStatus.ACTIVE,
    ).first()

    if not assignment:
        raise PermissionDeniedError("You are not an active staff member of this gym.")

    if not assignment.role:
        raise PermissionDeniedError("You do not have permission to manage community posts.")

    has_perm = assignment.role.permissions.filter(scope_code="posts:manage").exists()
    if not has_perm:
        raise PermissionDeniedError("Missing required permission scope 'posts:manage'.")


# ==============================================================================
# COMMUNITY FEED VIEWS
# ==============================================================================

class GymFeedView(APIView):
    """
    List gym community feed posts or publish a new post with text and media.
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [AllowAny()]

    @extend_schema(
        tags=["Community Feed"],
        summary="List Gym Community Feed",
        description="Retrieves community posts for a gym. Unauthenticated guests and non-members see only public posts; verified members and staff see both public and members_only posts.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=True),
            OpenApiParameter(name="privacy", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="search", type=str, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY, required=False),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: GymPostListSerializer(many=True),
            400: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request):
        gym = resolve_post_gym(request)
        is_member_or_staff = check_user_is_member_or_staff(request, gym)

        privacy = request.query_params.get("privacy")
        search = request.query_params.get("search")

        qs = list_gym_feed(
            gym=gym,
            is_member_or_staff=is_member_or_staff,
            privacy_filter=privacy,
            search=search,
        )

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request)
        if page is not None:
            serializer = GymPostListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = GymPostListSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Community Feed"],
        summary="Create Community Post",
        description="Creates a new community post with optional text and media attachments (pictures or videos). Requires 'posts:manage' scope.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=GymPostCreateSerializer,
        responses={
            201: GymPostDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
        },
    )
    def post(self, request):
        gym = resolve_post_gym(request)
        check_post_management_permission(request, gym)

        serializer = GymPostCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Gather any uploaded files (support multipart 'media_files' or 'files')
        media_files = request.FILES.getlist("media_files") or request.FILES.getlist("files")

        post = create_post(
            gym=gym,
            author_user=request.user,
            content_text=data.get("content_text"),
            privacy=data.get("privacy"),
            media_files=media_files,
            media_items=data.get("media_items"),
        )

        loaded_post = get_post_detail(gym=gym, post_id=post.id, is_member_or_staff=True)
        return Response(GymPostDetailSerializer(loaded_post).data, status=status.HTTP_201_CREATED)


class GymPostDetailView(APIView):
    """
    Retrieve, update, or delete a single gym community post.
    """
    def get_permissions(self):
        if self.request.method in ("PATCH", "DELETE"):
            return [IsAuthenticated()]
        return [AllowAny()]

    @extend_schema(
        tags=["Community Feed"],
        summary="Get Post Detail",
        description="Retrieves a single community post dossier with all attached media.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=True),
        ],
        responses={
            200: GymPostDetailSerializer,
            400: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def get(self, request, post_id: uuid.UUID):
        gym = resolve_post_gym(request)
        is_member_or_staff = check_user_is_member_or_staff(request, gym)

        post = get_post_detail(gym=gym, post_id=post_id, is_member_or_staff=is_member_or_staff)
        return Response(GymPostDetailSerializer(post).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Community Feed"],
        summary="Update Community Post",
        description="Updates post text, privacy level, or reorders media attachments. Requires 'posts:manage' scope.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=GymPostUpdateSerializer,
        responses={
            200: GymPostDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def patch(self, request, post_id: uuid.UUID):
        gym = resolve_post_gym(request)
        check_post_management_permission(request, gym)

        post = get_post_detail(gym=gym, post_id=post_id, is_member_or_staff=True)
        serializer = GymPostUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        update_post(
            post=post,
            content_text=data.get("content_text"),
            privacy=data.get("privacy"),
            media_order=data.get("media_order"),
        )

        loaded_post = get_post_detail(gym=gym, post_id=post.id, is_member_or_staff=True)
        return Response(GymPostDetailSerializer(loaded_post).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["Community Feed"],
        summary="Delete Community Post",
        description="Permanently deletes a gym community post and its associated media assets. Requires 'posts:manage' scope.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        responses={
            200: ErrorDetailSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def delete(self, request, post_id: uuid.UUID):
        gym = resolve_post_gym(request)
        check_post_management_permission(request, gym)

        post = get_post_detail(gym=gym, post_id=post_id, is_member_or_staff=True)
        delete_post(post)
        return Response({"message": "Post deleted successfully."}, status=status.HTTP_200_OK)


class GymPostMediaThumbnailView(APIView):
    """
    Custom video thumbnail replacement for post video attachments.
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        tags=["Community Feed"],
        summary="Upload Custom Video Thumbnail",
        description="Allows gym staff to replace the auto-generated poster frame of a video post with a custom image. Requires 'posts:manage' scope.",
        parameters=[
            OpenApiParameter(name="gym_id", type=str, location=OpenApiParameter.QUERY, required=False),
        ],
        request=CustomVideoThumbnailSerializer,
        responses={
            200: GymPostMediaSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            403: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def patch(self, request, post_id: uuid.UUID, media_id: uuid.UUID):
        gym = resolve_post_gym(request)
        check_post_management_permission(request, gym)

        media = get_post_media_by_id(gym=gym, post_id=post_id, media_id=media_id)

        file = request.FILES.get("thumbnail_image") or request.FILES.get("file")
        if not file:
            raise DomainValidationError("A 'thumbnail_image' file is required.")

        updated_media = update_video_thumbnail(post_media=media, custom_thumbnail_file=file)
        return Response(GymPostMediaSerializer(updated_media).data, status=status.HTTP_200_OK)
