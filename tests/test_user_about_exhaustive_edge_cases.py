import uuid
import datetime
import pytest
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import (
    User,
    UserProfile,
    UserEducation,
    UserSocialLink,
    UserFollow,
    UserBlockedUser,
)
from apps.authentication.services import issue_context_token
from common.enums import TokenContextType, GenderEnum, SocialPlatformEnum


@pytest.fixture
def user_alice(db):
    user = User.objects.create_user(
        email="alice.about.qa@manygym.com",
        password="SecurePassword123!",
        first_name="Alice",
        last_name="QA",
        phone="+14155550001",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    user.get_settings()
    return user


@pytest.fixture
def user_bob(db):
    user = User.objects.create_user(
        email="bob.about.qa@manygym.com",
        password="SecurePassword123!",
        first_name="Bob",
        last_name="Target",
        phone="+14155550002",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    user.get_settings()
    return user


@pytest.fixture
def user_charlie(db):
    user = User.objects.create_user(
        email="charlie.about.qa@manygym.com",
        password="SecurePassword123!",
        first_name="Charlie",
        last_name="Third",
        phone="+14155550003",
        is_verified=True,
    )
    UserProfile.objects.get_or_create(user=user)
    user.get_settings()
    return user


def make_client(user):
    token = issue_context_token(user=user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token['access']}")
    return client


@pytest.fixture
def alice_client(user_alice):
    return make_client(user_alice)


@pytest.fixture
def bob_client(user_bob):
    return make_client(user_bob)


# ==============================================================================
# 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
# ==============================================================================

@pytest.mark.django_db
class TestUserAboutTypeJuggling:
    """1. Test all applicable fields with incorrect data types (Type Juggling)."""

    def test_patch_about_me_type_juggling_primitives(self, alice_client):
        url = "/api/v1/users/profile/about/"

        invalid_payloads = [
            # Integer where string expected
            ({"current_address": 12345}, 400),
            ({"home_town": 99999}, 400),
            ({"about_you": 88888}, 400),
            ({"favourite_quote": 77777}, 400),
            ({"phone_number": 66666}, 400),
            # Boolean where string expected
            ({"current_address": True}, 400),
            ({"home_town": False}, 400),
            ({"about_you": True}, 400),
            ({"favourite_quote": False}, 400),
            ({"phone_number": True}, 400),
            # Float where string expected
            ({"current_address": 45.67}, 400),
            ({"home_town": 12.34}, 400),
            ({"about_you": 3.14159}, 400),
            # List where string expected
            ({"current_address": ["123 Main St"]}, 400),
            ({"home_town": ["Dhaka"]}, 400),
            ({"about_you": ["Bio text"]}, 400),
            ({"favourite_quote": ["Quote text"]}, 400),
            # Dict where string expected
            ({"current_address": {"address": "123 Main St"}}, 400),
            ({"home_town": {"city": "Dhaka"}}, 400),
            ({"about_you": {"text": "Bio"}}, 400),
            ({"favourite_quote": {"quote": "Quote"}}, 400),
            # List where dict expected
            ({"personal_details": ["not", "a", "dict"]}, 400),
            ({"contact_info": ["not", "a", "dict"]}, 400),
            ({"details_about_you": ["not", "a", "dict"]}, 400),
            # Primitive where dict expected
            ({"personal_details": "string_value"}, 400),
            ({"personal_details": 12345}, 400),
            ({"personal_details": True}, 400),
            ({"contact_info": 12345}, 400),
            ({"details_about_you": "just_a_string"}, 400),
            # String where list expected
            ({"education_list": "should_be_a_list"}, 400),
            ({"hobbies": "should_be_a_list"}, 400),
            ({"social_links": "should_be_a_list"}, 400),
            # Dict where list expected
            ({"education_list": {"university_name": "MIT"}}, 400),
            ({"hobbies": {"hobby": "swimming"}}, 400),
            ({"social_links": {"platform": "instagram"}}, 400),
            # Invalid item type in hobbies list
            ({"hobbies": [123, 456]}, 400),
            ({"hobbies": [True, False]}, 400),
            ({"hobbies": [{"name": "gym"}]}, 400),
            ({"hobbies": [["nested_list"]]}, 400),
            # Invalid date format / type
            ({"date_of_birth": 12345}, 400),
            ({"date_of_birth": True}, 400),
            ({"date_of_birth": ["2000-01-01"]}, 400),
            ({"date_of_birth": {"date": "2000-01-01"}}, 400),
        ]

        for payload, expected_status in invalid_payloads:
            res = alice_client.patch(url, payload, format="json")
            assert res.status_code == expected_status, f"Failed for payload: {payload}, got: {res.status_code}"

    def test_post_education_type_juggling(self, alice_client):
        url = "/api/v1/users/profile/about/educations/"

        invalid_education_payloads = [
            # Integer where string expected
            ({"university_name": 123, "from_year": "2015-01-01", "subject": "CS"}, 400),
            ({"university_name": "MIT", "from_year": "2015-01-01", "subject": 12345}, 400),
            # Boolean where string expected
            ({"university_name": True, "from_year": "2015-01-01", "subject": "CS"}, 400),
            ({"university_name": "MIT", "from_year": "2015-01-01", "subject": False}, 400),
            # Boolean where date expected
            ({"university_name": "MIT", "from_year": True, "subject": "CS"}, 400),
            ({"university_name": "MIT", "from_year": False, "subject": "CS"}, 400),
            ({"university_name": "MIT", "from_year": "2015-01-01", "till_year": True, "subject": "CS"}, 400),
            # Non-boolean where boolean expected (StrictBooleanField)
            ({"university_name": "MIT", "from_year": "2015-01-01", "subject": "CS", "graduated": "yes"}, 400),
            ({"university_name": "MIT", "from_year": "2015-01-01", "subject": "CS", "graduated": 1}, 400),
            ({"university_name": "MIT", "from_year": "2015-01-01", "subject": "CS", "graduated": "true"}, 400),
            # List where string/date expected
            ({"university_name": ["MIT"], "from_year": "2015-01-01", "subject": "CS"}, 400),
            ({"university_name": "MIT", "from_year": ["2015-01-01"], "subject": "CS"}, 400),
            # Dict where string/date expected
            ({"university_name": {"name": "MIT"}, "from_year": "2015-01-01", "subject": "CS"}, 400),
            ({"university_name": "MIT", "from_year": {"year": 2015}, "subject": "CS"}, 400),
        ]

        for payload, expected_status in invalid_education_payloads:
            res = alice_client.post(url, payload, format="json")
            assert res.status_code == expected_status, f"Failed for edu payload: {payload}, got: {res.status_code}"

    def test_post_social_link_type_juggling(self, alice_client):
        url = "/api/v1/users/profile/about/social-links/"

        invalid_social_payloads = [
            ({"platform": 12345, "link": "https://example.com"}, 400),
            ({"platform": True, "link": "https://example.com"}, 400),
            ({"platform": ["instagram"], "link": "https://example.com"}, 400),
            ({"platform": "instagram", "link": 12345}, 400),
            ({"platform": "instagram", "link": True}, 400),
            ({"platform": "instagram", "link": ["https://example.com"]}, 400),
            ({"platform": "instagram", "link": {"url": "https://example.com"}}, 400),
        ]

        for payload, expected_status in invalid_social_payloads:
            res = alice_client.post(url, payload, format="json")
            assert res.status_code == expected_status, f"Failed for social payload: {payload}, got: {res.status_code}"


# ==============================================================================
# 2. BOUNDARY & LENGTH EDGE CASES
# ==============================================================================

@pytest.mark.django_db
class TestUserAboutBoundaryAndLengthEdgeCases:
    """2. Test all applicable minimum and maximum boundaries and lengths."""

    def test_about_you_exact_boundaries(self, alice_client):
        url = "/api/v1/users/profile/about/"

        # Min - 1 / empty string -> allowed
        res = alice_client.patch(url, {"about_you": ""}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.json()["details_about_you"]["about_you"] == ""

        # Max - 1 (319 chars) -> allowed
        res = alice_client.patch(url, {"about_you": "B" * 319}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()["details_about_you"]["about_you"]) == 319

        # Max (320 chars) -> allowed
        res = alice_client.patch(url, {"about_you": "C" * 320}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()["details_about_you"]["about_you"]) == 320

        # Max + 1 (321 chars) -> rejected
        res = alice_client.patch(url, {"about_you": "D" * 321}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Extreme length (10,000+ chars) -> rejected
        res = alice_client.patch(url, {"about_you": "E" * 10500}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_favourite_quote_exact_boundaries(self, alice_client):
        url = "/api/v1/users/profile/about/"

        # Empty string -> allowed
        res = alice_client.patch(url, {"favourite_quote": ""}, format="json")
        assert res.status_code == status.HTTP_200_OK

        # Max - 1 (159 chars) -> allowed
        res = alice_client.patch(url, {"favourite_quote": "Q" * 159}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()["details_about_you"]["favourite_quote"]) == 159

        # Max (160 chars) -> allowed
        res = alice_client.patch(url, {"favourite_quote": "Q" * 160}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.json()["details_about_you"]["favourite_quote"]) == 160

        # Max + 1 (161 chars) -> rejected
        res = alice_client.patch(url, {"favourite_quote": "Q" * 161}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Extreme length (10,000+ chars) -> rejected
        res = alice_client.patch(url, {"favourite_quote": "Q" * 10500}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_address_and_hometown_boundaries(self, alice_client):
        url = "/api/v1/users/profile/about/"

        # Address: max 500 chars -> 500 allowed, 501 rejected
        res = alice_client.patch(url, {"current_address": "A" * 500}, format="json")
        assert res.status_code == status.HTTP_200_OK

        res = alice_client.patch(url, {"current_address": "A" * 501}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Home town: max 255 chars -> 255 allowed, 256 rejected
        res = alice_client.patch(url, {"home_town": "H" * 255}, format="json")
        assert res.status_code == status.HTTP_200_OK

        res = alice_client.patch(url, {"home_town": "H" * 256}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_education_fields_boundaries(self, alice_client):
        url = "/api/v1/users/profile/about/educations/"

        # Empty string / whitespace-only on required fields
        res = alice_client.post(url, {"university_name": "", "from_year": "2015-01-01", "subject": "CS"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        res = alice_client.post(url, {"university_name": "   ", "from_year": "2015-01-01", "subject": "CS"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        res = alice_client.post(url, {"university_name": "Harvard", "from_year": "2015-01-01", "subject": ""}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        res = alice_client.post(url, {"university_name": "Harvard", "from_year": "2015-01-01", "subject": "   "}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # University max 255 chars -> 255 allowed, 256 rejected
        res = alice_client.post(url, {"university_name": "U" * 255, "from_year": "2015-01-01", "subject": "CS"}, format="json")
        assert res.status_code == status.HTTP_201_CREATED

        res = alice_client.post(url, {"university_name": "U" * 256, "from_year": "2015-01-01", "subject": "CS"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Subject max 255 chars -> 255 allowed, 256 rejected
        res = alice_client.post(url, {"university_name": "Oxford", "from_year": "2015-01-01", "subject": "S" * 255}, format="json")
        assert res.status_code == status.HTTP_201_CREATED

        res = alice_client.post(url, {"university_name": "Oxford", "from_year": "2015-01-01", "subject": "S" * 256}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_social_link_boundaries(self, alice_client):
        url = "/api/v1/users/profile/about/social-links/"

        # Link empty string or whitespace
        res = alice_client.post(url, {"platform": "instagram", "link": ""}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        res = alice_client.post(url, {"platform": "instagram", "link": "   "}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Link max 1000 chars -> 1000 allowed, 1001 rejected
        res = alice_client.post(url, {"platform": "instagram", "link": "https://instagram.com/" + "a" * (1000 - 22)}, format="json")
        assert res.status_code == status.HTTP_201_CREATED

        res = alice_client.post(url, {"platform": "instagram", "link": "https://instagram.com/" + "a" * 1000}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_hobbies_list_length_boundaries(self, alice_client):
        url = "/api/v1/users/profile/about/"

        # Individual hobby > 100 chars -> rejected
        res = alice_client.patch(url, {"hobbies": ["H" * 101]}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Individual hobby = 100 chars -> allowed
        res = alice_client.patch(url, {"hobbies": ["H" * 100]}, format="json")
        assert res.status_code == status.HTTP_200_OK

        # Hobbies list exceeding max_length=100 -> rejected
        large_hobbies = [f"Hobby_{i}" for i in range(105)]
        res = alice_client.patch(url, {"hobbies": large_hobbies}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 3. MISSING, EXTRA & MALFORMED FIELDS
# ==============================================================================

@pytest.mark.django_db
class TestUserAboutMissingExtraMalformedFields:
    """3. Test missing, extra garbage, read-only, and malformed field scenarios."""

    def test_empty_json_body_is_safe_noop(self, alice_client):
        url = "/api/v1/users/profile/about/"
        res = alice_client.patch(url, {}, format="json")
        assert res.status_code == status.HTTP_200_OK

        res = alice_client.put(url, {}, format="json")
        assert res.status_code == status.HTTP_200_OK

    def test_missing_required_fields_in_education(self, alice_client):
        url = "/api/v1/users/profile/about/educations/"

        # Missing university_name
        res = alice_client.post(url, {"from_year": "2015-01-01", "subject": "CS"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "university_name" in res.json()["details"]

        # Missing from_year
        res = alice_client.post(url, {"university_name": "MIT", "subject": "CS"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "from_year" in res.json()["details"]

        # Missing subject
        res = alice_client.post(url, {"university_name": "MIT", "from_year": "2015-01-01"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "subject" in res.json()["details"]

        # Empty body
        res = alice_client.post(url, {}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_required_fields_in_social_link(self, alice_client):
        url = "/api/v1/users/profile/about/social-links/"

        # Missing platform
        res = alice_client.post(url, {"link": "https://example.com"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "platform" in res.json()["details"]

        # Missing link
        res = alice_client.post(url, {"platform": "instagram"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "link" in res.json()["details"]

        # Empty body
        res = alice_client.post(url, {}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_100_extra_garbage_fields_ignored_safely(self, alice_client):
        url = "/api/v1/users/profile/about/"
        payload = {f"unknown_garbage_field_{i}": f"value_{i}" for i in range(120)}
        payload["home_town"] = "Barisal"

        res = alice_client.patch(url, payload, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.json()["personal_details"]["home_town"] == "Barisal"

    def test_server_controlled_and_privilege_escalation_fields_ignored(self, alice_client, user_alice):
        url = "/api/v1/users/profile/about/"
        attacker_payload = {
            "is_staff": True,
            "is_superuser": True,
            "status": "suspended",
            "is_verified": False,
            "id": str(uuid.uuid4()),
            "created_at": "2020-01-01T00:00:00Z",
            "email": "hijacked@manygym.com",
            "home_town": "Bogura",
        }

        res = alice_client.patch(url, attacker_payload, format="json")
        assert res.status_code == status.HTTP_200_OK

        user_alice.refresh_from_db()
        assert user_alice.is_staff is False
        assert user_alice.is_superuser is False
        assert user_alice.is_verified is True
        assert user_alice.email == "alice.about.qa@manygym.com"
        assert res.json()["personal_details"]["home_town"] == "Bogura"


# ==============================================================================
# 4. FORMAT-SPECIFIC INVALID INPUTS
# ==============================================================================

@pytest.mark.django_db
class TestUserAboutFormatSpecificInvalidInputs:
    """4. Test format-specific errors: invalid dates, leap years, malformed UUIDs, invalid enums."""

    def test_invalid_date_formats(self, alice_client):
        url = "/api/v1/users/profile/about/"

        invalid_dates = [
            "2026-13-45",       # Invalid month & day
            "2026-02-30",       # February 30th does not exist
            "31/12/2026",       # Non-ISO format
            "today",            # Text string
            "yesterday",        # Text string
            "2026.05.15",       # Dotted format
            "1740000000",       # Unix timestamp string
        ]

        for bad_date in invalid_dates:
            res = alice_client.patch(url, {"date_of_birth": bad_date}, format="json")
            assert res.status_code == status.HTTP_400_BAD_REQUEST, f"Allowed invalid date: {bad_date}"

    def test_leap_year_handling(self, alice_client):
        url = "/api/v1/users/profile/about/"

        # 2024 is a leap year -> Feb 29 allowed
        res = alice_client.patch(url, {"date_of_birth": "2024-02-29"}, format="json")
        assert res.status_code == status.HTTP_200_OK
        assert res.json()["personal_details"]["date_of_birth"] == "2024-02-29"

        # 2023 is not a leap year -> Feb 29 rejected
        res = alice_client.patch(url, {"date_of_birth": "2023-02-29"}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_till_year_before_from_year_rejected_in_all_routes(self, alice_client):
        # 1. In nested about patch
        res = alice_client.patch(
            "/api/v1/users/profile/about/",
            {
                "education_list": [
                    {
                        "university_name": "MIT",
                        "from_year": "2020-01-01",
                        "till_year": "2019-12-31",
                        "subject": "Math",
                    }
                ]
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # 2. In POST education
        res = alice_client.post(
            "/api/v1/users/profile/about/educations/",
            {
                "university_name": "MIT",
                "from_year": "2020-01-01",
                "till_year": "2018-01-01",
                "subject": "Math",
            },
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_uuid_formats_in_path_parameters(self, alice_client):
        bad_uuids = [
            "not-a-uuid",
            "12345",
            "-1",
            "00000000-0000-0000-0000-00000000000g",  # invalid hex char 'g'
            "null",
            "undefined",
        ]

        for bad in bad_uuids:
            # Public profile
            res = alice_client.get(f"/api/v1/users/{bad}/profile/about/")
            assert res.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]

            # Education detail
            res = alice_client.patch(f"/api/v1/users/profile/about/educations/{bad}/", {"subject": "Test"}, format="json")
            assert res.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]

            # Social link detail
            res = alice_client.patch(f"/api/v1/users/profile/about/social-links/{bad}/", {"link": "https://test.com"}, format="json")
            assert res.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND]

    def test_nonexistent_valid_uuids_return_404(self, alice_client):
        nonexistent = uuid.uuid4()

        # Public about
        res = alice_client.get(f"/api/v1/users/{nonexistent}/profile/about/")
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # Education
        res = alice_client.patch(f"/api/v1/users/profile/about/educations/{nonexistent}/", {"subject": "New"}, format="json")
        assert res.status_code == status.HTTP_404_NOT_FOUND

        res = alice_client.delete(f"/api/v1/users/profile/about/educations/{nonexistent}/")
        assert res.status_code == status.HTTP_404_NOT_FOUND

        # Social link
        res = alice_client.patch(f"/api/v1/users/profile/about/social-links/{nonexistent}/", {"link": "https://new.com"}, format="json")
        assert res.status_code == status.HTTP_404_NOT_FOUND

        res = alice_client.delete(f"/api/v1/users/profile/about/social-links/{nonexistent}/")
        assert res.status_code == status.HTTP_404_NOT_FOUND


# ==============================================================================
# 5. QUERY PARAMETERS, FILTERS & SEARCH RESILIENCE
# ==============================================================================

@pytest.mark.django_db
class TestUserAboutQueryParamsAndFilters:
    """5. Verify unexpected and extreme query parameters never cause an unhandled 500 error."""

    def test_about_endpoints_resilience_to_garbage_query_params(self, alice_client, user_bob):
        endpoints = [
            "/api/v1/users/profile/about/",
            "/api/v1/users/me/about/",
            f"/api/v1/users/{user_bob.id}/profile/about/",
            "/api/v1/users/profile/about/educations/",
            "/api/v1/users/profile/about/social-links/",
        ]

        query_payloads = [
            "?page=0",
            "?page=-1",
            "?page=abc",
            "?page=999999999999999999999999999999999999",
            "?limit=-10",
            "?limit=999999999999999999999999999999999999",
            "?search=' OR 1=1 --",
            "?search=<script>alert(1)</script>",
            "?search=" + "A" * 500,
            "?order_by=invalid_field_does_not_exist",
            "?filter[unknown]=value",
            "?foo=bar&baz=qux&num=123",
        ]

        for ep in endpoints:
            for q in query_payloads:
                res = alice_client.get(f"{ep}{q}")
                assert res.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST], (
                    f"Unexpected status {res.status_code} for {ep}{q}"
                )


# ==============================================================================
# 6. SECURITY & INJECTION TESTING
# ==============================================================================

@pytest.mark.django_db
class TestUserAboutSecurityAndInjection:
    """6. SQLi, XSS, Path Traversal, and complex Unicode/adversarial payloads."""

    def test_sql_injection_payloads_in_all_free_text_fields(self, alice_client):
        sqli_payloads = [
            "' OR 1=1 --",
            '" OR ""="',
            "'; DROP TABLE users; --",
            "UNION SELECT NULL, NULL, NULL --",
            "1' AND SLEEP(5) --",
            "admin'--",
        ]

        url = "/api/v1/users/profile/about/"
        for sqli in sqli_payloads:
            res = alice_client.patch(
                url,
                {
                    "current_address": f"Address {sqli}",
                    "home_town": f"Town {sqli}",
                    "about_you": f"Bio {sqli}",
                    "favourite_quote": f"Quote {sqli}",
                },
                format="json",
            )
            # Must succeed cleanly or validate without SQL execution
            assert res.status_code == status.HTTP_200_OK
            assert "DROP TABLE" not in res.json()["personal_details"]["home_town"] or sqli in res.json()["personal_details"]["home_town"]

            # Verify table still exists and data was persisted as literal text
            assert User.objects.filter(email="alice.about.qa@manygym.com").exists()

    def test_xss_payloads_stored_as_safe_literal_text(self, alice_client):
        xss_payloads = [
            "<script>alert(1)</script>",
            "<img src=x onerror=alert(document.cookie)>",
            "javascript:alert('pwned')",
            "<svg/onload=alert('xss')>",
        ]

        for xss in xss_payloads:
            res = alice_client.patch(
                "/api/v1/users/profile/about/",
                {
                    "about_you": xss,
                    "favourite_quote": xss,
                },
                format="json",
            )
            assert res.status_code == status.HTTP_200_OK
            assert res.json()["details_about_you"]["about_you"] == xss
            assert res.json()["details_about_you"]["favourite_quote"] == xss

    def test_path_traversal_payloads_in_free_text(self, alice_client):
        traversals = [
            "../../etc/passwd",
            "..%2F..%2Fetc%2Fpasswd",
            "/etc/shadow",
            "..\\..\\windows\\system32",
        ]

        for pt in traversals:
            res = alice_client.patch(
                "/api/v1/users/profile/about/",
                {"current_address": pt},
                format="json",
            )
            assert res.status_code == status.HTTP_200_OK
            assert res.json()["personal_details"]["current_address"] == pt

    def test_unicode_emojis_rtl_and_complex_encodings(self, alice_client):
        complex_payloads = [
            # Emojis
            {"about_you": "Fitness coach 🏋️‍♂️ Running enthusiast 🏃‍♀️ 💪 🧘", "favourite_quote": "Stay hard! 🔥 💯"},
            # Arabic RTL
            {"home_town": "القاهرة", "about_you": "مرحبا بالعالم أنا مدرب لياقة بدنية"},
            # Hebrew RTL
            {"home_town": "תל אביב", "about_you": "שלום עולם! מאמן כושר אישי"},
            # Bengali
            {"home_town": "ঢাকা", "about_you": "ফিটনেস ও সুস্বাস্থ্যের জন্য প্রতিদিন ব্যায়াম করুন।"},
            # Japanese / Chinese
            {"home_town": "東京都", "about_you": "フィットネスコーチ。毎日鍛錬！"},
            # Zalgo / Combining characters
            {"about_you": "Z̵a̸l̷g̶o̴ Fitness", "favourite_quote": "C̸h̸a̶o̷s̷"},
        ]

        for cp in complex_payloads:
            res = alice_client.patch("/api/v1/users/profile/about/", cp, format="json")
            assert res.status_code == status.HTTP_200_OK


# ==============================================================================
# 7. AUTHENTICATION, AUTHORIZATION & PERMISSIONS
# ==============================================================================

@pytest.mark.django_db
class TestUserAboutAuthenticationAndPermissions:
    """7. Test missing tokens, invalid tokens, expired tokens, and inactive credentials."""

    def test_unauthenticated_requests_rejected_with_401(self, user_bob):
        unauth_client = APIClient()

        endpoints = [
            ("GET", "/api/v1/users/profile/about/"),
            ("PATCH", "/api/v1/users/profile/about/"),
            ("PUT", "/api/v1/users/profile/about/"),
            ("GET", f"/api/v1/users/{user_bob.id}/profile/about/"),
            ("GET", "/api/v1/users/profile/about/educations/"),
            ("POST", "/api/v1/users/profile/about/educations/"),
            ("GET", "/api/v1/users/profile/about/social-links/"),
            ("POST", "/api/v1/users/profile/about/social-links/"),
        ]

        for method, ep in endpoints:
            if method == "GET":
                res = unauth_client.get(ep)
            elif method == "PATCH":
                res = unauth_client.patch(ep, {}, format="json")
            elif method == "PUT":
                res = unauth_client.put(ep, {}, format="json")
            elif method == "POST":
                res = unauth_client.post(ep, {}, format="json")
            assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Allowed unauthenticated for {method} {ep}"

    def test_malformed_and_invalid_tokens_rejected_with_401(self):
        client = APIClient()

        malformed_headers = [
            "Bearer ",
            "Bearer invalid.jwt.token",
            "Token 123456",
            "Basic abcdef==",
            "Bearer " + "A" * 500,
        ]

        for h in malformed_headers:
            client.credentials(HTTP_AUTHORIZATION=h)
            res = client.get("/api/v1/users/profile/about/")
            assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_inactive_user_token_rejected_with_401(self, user_alice):
        client = make_client(user_alice)
        user_alice.is_active = False
        user_alice.save()

        res = client.get("/api/v1/users/profile/about/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED


# ==============================================================================
# 8. IDOR & OBJECT-LEVEL AUTHORIZATION
# ==============================================================================

@pytest.mark.django_db
class TestUserAboutIDORAndObjectLevelAuthorization:
    """8. Test IDOR protection across education and social link mutation endpoints."""

    def test_user_cannot_patch_another_users_education(self, alice_client, bob_client, user_bob):
        # 1. Bob creates an education record
        res = bob_client.post(
            "/api/v1/users/profile/about/educations/",
            {
                "university_name": "Bob University",
                "from_year": "2015-01-01",
                "subject": "Architecture",
                "graduated": True,
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        bob_edu_id = res.json()["id"]

        # 2. Alice attempts to patch Bob's education record -> MUST be 404
        alice_res = alice_client.patch(
            f"/api/v1/users/profile/about/educations/{bob_edu_id}/",
            {"subject": "Hacked Subject"},
            format="json",
        )
        assert alice_res.status_code == status.HTTP_404_NOT_FOUND

        # Verify Bob's record remains unaltered
        edu = UserEducation.objects.get(id=bob_edu_id)
        assert edu.subject == "Architecture"

    def test_user_cannot_delete_another_users_education(self, alice_client, bob_client, user_bob):
        # 1. Bob creates an education record
        res = bob_client.post(
            "/api/v1/users/profile/about/educations/",
            {
                "university_name": "Bob University 2",
                "from_year": "2016-01-01",
                "subject": "Civil Engineering",
                "graduated": True,
            },
            format="json",
        )
        bob_edu_id = res.json()["id"]

        # 2. Alice attempts to delete Bob's education record -> MUST be 404
        alice_res = alice_client.delete(f"/api/v1/users/profile/about/educations/{bob_edu_id}/")
        assert alice_res.status_code == status.HTTP_404_NOT_FOUND

        # Verify Bob's record still exists
        assert UserEducation.objects.filter(id=bob_edu_id).exists() is True

    def test_user_cannot_patch_another_users_social_link(self, alice_client, bob_client, user_bob):
        # 1. Bob creates a social link
        res = bob_client.post(
            "/api/v1/users/profile/about/social-links/",
            {"platform": "github", "link": "https://github.com/bob"},
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        bob_link_id = res.json()["id"]

        # 2. Alice attempts to patch Bob's link -> MUST be 404
        alice_res = alice_client.patch(
            f"/api/v1/users/profile/about/social-links/{bob_link_id}/",
            {"link": "https://github.com/alice_hacked"},
            format="json",
        )
        assert alice_res.status_code == status.HTTP_404_NOT_FOUND

        link = UserSocialLink.objects.get(id=bob_link_id)
        assert link.link == "https://github.com/bob"

    def test_user_cannot_delete_another_users_social_link(self, alice_client, bob_client, user_bob):
        # 1. Bob creates a social link
        res = bob_client.post(
            "/api/v1/users/profile/about/social-links/",
            {"platform": "youtube", "link": "https://youtube.com/@bob"},
            format="json",
        )
        bob_link_id = res.json()["id"]

        # 2. Alice attempts to delete Bob's link -> MUST be 404
        alice_res = alice_client.delete(f"/api/v1/users/profile/about/social-links/{bob_link_id}/")
        assert alice_res.status_code == status.HTTP_404_NOT_FOUND

        assert UserSocialLink.objects.filter(id=bob_link_id).exists() is True


# ==============================================================================
# 9. BUSINESS LOGIC & INVALID STATE TRANSITIONS
# ==============================================================================

@pytest.mark.django_db
class TestUserAboutBusinessLogicAndStateTransitions:
    """9. Test soft-deleted accounts, deactivated accounts, blocking relations, and repeated actions."""

    def test_soft_deleted_target_user_returns_404(self, alice_client, user_bob):
        # Bob is soft-deleted
        setting = user_bob.get_settings()
        setting.soft_delete()
        setting.save()

        res = alice_client.get(f"/api/v1/users/{user_bob.id}/profile/about/")
        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_deactivated_target_user_behavior(self, alice_client, bob_client, user_bob):
        setting = user_bob.get_settings()
        setting.deactivate()
        setting.save()

        # Alice viewing Bob -> 400 Bad Request (Deactivated account)
        res = alice_client.get(f"/api/v1/users/{user_bob.id}/profile/about/")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

        # Bob viewing his own profile -> 200 OK (Owner can still view own about details)
        res_bob = bob_client.get("/api/v1/users/profile/about/")
        assert res_bob.status_code == status.HTTP_200_OK

    def test_blocked_target_user_returns_403(self, alice_client, user_bob):
        # Bob blocks Alice
        UserBlockedUser.objects.create(blocker=user_bob, blocked_user=alice_client.handler._force_user or User.objects.get(email="alice.about.qa@manygym.com"))

        res = alice_client.get(f"/api/v1/users/{user_bob.id}/profile/about/")
        assert res.status_code == status.HTTP_403_FORBIDDEN
        assert "blocked" in res.json()["message"].lower()

    def test_private_target_user_visibility_lifecycle(self, alice_client, user_alice, user_bob):
        user_bob.profile.is_private = True
        user_bob.profile.save()

        # Alice is not following Bob -> 403
        res = alice_client.get(f"/api/v1/users/{user_bob.id}/profile/about/")
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # Alice follows Bob -> 200
        follow = UserFollow.objects.create(follower=user_alice, followed_user=user_bob)
        res_followed = alice_client.get(f"/api/v1/users/{user_bob.id}/profile/about/")
        assert res_followed.status_code == status.HTTP_200_OK

        # Alice unfollows Bob -> 403 again
        follow.delete()
        res_unfollowed = alice_client.get(f"/api/v1/users/{user_bob.id}/profile/about/")
        assert res_unfollowed.status_code == status.HTTP_403_FORBIDDEN

    def test_repeat_deletion_of_education_returns_404(self, alice_client):
        # Create education
        create_res = alice_client.post(
            "/api/v1/users/profile/about/educations/",
            {
                "university_name": "Columbia University",
                "from_year": "2010-01-01",
                "subject": "Philosophy",
            },
            format="json",
        )
        edu_id = create_res.json()["id"]

        # First delete -> 200
        del_1 = alice_client.delete(f"/api/v1/users/profile/about/educations/{edu_id}/")
        assert del_1.status_code == status.HTTP_200_OK

        # Second delete -> 404
        del_2 = alice_client.delete(f"/api/v1/users/profile/about/educations/{edu_id}/")
        assert del_2.status_code == status.HTTP_404_NOT_FOUND

    def test_repeat_deletion_of_social_link_returns_404(self, alice_client):
        # Create link
        create_res = alice_client.post(
            "/api/v1/users/profile/about/social-links/",
            {"platform": "tiktok", "link": "https://tiktok.com/@alice"},
            format="json",
        )
        link_id = create_res.json()["id"]

        # First delete -> 200
        del_1 = alice_client.delete(f"/api/v1/users/profile/about/social-links/{link_id}/")
        assert del_1.status_code == status.HTTP_200_OK

        # Second delete -> 404
        del_2 = alice_client.delete(f"/api/v1/users/profile/about/social-links/{link_id}/")
        assert del_2.status_code == status.HTTP_404_NOT_FOUND


# ==============================================================================
# 10. HTTP METHOD & CONTENT-TYPE VALIDATION
# ==============================================================================

@pytest.mark.django_db
class TestUserAboutHTTPMethodValidation:
    """10. Verify unsupported HTTP methods return 405 Method Not Allowed."""

    def test_disallowed_http_methods_return_405(self, alice_client, user_bob):
        disallowed = [
            # UserAboutMeView (allows GET, PATCH, PUT)
            ("POST", "/api/v1/users/profile/about/"),
            ("DELETE", "/api/v1/users/profile/about/"),
            # UserPublicAboutView (allows GET)
            ("POST", f"/api/v1/users/{user_bob.id}/profile/about/"),
            ("PATCH", f"/api/v1/users/{user_bob.id}/profile/about/"),
            ("PUT", f"/api/v1/users/{user_bob.id}/profile/about/"),
            ("DELETE", f"/api/v1/users/{user_bob.id}/profile/about/"),
            # UserEducationListCreateView (allows GET, POST)
            ("PUT", "/api/v1/users/profile/about/educations/"),
            ("DELETE", "/api/v1/users/profile/about/educations/"),
            # UserSocialLinkListCreateView (allows GET, POST)
            ("PUT", "/api/v1/users/profile/about/social-links/"),
            ("DELETE", "/api/v1/users/profile/about/social-links/"),
        ]

        for method, ep in disallowed:
            if method == "POST":
                res = alice_client.post(ep, {}, format="json")
            elif method == "PUT":
                res = alice_client.put(ep, {}, format="json")
            elif method == "PATCH":
                res = alice_client.patch(ep, {}, format="json")
            elif method == "DELETE":
                res = alice_client.delete(ep)
            assert res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED, (
                f"Expected 405 for {method} {ep}, got: {res.status_code}"
            )

    def test_malformed_json_body_returns_400(self, alice_client):
        # Raw unparseable JSON
        res = alice_client.patch(
            "/api/v1/users/profile/about/",
            data="{invalid_json_body: true,",
            content_type="application/json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST


# ==============================================================================
# 11. RESPONSE VALIDATION & ENVELOPE CONSISTENCY
# ==============================================================================

@pytest.mark.django_db
class TestUserAboutResponseValidation:
    """11. Verify response structure, error envelope formatting, and absence of sensitive leaks."""

    def test_error_envelope_structure_on_validation_failure(self, alice_client):
        res = alice_client.patch(
            "/api/v1/users/profile/about/",
            {"about_you": "A" * 325},
            format="json",
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        data = res.json()

        # Strict error envelope check
        assert "code" in data
        assert "message" in data
        assert "details" in data
        assert isinstance(data["details"], dict)

        # Zero internal traceback or sensitive leaks
        content_str = str(data).lower()
        assert "traceback" not in content_str
        assert "exception" not in content_str
        assert "psycopg" not in content_str
        assert "django.db" not in content_str

    def test_success_response_structure_on_about_get(self, alice_client, user_alice):
        res = alice_client.get("/api/v1/users/profile/about/")
        assert res.status_code == status.HTTP_200_OK
        data = res.json()

        expected_keys = {
            "user_id",
            "first_name",
            "last_name",
            "avatar_url",
            "is_private",
            "personal_details",
            "education_list",
            "hobbies",
            "contact_info",
            "details_about_you",
        }
        assert expected_keys.issubset(data.keys())

        # Verify personal_details keys
        pd_keys = {"current_address", "home_town", "date_of_birth", "gender"}
        assert pd_keys.issubset(data["personal_details"].keys())

        # Verify contact_info keys
        ci_keys = {"social_links", "phone_number", "email"}
        assert ci_keys.issubset(data["contact_info"].keys())

        # Verify details_about_you keys
        day_keys = {"about_you", "favourite_quote"}
        assert day_keys.issubset(data["details_about_you"].keys())

