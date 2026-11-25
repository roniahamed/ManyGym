from rest_framework import serializers

from apps.amenities.models import GymAmenity
from apps.gyms.rest_api.v1.serializers.geo_serializers import GymSearchItemSerializer
from apps.memberships.models import MembershipPlan
from apps.posts.rest_api.v1.serializers import GymPostListSerializer
from apps.search.selectors import (
    SEARCH_FILTER_ALL,
    VALID_CANONICAL_FILTERS,
    normalize_search_filter,
)
from common.enums import (
    AmenityGroupEnum,
    GenderEnum,
    GymGenderRequired,
    GymTypeEnum,
    PlanTypeEnum,
    PostOwnerTypeEnum,
)
from common.serializers import AbsoluteMediaURLField, StrictCharField


class CentralSearchQuerySerializer(serializers.Serializer):
    """
    Validates query parameters for the central search endpoint across
    Gyms, People, Posts, Membership Plans, and Amenities.
    """

    q = StrictCharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Search keyword matching gyms, people, posts, membership plans, or amenities.",
    )
    search = StrictCharField(
        required=False,
        allow_blank=True,
        max_length=255,
        help_text="Alias for 'q'.",
    )
    filter = StrictCharField(
        required=False,
        allow_blank=True,
        default=SEARCH_FILTER_ALL,
        help_text=(
            "Target search category: 'all' (grouped overview for search dropdown/All tab), "
            "'gym', 'people', 'post', 'plan', or 'amenity' (paginated for dedicated search result page)."
        ),
    )
    type = StrictCharField(
        required=False,
        allow_blank=True,
        help_text="Alias for 'filter'.",
    )
    limit = serializers.IntegerField(
        required=False,
        default=5,
        min_value=1,
        max_value=20,
        help_text="Max items per category when filter='all' (default: 5, max: 20).",
    )
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(required=False, default=20, min_value=1, max_value=100)

    # Gym & Location filters
    city = StrictCharField(
        required=False,
        allow_blank=True,
        max_length=100,
        help_text="Filter by city name (applies to gyms, public people profiles, plans, and amenities).",
    )
    gym_category = serializers.ChoiceField(
        choices=GymTypeEnum.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Filter gyms (and gym plans/amenities) by gym category.",
    )
    category = serializers.ChoiceField(
        choices=GymTypeEnum.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Alias for 'gym_category'.",
    )
    gender_required = serializers.ChoiceField(
        choices=GymGenderRequired.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Filter gyms by gender policy ('everyone', 'women_only', 'men_only').",
    )
    latitude = serializers.FloatField(required=False, allow_null=True, min_value=-90.0, max_value=90.0)
    longitude = serializers.FloatField(required=False, allow_null=True, min_value=-180.0, max_value=180.0)
    radius = serializers.FloatField(required=False, default=20.0, min_value=0.1, max_value=500.0)

    # People filters
    gender = serializers.ChoiceField(
        choices=GenderEnum.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Filter public/followed people profiles by gender.",
    )
    is_following = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Filter people by whether the authenticated user currently follows them.",
    )

    # Post filters
    owner_type = serializers.ChoiceField(
        choices=PostOwnerTypeEnum.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Filter posts by author type ('user' or 'gym').",
    )
    is_repost = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Filter posts by repost status.",
    )

    # Membership Plan filters
    plan_type = serializers.ChoiceField(
        choices=PlanTypeEnum.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Filter membership plans by type ('time_based' or 'session_based').",
    )

    # Amenity filters
    amenity_group = serializers.ChoiceField(
        choices=AmenityGroupEnum.choices,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Filter amenities by catalog group.",
    )
    is_paid = serializers.BooleanField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Filter amenities by paid vs complimentary status.",
    )

    def validate(self, attrs):
        if not attrs.get("q") and attrs.get("search"):
            attrs["q"] = attrs["search"]

        raw_filter = attrs.get("type") if "type" in self.initial_data and "filter" not in self.initial_data else attrs.get("filter")
        try:
            attrs["filter"] = normalize_search_filter(raw_filter)
        except Exception:
            raise serializers.ValidationError(
                {"filter": f"Invalid search filter '{raw_filter}'. Allowed values: {', '.join(VALID_CANONICAL_FILTERS)}."}
            )

        if not attrs.get("gym_category") and attrs.get("category"):
            attrs["gym_category"] = attrs["category"]

        lat = attrs.get("latitude")
        lon = attrs.get("longitude")
        if (lat is not None and lon is None) or (lat is None and lon is not None):
            raise serializers.ValidationError(
                {"coordinates": "Both 'latitude' and 'longitude' must be provided together."}
            )

        q_val = attrs.get("q") or ""
        if "\x00" in q_val:
            raise serializers.ValidationError({"q": "Null characters are not allowed in search query."})

        return attrs


