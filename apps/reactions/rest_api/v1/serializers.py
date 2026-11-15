import uuid
from typing import Optional
from rest_framework import serializers

from apps.posts.models import GymPost, PostComment
from apps.reactions.models import Reaction, ReactionItem
from apps.stories.models import Story
from common.enums import PostOwnerTypeEnum
from common.serializers import StrictCharField, StrictUUIDField


def _resolve_url(request, path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if request:
        return request.build_absolute_uri(path)
    return path


class ReactionItemSerializer(serializers.ModelSerializer):
    """Represents a selectable emoji reaction type."""
    id = serializers.UUIDField(read_only=True)
    code = serializers.CharField(read_only=True)
    emoji = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    order = serializers.IntegerField(read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = ReactionItem
        fields = ["id", "code", "emoji", "label", "order", "is_active"]


class ReactionInputSerializer(serializers.Serializer):
    """
    Validates input payload for creating or toggling a reaction.
    Accepts either 'reaction_item_id' or 'reaction_code'.
    Target (post_id, story_id, or comment_id) can be provided in the payload or URL path.
    """
    reaction_item_id = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of the ReactionItem from the /api/v1/reactions/items/ catalog.",
    )
    reaction_code = StrictCharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Programmatic reaction code (e.g. 'smile', 'laugh', 'fire', 'like').",
    )
    owner_type = serializers.ChoiceField(
        choices=PostOwnerTypeEnum.choices,
        default=PostOwnerTypeEnum.USER,
        required=False,
        help_text="Whether reacting as a public user ('user') or on behalf of a gym ('gym').",
    )
    gym_id = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text="Required when owner_type='gym'.",
    )
    post_id = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text="Target post UUID if reacting to a community post/repost.",
    )
    story_id = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text="Target story UUID if reacting to a story.",
    )
    comment_id = StrictUUIDField(
        required=False,
        allow_null=True,
        help_text="Target comment UUID if reacting to a comment or reply.",
    )

    def validate(self, attrs):
        item_id = attrs.get("reaction_item_id")
        code = attrs.get("reaction_code")
        if not item_id and not code:
            raise serializers.ValidationError(
                "Either 'reaction_item_id' or 'reaction_code' must be provided."
            )
        owner_type = attrs.get("owner_type", PostOwnerTypeEnum.USER)
        gym_id = attrs.get("gym_id")
        if owner_type == PostOwnerTypeEnum.GYM and not gym_id:
            # Check context token before failing
            request = self.context.get("request")
            token_gym_id = getattr(request, "gym_id", None) if request else None
            if not token_gym_id:
                raise serializers.ValidationError({"gym_id": "gym_id is required when owner_type='gym'."})
        if owner_type == PostOwnerTypeEnum.USER and gym_id:
            raise serializers.ValidationError({"gym_id": "gym_id cannot be provided when owner_type='user'."})
        return attrs


class ReactionDetailSerializer(serializers.ModelSerializer):
    """Detailed response representation of a reaction."""
    id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)
    user_name = serializers.SerializerMethodField()
    user_avatar_url = serializers.SerializerMethodField()
    owner_type = serializers.CharField(read_only=True)
    gym_id = serializers.UUIDField(read_only=True, allow_null=True)
    gym_name = serializers.SerializerMethodField()
    gym_avatar_url = serializers.SerializerMethodField()
    reaction_item = ReactionItemSerializer(read_only=True)
    post_id = serializers.UUIDField(read_only=True, allow_null=True)
    story_id = serializers.UUIDField(read_only=True, allow_null=True)
    comment_id = serializers.UUIDField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Reaction
        fields = [
            "id",
            "user_id",
            "user_name",
            "user_avatar_url",
            "owner_type",
            "gym_id",
            "gym_name",
            "gym_avatar_url",
            "reaction_item",
            "post_id",
            "story_id",
            "comment_id",
            "created_at",
            "updated_at",
        ]

    def get_user_name(self, obj) -> str:
        if obj.user:
            name = f"{obj.user.first_name} {obj.user.last_name}".strip()
            return name or obj.user.email
        return "Unknown"

    def get_user_avatar_url(self, obj) -> Optional[str]:
        if obj.user and hasattr(obj.user, "profile") and obj.user.profile:
            return _resolve_url(self.context.get("request"), obj.user.profile.avatar_url)
        return None

    def get_gym_name(self, obj) -> Optional[str]:
        return obj.gym.name if obj.gym else None

    def get_gym_avatar_url(self, obj) -> Optional[str]:
        if obj.gym and obj.gym.profile_picture_url:
            return _resolve_url(self.context.get("request"), obj.gym.profile_picture_url)
        return None


class ReactionCountSummaryItemSerializer(serializers.Serializer):
    reaction_item_id = serializers.UUIDField()
    code = serializers.CharField()
    emoji = serializers.CharField()
    label = serializers.CharField()
    count = serializers.IntegerField()


class TopReactionSummaryItemSerializer(serializers.Serializer):
    code = serializers.CharField()
    emoji = serializers.CharField()
    count = serializers.IntegerField()


class ViewerReactionSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    reaction_item_id = serializers.UUIDField()
    code = serializers.CharField()
    emoji = serializers.CharField()
    label = serializers.CharField()
    owner_type = serializers.CharField()
    gym_id = serializers.UUIDField(allow_null=True, required=False)
    created_at = serializers.DateTimeField()


class ReactionSummarySerializer(serializers.Serializer):
    """Aggregated summary of reactions for a specific target."""
    total_reactions = serializers.IntegerField()
    reaction_counts = ReactionCountSummaryItemSerializer(many=True)
    top_reactions = TopReactionSummaryItemSerializer(many=True)
    viewer_reaction = ViewerReactionSummarySerializer(allow_null=True, required=False)


class ReactionTargetMetaSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    type = serializers.CharField()
    reactions_count = serializers.IntegerField()


class ReactionActionResponseSerializer(serializers.Serializer):
    """Response returned upon creating, updating, or toggling a reaction."""
    status = serializers.ChoiceField(choices=["created", "updated", "removed"])
    reaction = ReactionDetailSerializer(allow_null=True, required=False)
    target = ReactionTargetMetaSerializer()
    summary = ReactionSummarySerializer()

