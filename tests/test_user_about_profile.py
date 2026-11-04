import uuid
import datetime
import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import User, UserProfile, UserEducation, UserSocialLink, UserFollow, UserBlockedUser
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, GenderEnum, SocialPlatformEnum


@pytest.fixture
def auth_client_factory(db):
    def _create(user=None, email=None):
        if not user:
            email_val = email or f"about_user_{uuid.uuid4().hex[:8]}@example.com"
            user = User.objects.create_user(
                email=email_val,
                password="SecurePassword123!",
                first_name="Roni",
                last_name="Tester",
                phone="+8801700000000",
                is_verified=True,
            )
            UserProfile.objects.get_or_create(user=user)
            user.get_settings()
        else:
            user.get_settings()
        token = issue_context_token(user=user, context_type=TokenContextType.PERSONAL)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
        return client, user
    return _create


@pytest.mark.django_db
class TestUserAboutMe:
    def test_get_default_about_me(self, auth_client_factory):
        client, user = auth_client_factory()
        res = client.get("/api/v1/users/profile/about/")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()

        assert data["user_id"] == str(user.id)
        assert data["first_name"] == "Roni"
        assert data["last_name"] == "Tester"
        assert data["personal_details"]["current_address"] is None
        assert data["personal_details"]["home_town"] is None
        assert data["personal_details"]["date_of_birth"] is None
        assert data["personal_details"]["gender"] is None
        assert data["education_list"] == []
        assert data["hobbies"] == []
        assert data["contact_info"]["email"] == user.email
        assert data["contact_info"]["phone_number"] == "+8801700000000"
        assert data["contact_info"]["social_links"] == []
        assert data["details_about_you"]["about_you"] is None
        assert data["details_about_you"]["favourite_quote"] is None

    def test_alias_me_about_endpoint(self, auth_client_factory):
        client, user = auth_client_factory()
        res = client.get("/api/v1/users/me/about/")
        assert res.status_code == status.HTTP_200_OK
        assert res.json()["user_id"] == str(user.id)

    def test_update_about_me_nested_payload(self, auth_client_factory):
        client, user = auth_client_factory()
        payload = {
            "personal_details": {
                "current_address": "House 12, Road 5, Dhanmondi, Dhaka",
                "home_town": "Chittagong",
                "date_of_birth": "1995-07-20",
                "gender": "male",
            },
            "education_list": [
                {
                    "university_name": "University of Dhaka",
                    "from_year": "2014-01-01",
                    "till_year": "2018-12-31",
                    "subject": "Computer Science & Engineering",
                    "graduated": True,
                },
                {
                    "university_name": "BUET",
                    "from_year": "2019-01-01",
                    "till_year": None,
                    "subject": "Masters in Software Engineering",
                    "graduated": False,
                },
            ],
            "hobbies": ["Calisthenics", "Swimming", "Chess"],
            "contact_info": {
                "phone_number": "+8801811111111",
                "social_links": [
                    {
                        "platform": "facebook",
                        "link": "https://facebook.com/roni.profile",
                    },
                    {
                        "platform": "github",
                        "link": "https://github.com/roni",
                    },
                ],
            },
            "details_about_you": {
                "about_you": "Software engineer and fitness enthusiast focusing on compound lifts and endurance.",
                "favourite_quote": "Discipline equals freedom.",
            },
        }

        res = client.patch("/api/v1/users/profile/about/", payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()

        # Check returned response structure
        assert data["personal_details"]["current_address"] == "House 12, Road 5, Dhanmondi, Dhaka"
        assert data["personal_details"]["home_town"] == "Chittagong"
        assert data["personal_details"]["date_of_birth"] == "1995-07-20"
        assert data["personal_details"]["gender"] == "male"
        assert len(data["education_list"]) == 2
        assert data["education_list"][0]["university_name"] == "BUET"  # ordered by -from_year
        assert data["education_list"][0]["graduated"] is False
        assert data["education_list"][1]["university_name"] == "University of Dhaka"
        assert data["education_list"][1]["graduated"] is True
        assert data["hobbies"] == ["Calisthenics", "Swimming", "Chess"]
        assert data["contact_info"]["phone_number"] == "+8801811111111"
        assert len(data["contact_info"]["social_links"]) == 2
        assert data["details_about_you"]["about_you"] == "Software engineer and fitness enthusiast focusing on compound lifts and endurance."
        assert data["details_about_you"]["favourite_quote"] == "Discipline equals freedom."

        # Verify database persistence
        user.refresh_from_db()
        assert user.phone == "+8801811111111"
        profile = user.profile
        assert profile.address == "House 12, Road 5, Dhanmondi, Dhaka"
        assert profile.home_town == "Chittagong"
        assert profile.gender == "male"
        assert profile.sex == "male"
        assert profile.hobbies == ["Calisthenics", "Swimming", "Chess"]
        assert profile.about_you == "Software engineer and fitness enthusiast focusing on compound lifts and endurance."
        assert profile.favourite_quote == "Discipline equals freedom."
        assert user.educations.count() == 2
        assert user.social_links.count() == 2

    def test_update_about_me_flat_payload(self, auth_client_factory):
        client, user = auth_client_factory()
        payload = {
            "current_address": "Gulshan 2, Dhaka",
            "home_town": "Sylhet",
            "date_of_birth": "1998-03-15",
            "gender": "female",
            "phone_number": "+8801999999999",
            "hobbies": ["Yoga", "Pilates"],
            "about_you": "Yoga practitioner and nutritionist.",
            "favourite_quote": "Breathe in, breathe out.",
        }

        res = client.patch("/api/v1/users/profile/about/", payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()

        assert data["personal_details"]["current_address"] == "Gulshan 2, Dhaka"
        assert data["personal_details"]["home_town"] == "Sylhet"
        assert data["personal_details"]["gender"] == "female"
        assert data["contact_info"]["phone_number"] == "+8801999999999"
        assert data["hobbies"] == ["Yoga", "Pilates"]
        assert data["details_about_you"]["about_you"] == "Yoga practitioner and nutritionist."
        assert data["details_about_you"]["favourite_quote"] == "Breathe in, breathe out."

    def test_registered_email_cannot_be_changed(self, auth_client_factory):
        client, user = auth_client_factory()
        original_email = user.email

        # Send attempt to modify email
        payload = {
            "email": "hacked_email@attacker.com",
            "contact_info": {
                "email": "hacked_email2@attacker.com",
                "phone_number": "+8801722222222",
            },
        }
        res = client.patch("/api/v1/users/profile/about/", payload, format="json")
        assert res.status_code == status.HTTP_200_OK

        user.refresh_from_db()
        assert user.email == original_email
        assert res.json()["contact_info"]["email"] == original_email

    def test_about_you_max_length_validation(self, auth_client_factory):
        client, user = auth_client_factory()
        long_bio = "A" * 321
        res = client.patch(
            "/api/v1/users/profile/about/",
            {"about_you": long_bio},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_favourite_quote_max_length_validation(self, auth_client_factory):
        client, user = auth_client_factory()
        long_quote = "Q" * 161
        res = client.patch(
            "/api/v1/users/profile/about/",
            {"favourite_quote": long_quote},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_education_till_year_before_from_year_validation(self, auth_client_factory):
        client, user = auth_client_factory()
        payload = {
            "education_list": [
                {
                    "university_name": "Test University",
                    "from_year": "2020-01-01",
                    "till_year": "2018-01-01",
                    "subject": "Physics",
                    "graduated": True,
                }
            ]
        }
        res = client.patch("/api/v1/users/profile/about/", payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_education_flexible_year_format(self, auth_client_factory):
        client, user = auth_client_factory()
        payload = {
            "education_list": [
                {
                    "university_name": "Oxford University",
                    "from_year": "2015",
                    "till_year": "2019",
                    "subject": "Economics",
                    "graduated": True,
                }
            ]
        }
        res = client.patch("/api/v1/users/profile/about/", payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["education_list"][0]["from_year"] == "2015-01-01"
        assert data["education_list"][0]["till_year"] == "2019-01-01"

    def test_social_platform_invalid_choice(self, auth_client_factory):
        client, user = auth_client_factory()
        payload = {
            "social_links": [
                {
                    "platform": "non_existent_platform",
                    "link": "https://example.com",
                }
            ]
        }
        res = client.patch("/api/v1/users/profile/about/", payload, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_gender_invalid_choice(self, auth_client_factory):
        client, user = auth_client_factory()
        res = client.patch("/api/v1/users/profile/about/", {"gender": "alien"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestUserPublicAbout:
    def test_get_public_user_about_success(self, auth_client_factory):
        client_viewer, viewer = auth_client_factory()
        _, target = auth_client_factory()

        # Populate target user's about profile
        from apps.users.services import update_user_about
        update_user_about(
            target,
            current_address="Banani, Dhaka",
            home_town="Barisal",
            gender="male",
            hobbies=["Boxing", "Running"],
            about_you="Public fitness coach",
            favourite_quote="Never give up",
            education_list=[
                {
                    "university_name": "University of Chittagong",
                    "from_year": datetime.date(2012, 1, 1),
                    "till_year": datetime.date(2016, 1, 1),
                    "subject": "Physical Education",
                    "graduated": True,
                }
            ],
            social_links=[
                {"platform": "instagram", "link": "https://instagram.com/target_coach"}
            ],
        )

        res = client_viewer.get(f"/api/v1/users/{target.id}/profile/about/")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["user_id"] == str(target.id)
        assert data["personal_details"]["home_town"] == "Barisal"
        assert data["personal_details"]["gender"] == "male"
        assert data["hobbies"] == ["Boxing", "Running"]
        assert len(data["education_list"]) == 1
        assert len(data["contact_info"]["social_links"]) == 1

    def test_get_public_user_about_not_found(self, auth_client_factory):
        client, _ = auth_client_factory()
        random_id = uuid.uuid4()
        res = client.get(f"/api/v1/users/{random_id}/profile/about/")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_get_public_user_about_invalid_uuid(self, auth_client_factory):
        client, _ = auth_client_factory()
        res = client.get("/api/v1/users/not-a-uuid/profile/about/")
        assert res.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]

    def test_get_public_user_about_deactivated(self, auth_client_factory):
        client_viewer, viewer = auth_client_factory()
        _, target = auth_client_factory()

        setting = target.get_settings()
        setting.deactivate()
        setting.save()

        res = client_viewer.get(f"/api/v1/users/{target.id}/profile/about/")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_public_user_about_blocked(self, auth_client_factory):
        client_viewer, viewer = auth_client_factory()
        _, target = auth_client_factory()

        # Target blocks viewer
        UserBlockedUser.objects.create(blocker=target, blocked_user=viewer)

        res = client_viewer.get(f"/api/v1/users/{target.id}/profile/about/")
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_get_public_user_about_private_unfollowed(self, auth_client_factory):
        client_viewer, viewer = auth_client_factory()
        _, target = auth_client_factory()

        target.profile.is_private = True
        target.profile.save()

        res = client_viewer.get(f"/api/v1/users/{target.id}/profile/about/")
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_get_public_user_about_private_followed(self, auth_client_factory):
        client_viewer, viewer = auth_client_factory()
        _, target = auth_client_factory()

        target.profile.is_private = True
        target.profile.save()

        # Viewer follows target
        UserFollow.objects.create(follower=viewer, followed_user=target)

        res = client_viewer.get(f"/api/v1/users/{target.id}/profile/about/")
        assert res.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestGranularEducationAndSocialLinks:
    def test_education_crud(self, auth_client_factory):
        client, user = auth_client_factory()

        # 1. Create education
        create_res = client.post(
            "/api/v1/users/profile/about/educations/",
            {
                "university_name": "MIT",
                "from_year": "2016-09-01",
                "till_year": "2020-05-30",
                "subject": "Electrical Engineering",
                "graduated": True,
            },
            format="json",
        )
        assert create_res.status_code == status.HTTP_201_CREATED
        edu_id = create_res.json()["id"]

        # 2. List educations
        list_res = client.get("/api/v1/users/profile/about/educations/")
        assert list_res.status_code == status.HTTP_200_OK
        assert len(list_res.json()) == 1

        # 3. Patch education
        patch_res = client.patch(
            f"/api/v1/users/profile/about/educations/{edu_id}/",
            {"subject": "Computer Science"},
            format="json",
        )
        assert patch_res.status_code == status.HTTP_200_OK
        assert patch_res.json()["subject"] == "Computer Science"

        # 4. Delete education
        del_res = client.delete(f"/api/v1/users/profile/about/educations/{edu_id}/")
        assert del_res.status_code == status.HTTP_200_OK
        assert UserEducation.objects.filter(id=edu_id).exists() is False

    def test_social_link_crud(self, auth_client_factory):
        client, user = auth_client_factory()

        # 1. Create link
        create_res = client.post(
            "/api/v1/users/profile/about/social-links/",
            {
                "platform": "linkedin",
                "link": "https://linkedin.com/in/test-profile",
            },
            format="json",
        )
        assert create_res.status_code == status.HTTP_201_CREATED
        link_id = create_res.json()["id"]

        # 2. List links
        list_res = client.get("/api/v1/users/profile/about/social-links/")
        assert list_res.status_code == status.HTTP_200_OK
        assert len(list_res.json()) == 1

        # 3. Patch link
        patch_res = client.patch(
            f"/api/v1/users/profile/about/social-links/{link_id}/",
            {"link": "https://linkedin.com/in/updated-profile"},
            format="json",
        )
        assert patch_res.status_code == status.HTTP_200_OK
        assert patch_res.json()["link"] == "https://linkedin.com/in/updated-profile"

        # 4. Delete link
        del_res = client.delete(f"/api/v1/users/profile/about/social-links/{link_id}/")
        assert del_res.status_code == status.HTTP_200_OK
        assert UserSocialLink.objects.filter(id=link_id).exists() is False


@pytest.mark.django_db
class TestQueryEfficiency:
    def test_about_me_query_budget(self, auth_client_factory):
        client, user = auth_client_factory()
        from apps.users.services import update_user_about
        update_user_about(
            user,
            current_address="Dhanmondi, Dhaka",
            education_list=[
                {
                    "university_name": f"Uni {i}",
                    "from_year": datetime.date(2010 + i, 1, 1),
                    "subject": "CS",
                    "graduated": True,
                }
                for i in range(5)
            ],
            social_links=[
                {"platform": "instagram", "link": f"https://instagram.com/u_{i}"}
                for i in range(3)
            ],
        )

        with CaptureQueriesContext(connection) as queries:
            res = client.get("/api/v1/users/profile/about/")
            assert res.status_code == status.HTTP_200_OK

        # Query budget: Auth token/user + user with profile/settings + educations prefetch + social_links prefetch
        # Should be strictly bounded (no N+1 per education or social link)
        assert len(queries) <= 8, f"Expected <= 8 queries, got {len(queries)}"

