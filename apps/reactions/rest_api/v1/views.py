import uuid
from typing import Any, Dict, Optional, Tuple

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.gyms.models import Gym, GymSetting
from apps.reactions.models import Reaction, ReactionItem
from apps.reactions.permissions import CanReactAsGymPermission
from apps.reactions.rest_api.v1.serializers import (
    ReactionActionResponseSerializer,
    ReactionDetailSerializer,
    ReactionInputSerializer,
    ReactionItemSerializer,
    ReactionSummarySerializer,
)
from apps.reactions.selectors import (
    get_reaction_by_id,
    get_target_reaction_summary,
    list_reaction_items,
    list_reactions_for_target,
)
from apps.reactions.services import remove_reaction, toggle_or_set_reaction
from common.enums import PostOwnerTypeEnum, TokenContextType
from common.exceptions import DomainValidationError, PermissionDeniedError, ResourceNotFoundError
from common.pagination import StandardResultsSetPagination
from common.serializers import ErrorDetailSerializer


def _resolve_gym(request, gym_id: Any) -> Gym:
    try:
        gym_uuid = uuid.UUID(str(gym_id))
        gym = Gym.objects.select_related("settings").get(id=gym_uuid)
    except (Gym.DoesNotExist, ValueError, TypeError, AttributeError):
        raise ResourceNotFoundError("Gym not found.")

    setting = getattr(gym, "settings", None) or GymSetting.objects.filter(gym=gym).first()
    if setting and setting.is_deleted:
        raise ResourceNotFoundError("Gym not found.")
    return gym


def _resolve_reaction_actor_context(
    request,
    data_owner_type: Optional[str] = None,
    data_gym_id: Any = None,
) -> Tuple[str, Optional[Gym]]:
    """Resolves owner_type ('user' or 'gym') and gym entity from body or JWT token context."""
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        setting = user.get_settings()
        if setting.is_deleted or setting.is_deactivated:
            raise PermissionDeniedError("Your account is deactivated or deleted.")

    if data_owner_type == PostOwnerTypeEnum.GYM or data_gym_id:
        explicit_gym_id = data_gym_id or getattr(request, "gym_id", None)
        if not explicit_gym_id:
            raise DomainValidationError("A valid 'gym_id' is required when owner_type='gym'.")
        gym = _resolve_gym(request, explicit_gym_id)
        return PostOwnerTypeEnum.GYM, gym

    token_context = getattr(request, "token_context", TokenContextType.PERSONAL)
    token_gym_id = getattr(request, "gym_id", None)
    if token_context == TokenContextType.GYM and token_gym_id:
        gym = _resolve_gym(request, token_gym_id)
        return PostOwnerTypeEnum.GYM, gym

    return PostOwnerTypeEnum.USER, None


