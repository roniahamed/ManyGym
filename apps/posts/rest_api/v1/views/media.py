import uuid
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.posts.selectors import get_post_media_by_id
from apps.posts.services import update_video_thumbnail
from apps.posts.rest_api.v1.serializers import (
    GymPostMediaSerializer,
    CustomVideoThumbnailSerializer,
)
from apps.posts.rest_api.v1.views.base import (
    resolve_post_gym,
    check_post_management_permission,
)
from common.exceptions import DomainValidationError
from common.serializers import ErrorDetailSerializer


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
