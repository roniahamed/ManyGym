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


class GymMemberRosterItemSerializer(serializers.Serializer):
    """
    Serializer representing an active member in the gym's public/member-facing roster.
    """
    member_id = serializers.UUIDField()
    user_id = serializers.UUIDField(allow_null=True)
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.CharField()
    email = serializers.EmailField()
    avatar_url = serializers.CharField(allow_null=True, required=False)
    joined_at = serializers.DateTimeField()
    joining_status = serializers.CharField()

    def to_representation(self, instance):
        if not isinstance(instance, dict):
            user = getattr(instance, "user", None)
            profile = getattr(user, "profile", None) if user else None
            avatar = getattr(profile, "avatar_url", None) or getattr(instance, "profile_photo_url", None)
            fn = getattr(instance, "first_name", "") or ""
            ln = getattr(instance, "last_name", "") or ""
            return {
                "member_id": instance.id,
                "user_id": user.id if user else None,
                "first_name": fn,
                "last_name": ln,
                "full_name": f"{fn} {ln}".strip(),
                "email": getattr(instance, "email", ""),
                "avatar_url": avatar,
                "joined_at": instance.created_at,
                "joining_status": getattr(instance, "joining_status", ""),
            }
        return super().to_representation(instance)


class GymMemberJoiningRequestCreateSerializer(serializers.Serializer):
    interested_plan_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500)


class GymMemberJoiningRequestResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    gym_id = serializers.UUIDField()
    gym_name = serializers.CharField()
    status = serializers.CharField()
    request_id = serializers.UUIDField(required=False)
    lead_id = serializers.UUIDField(required=False, allow_null=True)
    created = serializers.BooleanField()


class GymMemberJoiningRequestStatusSerializer(serializers.Serializer):
    gym_id = serializers.UUIDField()
    can_send_request = serializers.BooleanField()
    is_member = serializers.BooleanField()
    has_pending_request = serializers.BooleanField()
    pending_request_id = serializers.UUIDField(required=False, allow_null=True)
    is_blocked = serializers.BooleanField()
    who_can_send_joining_request = serializers.CharField()