class ReactionItemListView(APIView):
    """
    Lists all active reaction items from the master reaction catalog.
    Public endpoint.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        summary="List available reaction items",
        description="Returns the active catalog of reactions (emojis, labels, and codes) including 😊 and 😆.",
        responses={200: ReactionItemSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        items = list_reaction_items(active_only=True)
        serializer = ReactionItemSerializer(items, many=True)
        return Response({
            "count": len(serializer.data),
            "results": serializer.data,
        }, status=status.HTTP_200_OK)


class BaseReactionTargetView(APIView):
    """Base class for target-specific reaction operations (Post, Story, Comment)."""
    pagination_class = StandardResultsSetPagination

    def get_target_coordinates(self, request, **kwargs) -> Dict[str, Optional[uuid.UUID]]:
        raise NotImplementedError

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]

    def handle_get_reactions(self, request, **kwargs):
        coords = self.get_target_coordinates(request, **kwargs)
        reaction_item_id = request.query_params.get("reaction_item_id")
        reaction_code = request.query_params.get("reaction_code") or request.query_params.get("code")

        qs = list_reactions_for_target(
            post_id=coords.get("post_id"),
            story_id=coords.get("story_id"),
            comment_id=coords.get("comment_id"),
            reaction_item_id=reaction_item_id,
            reaction_code=reaction_code,
            requesting_user=request.user if request.user.is_authenticated else None,
        )

        owner_type, gym = _resolve_reaction_actor_context(request)
        summary = get_target_reaction_summary(
            post_id=coords.get("post_id"),
            story_id=coords.get("story_id"),
            comment_id=coords.get("comment_id"),
            requesting_user=request.user if request.user.is_authenticated else None,
            owner_type=owner_type,
            gym=gym,
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        serializer = ReactionDetailSerializer(page, many=True, context={"request": request})

        paginated_response = paginator.get_paginated_response(serializer.data)
        paginated_response.data["summary"] = summary
        return paginated_response

    def handle_get_summary(self, request, **kwargs):
        coords = self.get_target_coordinates(request, **kwargs)
        owner_type, gym = _resolve_reaction_actor_context(request)
        summary = get_target_reaction_summary(
            post_id=coords.get("post_id"),
            story_id=coords.get("story_id"),
            comment_id=coords.get("comment_id"),
            requesting_user=request.user if request.user.is_authenticated else None,
            owner_type=owner_type,
            gym=gym,
        )
        return Response(summary, status=status.HTTP_200_OK)

    def handle_toggle_reaction(self, request, **kwargs):
        coords = self.get_target_coordinates(request, **kwargs)
        serializer = ReactionInputSerializer(data=request.data or {}, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        owner_type, gym = _resolve_reaction_actor_context(
            request,
            data_owner_type=data.get("owner_type"),
            data_gym_id=data.get("gym_id"),
        )

        reaction, action_status, target_obj = toggle_or_set_reaction(
            actor_user=request.user,
            reaction_item_id=data.get("reaction_item_id"),
            reaction_code=data.get("reaction_code"),
            post_id=coords.get("post_id"),
            story_id=coords.get("story_id"),
            comment_id=coords.get("comment_id"),
            owner_type=owner_type,
            gym=gym,
        )

        summary = get_target_reaction_summary(
            post_id=coords.get("post_id"),
            story_id=coords.get("story_id"),
            comment_id=coords.get("comment_id"),
            requesting_user=request.user,
            owner_type=owner_type,
            gym=gym,
        )

        target_type = "post" if coords.get("post_id") else ("story" if coords.get("story_id") else "comment")
        response_payload = {
            "status": action_status,
            "reaction": ReactionDetailSerializer(reaction, context={"request": request}).data if reaction else None,
            "target": {
                "id": str(target_obj.id),
                "type": target_type,
                "reactions_count": getattr(target_obj, "reactions_count", 0),
            },
            "summary": summary,
        }

        http_code = status.HTTP_201_CREATED if action_status == "created" else status.HTTP_200_OK
        return Response(response_payload, status=http_code)

    def handle_delete_reaction(self, request, **kwargs):
        coords = self.get_target_coordinates(request, **kwargs)
        owner_type, gym = _resolve_reaction_actor_context(
            request,
            data_owner_type=request.data.get("owner_type") if isinstance(request.data, dict) else None,
            data_gym_id=request.data.get("gym_id") if isinstance(request.data, dict) else None,
        )

        success, target_obj = remove_reaction(
            actor_user=request.user,
            post_id=coords.get("post_id"),
            story_id=coords.get("story_id"),
            comment_id=coords.get("comment_id"),
            owner_type=owner_type,
            gym=gym,
        )

        summary = get_target_reaction_summary(
            post_id=coords.get("post_id"),
            story_id=coords.get("story_id"),
            comment_id=coords.get("comment_id"),
            requesting_user=request.user,
            owner_type=owner_type,
            gym=gym,
        )

        target_type = "post" if coords.get("post_id") else ("story" if coords.get("story_id") else "comment")
        return Response({
            "status": "removed" if success else "not_found",
            "target": {
                "id": str(target_obj.id) if target_obj else str(coords.get("post_id") or coords.get("story_id") or coords.get("comment_id")),
                "type": target_type,
                "reactions_count": getattr(target_obj, "reactions_count", 0) if target_obj else 0,
            },
            "summary": summary,
        }, status=status.HTTP_200_OK)


class PostReactionsView(BaseReactionTargetView):
    """List, toggle, or remove reactions on a community post or repost."""

    def get_target_coordinates(self, request, **kwargs):
        return {"post_id": kwargs.get("post_id"), "story_id": None, "comment_id": None}

    @extend_schema(
        summary="List reactions for a post",
        description="Returns paginated list of users/gyms who reacted to the post, along with breakdown summary.",
        parameters=[
            OpenApiParameter(name="reaction_item_id", type=uuid.UUID, location=OpenApiParameter.QUERY, description="Filter by reaction item UUID"),
            OpenApiParameter(name="code", type=str, location=OpenApiParameter.QUERY, description="Filter by reaction code (e.g. smile, laugh, fire)"),
        ],
        responses={200: ReactionDetailSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return self.handle_get_reactions(request, **kwargs)

    @extend_schema(
        summary="React or toggle reaction on a post",
        description="Creates, updates, or toggles off a reaction on a community post/repost.",
        request=ReactionInputSerializer,
        responses={
            201: ReactionActionResponseSerializer,
            200: ReactionActionResponseSerializer,
            400: ErrorDetailSerializer,
            401: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, *args, **kwargs):
        return self.handle_toggle_reaction(request, **kwargs)

    @extend_schema(
        summary="Remove reaction from a post",
        description="Explicitly removes the authenticated user's reaction from the specified post.",
        responses={200: ReactionActionResponseSerializer},
    )
    def delete(self, request, *args, **kwargs):
        return self.handle_delete_reaction(request, **kwargs)


class PostReactionSummaryView(BaseReactionTargetView):
    """Retrieve aggregated reaction statistics for a post."""

    def get_target_coordinates(self, request, **kwargs):
        return {"post_id": kwargs.get("post_id"), "story_id": None, "comment_id": None}

    @extend_schema(
        summary="Get post reactions summary",
        description="Returns total reactions count, breakdown by emoji, top reactions, and viewer reaction for a post.",
        responses={200: ReactionSummarySerializer},
    )
    def get(self, request, *args, **kwargs):
        return self.handle_get_summary(request, **kwargs)


class StoryReactionsView(BaseReactionTargetView):
    """List, toggle, or remove reactions on an ephemeral story."""

    def get_target_coordinates(self, request, **kwargs):
        return {"post_id": None, "story_id": kwargs.get("story_id"), "comment_id": None}

    @extend_schema(
        summary="List reactions for a story",
        description="Returns paginated list of reactors and summary breakdown for a story.",
        parameters=[
            OpenApiParameter(name="code", type=str, location=OpenApiParameter.QUERY, description="Filter by reaction code"),
        ],
        responses={200: ReactionDetailSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return self.handle_get_reactions(request, **kwargs)

    @extend_schema(
        summary="React or toggle reaction on a story",
        description="Creates, updates, or toggles off a reaction on an active story.",
        request=ReactionInputSerializer,
        responses={
            201: ReactionActionResponseSerializer,
            200: ReactionActionResponseSerializer,
            400: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, *args, **kwargs):
        return self.handle_toggle_reaction(request, **kwargs)

    @extend_schema(
        summary="Remove reaction from a story",
        description="Explicitly removes viewer's reaction from the story.",
        responses={200: ReactionActionResponseSerializer},
    )
    def delete(self, request, *args, **kwargs):
        return self.handle_delete_reaction(request, **kwargs)


class StoryReactionSummaryView(BaseReactionTargetView):
    """Retrieve aggregated reaction statistics for a story."""

    def get_target_coordinates(self, request, **kwargs):
        return {"post_id": None, "story_id": kwargs.get("story_id"), "comment_id": None}

    @extend_schema(
        summary="Get story reactions summary",
        description="Returns total reactions, emoji frequency breakdown, and viewer reaction for a story.",
        responses={200: ReactionSummarySerializer},
    )
    def get(self, request, *args, **kwargs):
        return self.handle_get_summary(request, **kwargs)


class CommentReactionsView(BaseReactionTargetView):
    """List, toggle, or remove reactions on a comment or nested reply."""

    def get_target_coordinates(self, request, **kwargs):
        return {"post_id": None, "story_id": None, "comment_id": kwargs.get("comment_id")}

    @extend_schema(
        summary="List reactions for a comment",
        description="Returns paginated list of reactors and summary breakdown for a post comment or nested reply.",
        parameters=[
            OpenApiParameter(name="code", type=str, location=OpenApiParameter.QUERY, description="Filter by reaction code"),
        ],
        responses={200: ReactionDetailSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return self.handle_get_reactions(request, **kwargs)

    @extend_schema(
        summary="React or toggle reaction on a comment",
        description="Creates, updates, or toggles off a reaction on a post comment or nested reply.",
        request=ReactionInputSerializer,
        responses={
            201: ReactionActionResponseSerializer,
            200: ReactionActionResponseSerializer,
            400: ErrorDetailSerializer,
            404: ErrorDetailSerializer,
        },
    )
    def post(self, request, *args, **kwargs):
        return self.handle_toggle_reaction(request, **kwargs)

    @extend_schema(
        summary="Remove reaction from a comment",
        description="Explicitly removes viewer's reaction from the comment.",
        responses={200: ReactionActionResponseSerializer},
    )
    def delete(self, request, *args, **kwargs):
        return self.handle_delete_reaction(request, **kwargs)


class CommentReactionSummaryView(BaseReactionTargetView):
    """Retrieve aggregated reaction statistics for a post comment."""

    def get_target_coordinates(self, request, **kwargs):
        return {"post_id": None, "story_id": None, "comment_id": kwargs.get("comment_id")}

    @extend_schema(
        summary="Get comment reactions summary",
        description="Returns total reactions, emoji frequency breakdown, and viewer reaction for a comment.",
        responses={200: ReactionSummarySerializer},
    )
    def get(self, request, *args, **kwargs):
        return self.handle_get_summary(request, **kwargs)


class UnifiedReactionsView(APIView):
    """
    Unified endpoint for creating or listing reactions across any target (post, story, or comment).
    """
    pagination_class = StandardResultsSetPagination

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return [IsAuthenticated()]

    @extend_schema(
        summary="List reactions across targets",
        description="Query reactions filtered by target (post_id, story_id, or comment_id) and reaction criteria.",
        parameters=[
            OpenApiParameter(name="post_id", type=uuid.UUID, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="story_id", type=uuid.UUID, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="comment_id", type=uuid.UUID, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="reaction_item_id", type=uuid.UUID, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="code", type=str, location=OpenApiParameter.QUERY),
        ],
        responses={200: ReactionDetailSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        post_id = request.query_params.get("post_id")
        story_id = request.query_params.get("story_id") or request.query_params.get("moment_id")
        comment_id = request.query_params.get("comment_id")

        if not post_id and not story_id and not comment_id:
            raise DomainValidationError("Please provide at least one target filter: 'post_id', 'story_id' (or 'moment_id'), or 'comment_id'.")

        qs = list_reactions_for_target(
            post_id=post_id,
            story_id=story_id,
            comment_id=comment_id,
            reaction_item_id=request.query_params.get("reaction_item_id"),
            reaction_code=request.query_params.get("code") or request.query_params.get("reaction_code"),
            requesting_user=request.user if request.user.is_authenticated else None,
        )

        owner_type, gym = _resolve_reaction_actor_context(request)
        summary = get_target_reaction_summary(
            post_id=post_id,
            story_id=story_id,
            comment_id=comment_id,
            requesting_user=request.user if request.user.is_authenticated else None,
            owner_type=owner_type,
            gym=gym,
        )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request)
        serializer = ReactionDetailSerializer(page, many=True, context={"request": request})

        paginated_response = paginator.get_paginated_response(serializer.data)
        paginated_response.data["summary"] = summary
        return paginated_response

    @extend_schema(
        summary="Create or toggle reaction on any target",
        description="Creates, updates, or toggles off a reaction on a target specified in the request body.",
        request=ReactionInputSerializer,
        responses={
            201: ReactionActionResponseSerializer,
            200: ReactionActionResponseSerializer,
            400: ErrorDetailSerializer,
        },
    )
    def post(self, request, *args, **kwargs):
        serializer = ReactionInputSerializer(data=request.data or {}, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        post_id = data.get("post_id")
        story_id = data.get("story_id") or data.get("moment_id")
        comment_id = data.get("comment_id")

        if not post_id and not story_id and not comment_id:
            raise DomainValidationError("A target must be provided: 'post_id', 'story_id' (or 'moment_id'), or 'comment_id'.")

        owner_type, gym = _resolve_reaction_actor_context(
            request,
            data_owner_type=data.get("owner_type"),
            data_gym_id=data.get("gym_id"),
        )

        reaction, action_status, target_obj = toggle_or_set_reaction(
            actor_user=request.user,
            reaction_item_id=data.get("reaction_item_id"),
            reaction_code=data.get("reaction_code"),
            post_id=post_id,
            story_id=story_id,
            comment_id=comment_id,
            owner_type=owner_type,
            gym=gym,
        )

        summary = get_target_reaction_summary(
            post_id=post_id,
            story_id=story_id,
            comment_id=comment_id,
            requesting_user=request.user,
            owner_type=owner_type,
            gym=gym,
        )

        target_type = "post" if post_id else ("story" if story_id else "comment")
        response_payload = {
            "status": action_status,
            "reaction": ReactionDetailSerializer(reaction, context={"request": request}).data if reaction else None,
            "target": {
                "id": str(target_obj.id),
                "type": target_type,
                "reactions_count": getattr(target_obj, "reactions_count", 0),
            },
            "summary": summary,
        }

        http_code = status.HTTP_201_CREATED if action_status == "created" else status.HTTP_200_OK
        return Response(response_payload, status=http_code)


class UnifiedReactionDetailView(APIView):
    """Direct lookup or deletion of a reaction by its primary UUID."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Retrieve reaction details by ID",
        responses={200: ReactionDetailSerializer, 404: ErrorDetailSerializer},
    )
    def get(self, request, reaction_id: uuid.UUID, *args, **kwargs):
        reaction = get_reaction_by_id(reaction_id)
        serializer = ReactionDetailSerializer(reaction, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Delete reaction by ID",
        responses={200: ReactionActionResponseSerializer, 403: ErrorDetailSerializer, 404: ErrorDetailSerializer},
    )
    def delete(self, request, reaction_id: uuid.UUID, *args, **kwargs):
        success, target_obj = remove_reaction(
            actor_user=request.user,
            reaction_id=reaction_id,
        )
        return Response({
            "status": "removed",
            "reaction_id": str(reaction_id),
            "target": {
                "id": str(target_obj.id) if target_obj else None,
                "type": target_obj.__class__.__name__.lower() if target_obj else "unknown",
                "reactions_count": getattr(target_obj, "reactions_count", 0) if target_obj else 0,
            },
        }, status=status.HTTP_200_OK)