class PersonSearchItemSerializer(serializers.Serializer):
    """
    Privacy-safe projection for People search results.
    Withholds hidden profile attributes for private accounts not followed by the viewer.
    """

    id = serializers.UUIDField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    full_name = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    is_private = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    home_town = serializers.SerializerMethodField()
    about_you = serializers.SerializerMethodField()
    followers_count = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()
    has_pending_follow_request = serializers.SerializerMethodField()

    def _can_view_profile_details(self, obj) -> bool:
        profile = getattr(obj, "profile", None)
        if not profile or not profile.is_private:
            return True
        followed_user_ids = self.context.get("followed_user_ids", set())
        return obj.id in followed_user_ids

    def get_full_name(self, obj) -> str:
        return f"{obj.first_name} {obj.last_name}".strip()

    def get_avatar_url(self, obj) -> str | None:
        profile = getattr(obj, "profile", None)
        url = getattr(profile, "avatar_url", None) if profile else None
        if not url or not isinstance(url, str):
            return url
        if url.startswith(("http://", "https://", "data:")):
            return url
        request = self.context.get("request")
        if request is not None and hasattr(request, "build_absolute_uri"):
            return request.build_absolute_uri(url)
        return url

    def get_is_private(self, obj) -> bool:
        profile = getattr(obj, "profile", None)
        return bool(profile.is_private) if profile else False

    def get_city(self, obj) -> str | None:
        if not self._can_view_profile_details(obj):
            return None
        profile = getattr(obj, "profile", None)
        return profile.city if profile else None

    def get_home_town(self, obj) -> str | None:
        if not self._can_view_profile_details(obj):
            return None
        profile = getattr(obj, "profile", None)
        return profile.home_town if profile else None

    def get_about_you(self, obj) -> str | None:
        if not self._can_view_profile_details(obj):
            return None
        profile = getattr(obj, "profile", None)
        return profile.about_you if profile else None

    def get_followers_count(self, obj) -> int:
        annotated = getattr(obj, "followers_count_annotated", None)
        if annotated is not None:
            return annotated
        return obj.follower_relations.count()

    def get_is_following(self, obj) -> bool:
        return obj.id in self.context.get("followed_user_ids", set())

    def get_has_pending_follow_request(self, obj) -> bool:
        return obj.id in self.context.get("pending_follow_request_user_ids", set())


def _get_prefetched_gym_city(gym) -> str | None:
    if not gym:
        return None
    locations = getattr(gym, "prefetched_primary_locations", None)
    if locations:
        return locations[0].city
    primary = gym.locations.filter(is_primary=True).only("city").first()
    return primary.city if primary else None


class MembershipPlanSearchItemSerializer(serializers.ModelSerializer):
    """Public search projection for active Membership Plans with gym context."""

    gym_id = serializers.UUIDField(read_only=True)
    gym_name = serializers.CharField(source="gym.name", read_only=True)
    gym_profile_picture_url = AbsoluteMediaURLField(source="gym.profile_picture_url", allow_null=True, read_only=True)
    city = serializers.SerializerMethodField()
    plan_type_display = serializers.CharField(source="get_plan_type_display", read_only=True)
    duration_display = serializers.SerializerMethodField()
    included_amenities_count = serializers.SerializerMethodField()

    class Meta:
        model = MembershipPlan
        fields = [
            "id",
            "gym_id",
            "gym_name",
            "gym_profile_picture_url",
            "city",
            "name",
            "description",
            "plan_type",
            "plan_type_display",
            "price",
            "duration_value",
            "duration_unit",
            "duration_display",
            "joining_fee",
            "included_amenities_count",
            "created_at",
        ]

    def get_city(self, obj) -> str | None:
        return _get_prefetched_gym_city(obj.gym)

    def get_duration_display(self, obj) -> str:
        val = obj.duration_value
        unit = obj.duration_unit
        unit_display = f"{unit}s" if val > 1 and not unit.endswith("s") else unit
        return f"{val} {unit_display.capitalize()}"

    def get_included_amenities_count(self, obj) -> int:
        annotated = getattr(obj, "annotated_amenities_count", None)
        if annotated is not None:
            return annotated
        return obj.included_amenities.count()


class AmenitySearchItemSerializer(serializers.ModelSerializer):
    """Public search projection for Gym-configured Amenities."""

    amenity_id = serializers.UUIDField(source="amenity.id", read_only=True)
    name = serializers.CharField(source="amenity.name", read_only=True)
    group_name = serializers.CharField(source="amenity.group_name", read_only=True)
    group_display = serializers.CharField(source="amenity.get_group_name_display", read_only=True)
    gym_id = serializers.UUIDField(read_only=True)
    gym_name = serializers.CharField(source="gym.name", read_only=True)
    gym_profile_picture_url = AbsoluteMediaURLField(source="gym.profile_picture_url", allow_null=True, read_only=True)
    city = serializers.SerializerMethodField()

    class Meta:
        model = GymAmenity
        fields = [
            "id",
            "amenity_id",
            "name",
            "group_name",
            "group_display",
            "is_paid",
            "default_price",
            "gym_id",
            "gym_name",
            "gym_profile_picture_url",
            "city",
        ]

    def get_city(self, obj) -> str | None:
        return _get_prefetched_gym_city(obj.gym)


class CentralSearchCountsSerializer(serializers.Serializer):
    gyms = serializers.IntegerField()
    people = serializers.IntegerField()
    posts = serializers.IntegerField()
    membership_plans = serializers.IntegerField()
    amenities = serializers.IntegerField()
    total = serializers.IntegerField()


class CentralSearchGroupedResultsSerializer(serializers.Serializer):
    gyms = GymSearchItemSerializer(many=True)
    people = PersonSearchItemSerializer(many=True)
    posts = GymPostListSerializer(many=True)
    membership_plans = MembershipPlanSearchItemSerializer(many=True)
    amenities = AmenitySearchItemSerializer(many=True)


class CentralSearchAllResponseSerializer(serializers.Serializer):
    query = serializers.CharField(allow_blank=True)
    filter = serializers.CharField()
    counts = CentralSearchCountsSerializer()
    results = CentralSearchGroupedResultsSerializer()
