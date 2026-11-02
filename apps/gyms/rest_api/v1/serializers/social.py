from rest_framework import serializers


class GymFollowerItemSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(help_text="User unique identifier.")
    email = serializers.EmailField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True, required=False)
    followed_at = serializers.DateTimeField()

    def to_representation(self, instance):
        if not isinstance(instance, dict):
            user = getattr(instance, "user", None)
            if user:
                profile = getattr(user, "profile", None)
                first_name = getattr(user, "first_name", "") or ""
                last_name = getattr(user, "last_name", "") or ""
                return {
                    "user_id": user.id,
                    "email": getattr(user, "email", ""),
                    "first_name": first_name,
                    "last_name": last_name,
                    "full_name": f"{first_name} {last_name}".strip(),
                    "avatar_url": getattr(profile, "avatar_url", None),
                    "followed_at": instance.created_at,
                }
        return super().to_representation(instance)


class FollowedGymItemSerializer(serializers.Serializer):
    gym_id = serializers.UUIDField(help_text="Gym unique identifier.")
    name = serializers.CharField()
    primary_type = serializers.CharField()
    profile_picture_url = serializers.CharField(allow_null=True, required=False)
    followed_at = serializers.DateTimeField()

    def to_representation(self, instance):
        if not isinstance(instance, dict):
            gym = getattr(instance, "gym", None)
            if gym:
                return {
                    "gym_id": gym.id,
                    "name": getattr(gym, "name", ""),
                    "primary_type": getattr(gym, "primary_type", ""),
                    "profile_picture_url": getattr(gym, "profile_picture_url", None),
                    "followed_at": instance.created_at,
                }
        return super().to_representation(instance)


class GymFollowActionResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    is_following = serializers.BooleanField()
    gym_id = serializers.UUIDField()
    gym_name = serializers.CharField()
