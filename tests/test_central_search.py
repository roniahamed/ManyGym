from decimal import Decimal
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.amenities.models import AmenityCatalog, GymAmenity
from apps.gyms.models import GymFollow
from apps.gyms.services import (
    apply_access_control_action,
    block_user_for_gym,
    create_gym,
)
from apps.memberships.models import MembershipPlan
from apps.posts.models import GymPost
from apps.users.models import (
    FollowRequestStatus,
    User,
    UserBlockedUser,
    UserFollow,
    UserFollowRequest,
    UserProfile,
)
from common.enums import (
    AmenityGroupEnum,
    DurationUnitEnum,
    GenderEnum,
    GymGenderRequired,
    GymTypeEnum,
    PlanStatusEnum,
    PlanTypeEnum,
    PostOwnerTypeEnum,
    PostPrivacyEnum,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def searcher_user(db):
    user = User.objects.create_user(
        email="searcher@example.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="Searcher",
        is_verified=True,
    )
    UserProfile.objects.create(user=user, city="Dhaka", about_you="Fitness enthusiast")
    return user


@pytest.fixture
def seed_central_search_data(db, searcher_user):
    # People
    bob = User.objects.create_user(
        email="bob.titan@example.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Titan",
        is_verified=True,
    )
    UserProfile.objects.create(
        user=bob,
        city="Dhaka",
        home_town="Sylhet",
        gender=GenderEnum.MALE,
        about_you="Powerlifting coach at Titan",
    )

    carol_private = User.objects.create_user(
        email="carol.private@example.com",
        password="SecurePassword123!",
        first_name="Carol",
        last_name="Secret",
        is_verified=True,
    )
    UserProfile.objects.create(
        user=carol_private,
        city="Dhaka",
        home_town="HiddenTown",
        gender=GenderEnum.FEMALE,
        about_you="TopSecretBioKeyword",
        is_private=True,
    )

    dave_blocked = User.objects.create_user(
        email="dave.blocked@example.com",
        password="SecurePassword123!",
        first_name="Dave",
        last_name="TitanBlocked",
        is_verified=True,
    )
    UserProfile.objects.create(user=dave_blocked, city="Dhaka")
    UserBlockedUser.objects.create(blocker=dave_blocked, blocked_user=searcher_user)

    eve_deactivated = User.objects.create_user(
        email="eve.deactivated@example.com",
        password="SecurePassword123!",
        first_name="Eve",
        last_name="TitanOff",
        is_verified=True,
    )
    eve_settings = eve_deactivated.get_settings()
    eve_settings.deactivate()
    eve_settings.save()

    frank_pending = User.objects.create_user(
        email="frank.pending@example.com",
        password="SecurePassword123!",
        first_name="Frank",
        last_name="TitanPending",
        is_verified=True,
    )
    UserProfile.objects.create(user=frank_pending, city="Chattogram", is_private=True)
    UserFollowRequest.objects.create(
        requester=searcher_user,
        target_user=frank_pending,
        status=FollowRequestStatus.PENDING,
    )

    UserFollow.objects.create(follower=searcher_user, followed_user=bob)

    # Gyms
    desc = (
        "A premier fitness institution dedicated to empowering members with elite equipment, "
        "coaching programs, strength training, and recovery facilities."
    )
    gym_titan = create_gym(
        owner_user=bob,
        name="Titan Strength Club",
        primary_type=GymTypeEnum.STRENGTH_BODYBUILDING,
        gender_required=GymGenderRequired.EVERYONE,
        short_description=desc,
        address="Road 7, Dhanmondi",
        latitude=23.7465,
        longitude=90.3760,
        city="Dhaka",
        country="Bangladesh",
    )

    gym_women = create_gym(
        owner_user=bob,
        name="Titan Women Studio",
        primary_type=GymTypeEnum.YOGA_PILATES_STUDIO,
        gender_required=GymGenderRequired.WOMEN_ONLY,
        short_description=desc,
        address="Sector 3, Uttara",
        latitude=23.8759,
        longitude=90.3795,
        city="Dhaka",
        country="Bangladesh",
    )

    gym_blocked = create_gym(
        owner_user=bob,
        name="Titan Blocked Gym",
        primary_type=GymTypeEnum.GENERAL_FITNESS,
        short_description=desc,
        address="Gulshan 2",
        latitude=23.7925,
        longitude=90.4078,
        city="Dhaka",
        country="Bangladesh",
    )
    block_user_for_gym(gym=gym_blocked, user_id=str(searcher_user.id), blocked_by_user=bob)

    gym_unpublished = create_gym(
        owner_user=bob,
        name="Titan Hidden Gym",
        primary_type=GymTypeEnum.GENERAL_FITNESS,
        short_description=desc,
        address="Gazipur",
        latitude=23.9999,
        longitude=90.4203,
        city="Gazipur",
        country="Bangladesh",
    )
    apply_access_control_action(gym_unpublished, "unpublish", user=bob)
    GymFollow.objects.create(user=searcher_user, gym=gym_titan)

    # Posts
    post_public_user = GymPost.objects.create(
        owner_type=PostOwnerTypeEnum.USER,
        author_user=bob,
        content_text="Morning Titan deadlift session!",
        privacy=PostPrivacyEnum.PUBLIC,
    )
    post_public_gym = GymPost.objects.create(
        owner_type=PostOwnerTypeEnum.GYM,
        gym=gym_titan,
        author_user=bob,
        content_text="New Titan squat racks arrived.",
        privacy=PostPrivacyEnum.PUBLIC,
    )
    post_private_user = GymPost.objects.create(
        owner_type=PostOwnerTypeEnum.USER,
        author_user=bob,
        content_text="Secret Titan private diary",
        privacy=PostPrivacyEnum.PRIVATE,
    )
    post_blocked_gym = GymPost.objects.create(
        owner_type=PostOwnerTypeEnum.GYM,
        gym=gym_blocked,
        author_user=bob,
        content_text="Titan blocked gym announcement",
        privacy=PostPrivacyEnum.PUBLIC,
    )
    post_repost = GymPost.objects.create(
        owner_type=PostOwnerTypeEnum.USER,
        author_user=bob,
        is_repost=True,
        source_post=post_public_gym,
        content_text="Reposting Titan news",
        privacy=PostPrivacyEnum.PUBLIC,
    )

    # Membership Plans
    plan_active = MembershipPlan.objects.create(
        gym=gym_titan,
        name="Titan Gold Monthly",
        description="Full access to all Titan strength equipment, coaching, and sauna facilities.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("59.99"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )
    plan_draft = MembershipPlan.objects.create(
        gym=gym_titan,
        name="Titan Draft Pass",
        description="Draft membership plan that should never appear in public central search.",
        plan_status=PlanStatusEnum.DRAFT,
        plan_type=PlanTypeEnum.SESSION_BASED,
        price=Decimal("25.00"),
        duration_value=5,
        duration_unit=DurationUnitEnum.SESSION,
    )
    plan_blocked_gym = MembershipPlan.objects.create(
        gym=gym_blocked,
        name="Titan Blocked Plan",
        description="Plan from a gym that blocked the searcher, must be hidden from search.",
        plan_status=PlanStatusEnum.ACTIVE,
        plan_type=PlanTypeEnum.TIME_BASED,
        price=Decimal("40.00"),
        duration_value=1,
        duration_unit=DurationUnitEnum.MONTH,
    )

    # Amenities
    sauna_cat = AmenityCatalog.objects.create(
        name="Titan Infrared Sauna",
        group_name=AmenityGroupEnum.WELLNESS_AND_RECOVERY,
    )
    locker_cat = AmenityCatalog.objects.create(
        name="Smart Lockers",
        group_name=AmenityGroupEnum.CHANGING_AND_STORAGE,
    )
    amenity_free = GymAmenity.objects.create(
        gym=gym_titan,
        amenity=sauna_cat,
        is_paid=False,
    )
    amenity_paid = GymAmenity.objects.create(
        gym=gym_women,
        amenity=locker_cat,
        is_paid=True,
        default_price=Decimal("5.00"),
    )
    amenity_blocked_gym = GymAmenity.objects.create(
        gym=gym_blocked,
        amenity=sauna_cat,
        is_paid=False,
    )

    return {
        "bob": bob,
        "carol_private": carol_private,
        "dave_blocked": dave_blocked,
        "eve_deactivated": eve_deactivated,
        "frank_pending": frank_pending,
        "gym_titan": gym_titan,
        "gym_women": gym_women,
        "gym_blocked": gym_blocked,
        "gym_unpublished": gym_unpublished,
        "post_public_user": post_public_user,
        "post_public_gym": post_public_gym,
        "post_private_user": post_private_user,
        "post_blocked_gym": post_blocked_gym,
        "post_repost": post_repost,
        "plan_active": plan_active,
        "plan_draft": plan_draft,
        "plan_blocked_gym": plan_blocked_gym,
        "amenity_free": amenity_free,
        "amenity_paid": amenity_paid,
        "amenity_blocked_gym": amenity_blocked_gym,
    }


@pytest.mark.django_db
class TestCentralSearchAPI:

    def test_requires_authentication(self, api_client):
        url = reverse("search_v1:central-search")
        response = api_client.get(url, {"q": "titan"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_empty_query_without_filters_returns_empty_results(self, api_client, searcher_user, seed_central_search_data):
        api_client.force_authenticate(user=searcher_user)
        url = reverse("search_v1:central-search")

        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["query"] == ""
        assert data["filter"] == "all"
        assert data["counts"] == {
            "gyms": 0,
            "people": 0,
            "posts": 0,
            "membership_plans": 0,
            "amenities": 0,
            "total": 0,
        }
        assert data["results"] == {
            "gyms": [],
            "people": [],
            "posts": [],
            "membership_plans": [],
            "amenities": [],
        }

    def test_all_filter_returns_grouped_results_and_counts(self, api_client, searcher_user, seed_central_search_data):
        api_client.force_authenticate(user=searcher_user)
        url = reverse("search_v1:central-search")

        response = api_client.get(url, {"q": "Titan", "limit": 5})
        assert response.status_code == status.HTTP_200_OK
        data = response.json()

        assert data["query"] == "Titan"
        assert data["filter"] == "all"

        # Counts
        counts = data["counts"]
        assert counts["gyms"] == 2
        assert counts["people"] == 2  # bob + frank_pending (dave blocked, eve deactivated)
        assert counts["posts"] == 3  # public_user, public_gym, repost (private & blocked excluded)
        assert counts["membership_plans"] == 1  # plan_active only
        assert counts["amenities"] == 2  # amenity_free (gym_titan) + amenity_paid (gym_women); gym_blocked excluded
        assert counts["total"] == 10

        # Gyms
        gym_ids = {g["id"] for g in data["results"]["gyms"]}
        assert gym_ids == {
            str(seed_central_search_data["gym_titan"].id),
            str(seed_central_search_data["gym_women"].id),
        }

        # People
        people_ids = {p["id"] for p in data["results"]["people"]}
        assert people_ids == {
            str(seed_central_search_data["bob"].id),
            str(seed_central_search_data["frank_pending"].id),
        }
        bob_item = next(p for p in data["results"]["people"] if p["id"] == str(seed_central_search_data["bob"].id))
        assert bob_item["full_name"] == "Bob Titan"
        assert bob_item["is_following"] is True
        assert bob_item["has_pending_follow_request"] is False
        assert bob_item["followers_count"] == 1

        frank_item = next(
            p for p in data["results"]["people"] if p["id"] == str(seed_central_search_data["frank_pending"].id)
        )
        assert frank_item["is_private"] is True
        assert frank_item["is_following"] is False
        assert frank_item["has_pending_follow_request"] is True
        assert frank_item["city"] is None  # private profile hides city

        # Posts
        post_ids = {p["id"] for p in data["results"]["posts"]}
        assert post_ids == {
            str(seed_central_search_data["post_public_user"].id),
            str(seed_central_search_data["post_public_gym"].id),
            str(seed_central_search_data["post_repost"].id),
        }

        # Plans
        plan_ids = {p["id"] for p in data["results"]["membership_plans"]}
        assert plan_ids == {str(seed_central_search_data["plan_active"].id)}
        assert data["results"]["membership_plans"][0]["gym_name"] == "Titan Strength Club"

        # Amenities
        amenity_ids = {a["id"] for a in data["results"]["amenities"]}
        assert amenity_ids == {
            str(seed_central_search_data["amenity_free"].id),
            str(seed_central_search_data["amenity_paid"].id),
        }
        assert str(seed_central_search_data["amenity_blocked_gym"].id) not in amenity_ids

    def test_private_user_profile_privacy_in_people_search(self, api_client, searcher_user, seed_central_search_data):
        api_client.force_authenticate(user=searcher_user)
        url = reverse("search_v1:central-search")

        # Cannot probe private user's hidden bio/hometown
        r_bio = api_client.get(url, {"q": "TopSecretBioKeyword", "filter": "people"})
        assert r_bio.status_code == status.HTTP_200_OK
        assert r_bio.json()["results"] == []

        # Discoverable by name without leaking city/about_you
        r_name = api_client.get(url, {"q": "Carol Secret", "filter": "people"})
        assert r_name.status_code == status.HTTP_200_OK
        results = r_name.json()["results"]
        assert len(results) == 1
        assert results[0]["id"] == str(seed_central_search_data["carol_private"].id)
        assert results[0]["is_private"] is True
        assert results[0]["city"] is None
        assert results[0]["home_town"] is None
        assert results[0]["about_you"] is None

    def test_dedicated_search_page_gym_filters_and_pagination(self, api_client, searcher_user, seed_central_search_data):
        api_client.force_authenticate(user=searcher_user)
        url = reverse("search_v1:central-search")

        # Filter by gym_category and gender_required
        r1 = api_client.get(url, {
            "q": "Titan",
            "filter": "gym",
            "gym_category": GymTypeEnum.YOGA_PILATES_STUDIO,
            "gender_required": GymGenderRequired.WOMEN_ONLY,
        })
        assert r1.status_code == status.HTTP_200_OK
        d1 = r1.json()
        assert d1["filter"] == "gym"
        assert d1["count"] == 1
        assert d1["total_pages"] == 1
        assert d1["current_page"] == 1
        assert d1["results"][0]["id"] == str(seed_central_search_data["gym_women"].id)
        assert "counts" in d1

        # Pagination page_size=1
        r2 = api_client.get(url, {"q": "Titan", "filter": "gyms", "page": 1, "page_size": 1})
        assert r2.status_code == status.HTTP_200_OK
        d2 = r2.json()
        assert d2["count"] == 2
        assert d2["total_pages"] == 2
        assert len(d2["results"]) == 1
        assert d2["next"] is not None

        # Geospatial filter without keyword
        r_geo = api_client.get(url, {
            "filter": "gym",
            "latitude": 23.7465,
            "longitude": 90.3760,
            "radius": 5.0,
        })
        assert r_geo.status_code == status.HTTP_200_OK
        assert [g["id"] for g in r_geo.json()["results"]] == [str(seed_central_search_data["gym_titan"].id)]

    def test_people_filters_and_self_exclusion(self, api_client, searcher_user, seed_central_search_data):
        api_client.force_authenticate(user=searcher_user)
        url = reverse("search_v1:central-search")

        # Self excluded when searching own name
        r_self = api_client.get(url, {"q": "Alice Searcher", "filter": "people"})
        assert r_self.status_code == status.HTTP_200_OK
        assert r_self.json()["results"] == []

        # Filter by is_following=true & gender=male
        r_follow = api_client.get(url, {
            "q": "Titan",
            "filter": "people",
            "is_following": "true",
            "gender": GenderEnum.MALE,
        })
        assert r_follow.status_code == status.HTTP_200_OK
        assert [p["id"] for p in r_follow.json()["results"]] == [str(seed_central_search_data["bob"].id)]

        # Filter by is_following=false
        r_not_follow = api_client.get(url, {
            "q": "Titan",
            "filter": "people",
            "is_following": "false",
        })
        assert r_not_follow.status_code == status.HTTP_200_OK
        assert [p["id"] for p in r_not_follow.json()["results"]] == [str(seed_central_search_data["frank_pending"].id)]

    def test_post_plan_and_amenity_filters(self, api_client, searcher_user, seed_central_search_data):
        api_client.force_authenticate(user=searcher_user)
        url = reverse("search_v1:central-search")

        # Posts filter: owner_type=gym
        r_posts = api_client.get(url, {"q": "Titan", "filter": "post", "owner_type": PostOwnerTypeEnum.GYM})
        assert r_posts.status_code == status.HTTP_200_OK
        assert [p["id"] for p in r_posts.json()["results"]] == [str(seed_central_search_data["post_public_gym"].id)]

        # Posts filter: is_repost=true
        r_reposts = api_client.get(url, {"q": "Titan", "type": "posts", "is_repost": "true"})
        assert r_reposts.status_code == status.HTTP_200_OK
        assert [p["id"] for p in r_reposts.json()["results"]] == [str(seed_central_search_data["post_repost"].id)]

        # Plans filter
        r_plans = api_client.get(url, {"q": "Titan", "filter": "plan", "plan_type": PlanTypeEnum.TIME_BASED})
        assert r_plans.status_code == status.HTTP_200_OK
        assert [p["id"] for p in r_plans.json()["results"]] == [str(seed_central_search_data["plan_active"].id)]

        # Amenities filter: paid smart lockers
        r_amenities = api_client.get(url, {
            "filter": "amenity",
            "is_paid": "true",
            "amenity_group": AmenityGroupEnum.CHANGING_AND_STORAGE,
        })
        assert r_amenities.status_code == status.HTTP_200_OK
        assert [a["id"] for a in r_amenities.json()["results"]] == [str(seed_central_search_data["amenity_paid"].id)]

    def test_validation_errors(self, api_client, searcher_user):
        api_client.force_authenticate(user=searcher_user)
        url = reverse("search_v1:central-search")

        r_bad_filter = api_client.get(url, {"q": "titan", "filter": "unknown_tab"})
        assert r_bad_filter.status_code == status.HTTP_400_BAD_REQUEST

        r_bad_coords = api_client.get(url, {"filter": "gym", "latitude": 23.7465})
        assert r_bad_coords.status_code == status.HTTP_400_BAD_REQUEST
