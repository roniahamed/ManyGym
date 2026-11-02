from rest_framework import serializers


class FollowUserItemSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(help_text="User unique identifier.")
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True, required=False)
    is_private = serializers.BooleanField(default=False)
    followed_at = serializers.DateTimeField()

    def to_representation(self, instance):
        if not isinstance(instance, dict):
            relation_type = self.context.get("relation_type", "follower")
            target_user = instance.followed_user if relation_type == "following" else instance.follower
            profile = getattr(target_user, "profile", None)
            first_name = getattr(target_user, "first_name", "") or ""
            last_name = getattr(target_user, "last_name", "") or ""
            return {
                "user_id": target_user.id,
                "email": getattr(target_user, "email", ""),
                "first_name": first_name,
                "last_name": last_name,
                "full_name": f"{first_name} {last_name}".strip(),
                "avatar_url": getattr(profile, "avatar_url", None),
                "is_private": getattr(profile, "is_private", False),
                "followed_at": instance.created_at,
            }
        return super().to_representation(instance)


class UserFollowActionResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    is_following = serializers.BooleanField()
    target_user_id = serializers.UUIDField()


class FollowActionSerializer(serializers.Serializer):
    target_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="UUID of target User or Gym. Auto-detected whether user or gym.",
    )
    id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Alias for target_id.",
    )
    target_type = serializers.ChoiceField(
        choices=["user", "gym"],
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional entity type ('user' or 'gym'). Auto-detected automatically if omitted.",
    )
    action = serializers.ChoiceField(
        choices=["follow", "unfollow"],
        default="follow",
        required=False,
        help_text="Action to perform: 'follow' (default) or 'unfollow'.",
    )

    def validate_target_id(self, value):
        raw = self.initial_data.get("target_id") if hasattr(self, "initial_data") and isinstance(self.initial_data, dict) else None
        if isinstance(raw, (bool, int, float)):
            raise serializers.ValidationError("target_id must be a valid UUID string.")
        return value

    def validate_id(self, value):
        raw = self.initial_data.get("id") if hasattr(self, "initial_data") and isinstance(self.initial_data, dict) else None
        if isinstance(raw, (bool, int, float)):
            raise serializers.ValidationError("id must be a valid UUID string.")
        return value

    def validate(self, attrs):
        tid = attrs.get("target_id") or attrs.get("id") or self.context.get("target_id")
        if not tid:
            raise serializers.ValidationError("Please provide target_id (or id).")
        attrs["target_id"] = tid
        return attrs


class FollowActionResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    is_following = serializers.BooleanField()
    target_type = serializers.CharField()
    target_id = serializers.UUIDField()
    target_name = serializers.CharField(allow_null=True, required=False)


class UnifiedTargetFollowersResponseSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(choices=["user", "gym"], help_text="Type of the target entity ('user' or 'gym').")
    target_id = serializers.UUIDField(help_text="UUID of target entity.")
    followers_count = serializers.IntegerField(help_text="Total number of followers.")
    is_following = serializers.BooleanField(help_text="Whether authenticated user follows this target.")
    followers = serializers.ListField(child=serializers.DictField(), help_text="Followers list.")


class UnifiedFollowedAccountsResponseSerializer(serializers.Serializer):
    followed_users = FollowUserItemSerializer(many=True, help_text="List of users followed by authenticated user.")
    followed_gyms = serializers.ListField(child=serializers.DictField(), help_text="List of gyms followed by authenticated user.")
    total_followed_users = serializers.IntegerField(help_text="Total count of followed users.")
    total_followed_gyms = serializers.IntegerField(help_text="Total count of followed gyms.")
