import uuid
from decimal import Decimal
import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.urls import reverse

from apps.users.models import User, UserProfile
from apps.gyms.models import Gym, GymLocation, GymOpeningHours, GymGallery
from apps.gyms.services import create_gym, add_gallery_item
from apps.amenities.models import AmenityCatalog, GymAmenity
from apps.amenities.services import seed_amenity_catalog
from apps.access_control.models import Role, Permission, GymStaffAssignment
from apps.access_control.services import seed_default_permissions_and_roles
from apps.authentication.services import issue_context_token
from common.enums import (
    TokenContextType,
    UserStatus,
    StaffStatus,
    GymGenderRequired,
    GymTypeEnum,
    GalleryCategoryEnum,
    MediaTypeEnum,
)


@pytest.fixture(autouse=True)
def setup_seeds(db):
    seed_amenity_catalog()
    seed_default_permissions_and_roles()


def create_user_with_tokens(email="test.owner@manygym.com", is_verified=True, user_status=UserStatus.ACTIVE):
    user = User.objects.create_user(
        email=email,
        password="SecurePassword123!",
        first_name="Test",
        last_name="User",
        is_verified=is_verified,
        status=user_status,
    )
    UserProfile.objects.create(user=user)
    tokens = issue_context_token(user, context_type=TokenContextType.PERSONAL)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    return user, client, tokens


# =====================================================================
# 1. DATA TYPE MISMATCHES (TYPE JUGGLING)
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"name": 12345},
    {"name": ["Titan Gym"]},
    {"name": {"title": "Titan Gym"}},
    {"name": True},
    {"name": None},
    {"name": "Titan Gym", "min_age": "sixteen"},
    {"name": "Titan Gym", "min_age": [16]},
    {"name": "Titan Gym", "min_age": {"age": 16}},
    {"name": "Titan Gym", "latitude": "north-pole"},
    {"name": "Titan Gym", "latitude": [40.7128]},
    {"name": "Titan Gym", "latitude": {"lat": 40.7128}},
    {"name": "Titan Gym", "primary_type": 123},
    {"name": "Titan Gym", "primary_type": ["strength_bodybuilding_gym"]},
    {"name": "Titan Gym", "gender_required": 999},
])
def test_gym_create_type_juggling(payload):
    _, client, _ = create_user_with_tokens("type_juggling@manygym.com")
    res = client.post(reverse("gyms_v1:gym-create"), payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "code" in res.json()


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"min_age": "twenty"},
    {"min_age": [18]},
    {"min_age": {"age": 18}},
    {"name": 99999},
    {"name": ["New Name"]},
    {"primary_type": 123},
    {"gender_required": True},
    {"timezone": 12345},
])
def test_gym_overview_patch_type_juggling(payload):
    owner, client, _ = create_user_with_tokens("overview_types@manygym.com")
    gym = create_gym(owner_user=owner, name="Type Gym")
    url = f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={gym.id}"
    res = client.patch(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"address": 12345, "latitude": "40.0", "longitude": "-74.0"},
    {"address": ["123 Broadway"], "latitude": "40.0", "longitude": "-74.0"},
    {"address": "123 Broadway", "latitude": "not-a-float", "longitude": "-74.0"},
    {"address": "123 Broadway", "latitude": [40.0], "longitude": "-74.0"},
    {"address": "123 Broadway", "latitude": "40.0", "longitude": {"lng": -74.0}},
    {"address": "123 Broadway", "latitude": True, "longitude": "-74.0"},
    {"address": "123 Broadway", "latitude": None, "longitude": "-74.0"},
])
def test_gym_location_patch_type_juggling(payload):
    owner, client, _ = create_user_with_tokens("loc_types@manygym.com")
    gym = create_gym(owner_user=owner, name="Loc Gym")
    url = f"{reverse('gyms_v1:gym-profile-location')}?gym_id={gym.id}"
    res = client.patch(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    "not-a-dict",
    [1, 2, 3],
    {"hours": "not-a-list"},
    {"hours": 12345},
    {"hours": [{"day_of_week": "monday", "start_time": "08:00:00", "end_time": "20:00:00"}]},
    {"hours": [{"day_of_week": 1, "is_closed": "yes"}]},
    {"hours": [{"day_of_week": 1, "start_time": 800, "end_time": 2000}]},
    {"hours": [{"day_of_week": 1, "start_time": ["08:00:00"], "end_time": "20:00:00"}]},
])
def test_opening_hours_type_juggling(payload):
    owner, client, _ = create_user_with_tokens("hours_types@manygym.com")
    gym = create_gym(owner_user=owner, name="Hours Gym")
    url = f"{reverse('gyms_v1:gym-opening-hours')}?gym_id={gym.id}"
    res = client.put(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"media_url": 12345},
    {"media_url": ["http://cdn.com/img.jpg"]},
    {"media_url": {"url": "http://cdn.com/img.jpg"}},
    {"media_url": "http://cdn.com/img.jpg", "media_type": 999},
    {"media_url": "http://cdn.com/img.jpg", "category": 123},
    {"media_url": "http://cdn.com/img.jpg", "caption": 12345},
    {"media_url": "http://cdn.com/img.jpg", "caption": ["caption text"]},
])
def test_gallery_create_type_juggling(payload):
    owner, client, _ = create_user_with_tokens("gallery_types@manygym.com")
    gym = create_gym(owner_user=owner, name="Gal Gym")
    url = f"{reverse('gyms_v1:gym-gallery-list')}?gym_id={gym.id}"
    res = client.post(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
@pytest.mark.parametrize("payload", [
    {"free_amenity_ids": "not-a-list"},
    {"free_amenity_ids": 12345},
    {"free_amenity_ids": {"id": "123"}},
    {"free_amenity_ids": ["not-a-uuid"]},
    {"paid_amenities": "not-a-list"},
    {"paid_amenities": 12345},
    {"paid_amenities": [{"amenity_id": "not-a-uuid", "default_price": "10.00"}]},
    {"paid_amenities": [{"amenity_id": str(uuid.uuid4()), "default_price": "free"}]},
    {"paid_amenities": [{"amenity_id": str(uuid.uuid4()), "default_price": ["10.00"]}]},
    {"paid_amenities": [{"amenity_id": str(uuid.uuid4()), "default_price": True}]},
])
def test_amenities_sync_type_juggling(payload):
    owner, client, _ = create_user_with_tokens("amenity_types@manygym.com")
    gym = create_gym(owner_user=owner, name="Amenity Gym")
    url = f"{reverse('amenities_v1:gym-amenities-sync')}?gym_id={gym.id}"
    res = client.put(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST


# =====================================================================
# 2. BOUNDARY & LENGTH EDGE CASES
# =====================================================================

@pytest.mark.django_db
def test_short_description_exact_length_boundaries():
    owner, client, _ = create_user_with_tokens("boundaries_desc@manygym.com")
    gym = create_gym(owner_user=owner, name="Boundary Gym")
    url = f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={gym.id}"

    # min - 1: 119 characters -> MUST FAIL
    desc_119 = "a" * 119
    res_119 = client.patch(url, {"short_description": desc_119}, format="json")
    assert res_119.status_code == status.HTTP_400_BAD_REQUEST
    assert "at least 120 characters" in str(res_119.json())

    # min: 120 characters -> MUST SUCCEED
    desc_120 = "b" * 120
    res_120 = client.patch(url, {"short_description": desc_120}, format="json")
    assert res_120.status_code == status.HTTP_200_OK
    assert res_120.json()["short_description"] == desc_120

    # min + 1: 121 characters -> MUST SUCCEED
    desc_121 = "c" * 121
    res_121 = client.patch(url, {"short_description": desc_121}, format="json")
    assert res_121.status_code == status.HTTP_200_OK

    # 10,000 characters -> MUST SUCCEED without crash
    desc_10k = "d" * 10000
    res_10k = client.patch(url, {"short_description": desc_10k}, format="json")
    assert res_10k.status_code == status.HTTP_200_OK


@pytest.mark.django_db
@pytest.mark.parametrize("min_age,expected_status", [
    (-1, 400),
    (0, 400),
    (1, 200),
    (2, 200),
    (98, 200),
    (99, 200),
    (100, 400),
    (101, 400),
    (99999, 400),
])
def test_min_age_boundaries(min_age, expected_status):
    owner, client, _ = create_user_with_tokens(f"age_bound_{min_age}@manygym.com")
    gym = create_gym(owner_user=owner, name="Age Gym")
    url = f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={gym.id}"
    res = client.patch(url, {"min_age": min_age}, format="json")
    assert res.status_code == expected_status


@pytest.mark.django_db
@pytest.mark.parametrize("caption_len,expected_status", [
    (0, 201),
    (1, 201),
    (199, 201),
    (200, 201),
    (201, 400),
    (500, 400),
    (5000, 400),
])
def test_gallery_caption_length_boundaries(caption_len, expected_status):
    owner, client, _ = create_user_with_tokens(f"caption_{caption_len}@manygym.com")
    gym = create_gym(owner_user=owner, name="Caption Gym")
    url = f"{reverse('gyms_v1:gym-gallery-list')}?gym_id={gym.id}"

    res = client.post(
        url,
        {
            "media_url": "https://cdn.example.com/test.jpg",
            "caption": "x" * caption_len,
        },
        format="json",
    )
    assert res.status_code == expected_status


@pytest.mark.django_db
@pytest.mark.parametrize("day_of_week,expected_status", [
    (-1, 400),
    (0, 200),
    (6, 200),
    (7, 400),
    (100, 400),
])
def test_opening_hours_day_of_week_boundaries(day_of_week, expected_status):
    owner, client, _ = create_user_with_tokens(f"day_bound_{day_of_week}@manygym.com")
    gym = create_gym(owner_user=owner, name="Day Gym")
    url = f"{reverse('gyms_v1:gym-opening-hours')}?gym_id={gym.id}"

    payload = {
        "hours": [
            {"day_of_week": day_of_week, "start_time": "08:00:00", "end_time": "20:00:00", "is_closed": False}
        ]
    }
    res = client.put(url, payload, format="json")
    assert res.status_code == expected_status


@pytest.mark.django_db
@pytest.mark.parametrize("price,expected_status", [
    ("0.00", 400),
    ("-0.01", 400),
    ("-10.00", 400),
    ("0.01", 200),
    ("10.00", 200),
    ("99999999.99", 200),
    ("100000000.00", 400),
])
def test_paid_amenity_price_boundaries(price, expected_status):
    owner, client, _ = create_user_with_tokens(f"price_{price.replace('.', '_')}@manygym.com")
    gym = create_gym(owner_user=owner, name="Price Gym")
    url = f"{reverse('amenities_v1:gym-amenities-sync')}?gym_id={gym.id}"

    catalog_item = AmenityCatalog.objects.first()
    payload = {
        "paid_amenities": [{"amenity_id": str(catalog_item.id), "default_price": price}]
    }
    res = client.put(url, payload, format="json")
    assert res.status_code == expected_status


# =====================================================================
# 3. MISSING, EXTRA & MALFORMED FIELDS (MASS ASSIGNMENT SHIELD)
# =====================================================================

@pytest.mark.django_db
def test_completely_empty_json_bodies():
    owner, client, _ = create_user_with_tokens("empty_bodies@manygym.com")
    gym = create_gym(owner_user=owner, name="Empty Gym")

    # 1. POST gym create with {} -> 400 (missing name)
    assert client.post(reverse("gyms_v1:gym-create"), {}, format="json").status_code == 400

    # 2. PATCH location with {} -> 400 (missing address, lat, lng)
    assert client.patch(f"{reverse('gyms_v1:gym-profile-location')}?gym_id={gym.id}", {}, format="json").status_code == 400

    # 3. PUT opening hours with {} -> 400 (missing hours list)
    assert client.put(f"{reverse('gyms_v1:gym-opening-hours')}?gym_id={gym.id}", {}, format="json").status_code == 400

    # 4. POST gallery with {} -> 400 (missing file or media_url)
    assert client.post(f"{reverse('gyms_v1:gym-gallery-list')}?gym_id={gym.id}", {}, format="json").status_code == 400

    # 5. PATCH reorder with {} -> 400 (missing items)
    assert client.patch(f"{reverse('gyms_v1:gym-gallery-reorder')}?gym_id={gym.id}", {}, format="json").status_code == 400


@pytest.mark.django_db
def test_mass_assignment_and_100_garbage_fields():
    owner, client, _ = create_user_with_tokens("garbage_fields@manygym.com")
    gym = create_gym(owner_user=owner, name="Safe Gym")

    # Attempt to inject server-controlled fields & 100 extra garbage keys
    payload = {
        "name": "Tampered Safe Gym",
        "id": str(uuid.uuid4()),
        "owner_user": str(uuid.uuid4()),
        "owner_user_id": str(uuid.uuid4()),
        "is_superuser": True,
        "created_at": "1999-01-01T00:00:00Z",
    }
    for i in range(100):
        payload[f"injected_garbage_{i}"] = f"malicious_value_{i}"

    url = f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={gym.id}"
    res = client.patch(url, payload, format="json")
    assert res.status_code == status.HTTP_200_OK

    # Verify server-controlled fields were NOT overwritten
    refreshed_gym = Gym.objects.get(id=gym.id)
    assert refreshed_gym.name == "Tampered Safe Gym"
    assert refreshed_gym.owner_user_id == owner.id
    assert refreshed_gym.id == gym.id


# =====================================================================
# 4. FORMAT-SPECIFIC INVALID INPUTS
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("start_time,end_time,is_closed,expected_code", [
    ("25:00:00", "08:00:00", False, 400),
    ("10:00:00", "25:00:00", False, 400),
    ("12:65:00", "14:00:00", False, 400),
    ("noon", "midnight", False, 400),
    ("1700000000", "1700010000", False, 400),
    ("18:00:00", "08:00:00", False, 400),  # start > end
    ("10:00:00", "10:00:00", False, 400),  # start == end
    (None, None, False, 400),               # non-closed requires times
    ("08:00:00", None, False, 400),         # end_time missing
    (None, "20:00:00", False, 400),         # start_time missing
    ("08:00:00", "20:00:00", True, 200),    # closed cleans times gracefully
])
def test_opening_hours_time_formats_and_order(start_time, end_time, is_closed, expected_code):
    owner, client, _ = create_user_with_tokens(f"hours_{expected_code}@manygym.com")
    gym = create_gym(owner_user=owner, name="Time Gym")
    url = f"{reverse('gyms_v1:gym-opening-hours')}?gym_id={gym.id}"

    payload = {
        "hours": [
            {"day_of_week": 1, "start_time": start_time, "end_time": end_time, "is_closed": is_closed}
        ]
    }
    res = client.put(url, payload, format="json")
    assert res.status_code == expected_code


@pytest.mark.django_db
def test_duplicate_days_in_opening_hours_rejected():
    owner, client, _ = create_user_with_tokens("dup_days@manygym.com")
    gym = create_gym(owner_user=owner, name="Dup Gym")
    url = f"{reverse('gyms_v1:gym-opening-hours')}?gym_id={gym.id}"

    payload = {
        "hours": [
            {"day_of_week": 1, "start_time": "08:00:00", "end_time": "14:00:00", "is_closed": False},
            {"day_of_week": 1, "start_time": "15:00:00", "end_time": "22:00:00", "is_closed": False},
        ]
    }
    res = client.put(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Duplicate entry for day_of_week" in str(res.json())


@pytest.mark.django_db
@pytest.mark.parametrize("invalid_uuid", [
    "not-a-valid-uuid",
    "12345",
    "00000000-0000",
    "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
    "null",
    "undefined",
])
def test_malformed_uuids_in_all_phase2_endpoints(invalid_uuid):
    owner, client, _ = create_user_with_tokens(f"uuid_{invalid_uuid[:5]}@manygym.com")

    # 1. Overview GET with malformed gym_id
    res1 = client.get(f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={invalid_uuid}")
    assert res1.status_code in [400, 404]

    # 2. Location GET with malformed gym_id
    res2 = client.get(f"{reverse('gyms_v1:gym-profile-location')}?gym_id={invalid_uuid}")
    assert res2.status_code in [400, 404]

    # 3. Hours GET with malformed gym_id
    res3 = client.get(f"{reverse('gyms_v1:gym-opening-hours')}?gym_id={invalid_uuid}")
    assert res3.status_code in [400, 404]

    # 4. Gallery GET with malformed gym_id
    res4 = client.get(f"{reverse('gyms_v1:gym-gallery-list')}?gym_id={invalid_uuid}")
    assert res4.status_code in [400, 404]

    # 5. Gallery DELETE with malformed item_id
    res5 = client.delete(f"/api/v1/gyms/gallery/{invalid_uuid}/")
    assert res5.status_code == 404

    # 6. Amenities configured with malformed gym_id
    res6 = client.get(f"{reverse('amenities_v1:gym-amenities-configured')}?gym_id={invalid_uuid}")
    assert res6.status_code in [400, 404]


# =====================================================================
# 5. QUERY PARAMETERS, FILTERS & ENUMS
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("category", [
    "equipment",
    "workout_areas",
    "studios_class_spaces",
    "changing_rooms_showers",
    "wellness_facilities",
    "reception_lounge",
    "interior_decor",
    "exterior_entrance",
    "general",
    "other",
])
def test_valid_gallery_categories_filtering(category):
    owner, client, _ = create_user_with_tokens(f"cat_{category}@manygym.com")
    gym = create_gym(owner_user=owner, name="Cat Gym")
    add_gallery_item(gym, media_url="https://cdn.com/1.jpg", category=category)

    res = client.get(f"{reverse('gyms_v1:gym-gallery-list')}?gym_id={gym.id}&category={category}")
    assert res.status_code == status.HTTP_200_OK
    assert len(res.json()) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("garbage_category", [
    "invalid_cat",
    "EQUIPMENT",  # uppercase
    "123",
    "True",
    "null",
    "---",
    "' OR 1=1 --",
    "<script>",
])
def test_invalid_and_adversarial_gallery_category_filters(garbage_category):
    owner, client, _ = create_user_with_tokens(f"adv_cat_{garbage_category[:4]}@manygym.com")
    gym = create_gym(owner_user=owner, name="Adv Cat Gym")

    res = client.get(f"{reverse('gyms_v1:gym-gallery-list')}?gym_id={gym.id}&category={garbage_category}")
    assert res.status_code == status.HTTP_200_OK
    assert res.json() == []  # Gracefully returns empty list without 500 error


@pytest.mark.django_db
def test_missing_gym_id_returns_400():
    owner, client, _ = create_user_with_tokens("missing_gym_id@manygym.com")

    # Accessing gym endpoints without active gym token and without ?gym_id
    assert client.get(reverse("gyms_v1:gym-profile-overview")).status_code == status.HTTP_400_BAD_REQUEST
    assert client.get(reverse("gyms_v1:gym-profile-location")).status_code == status.HTTP_400_BAD_REQUEST
    assert client.get(reverse("gyms_v1:gym-opening-hours")).status_code == status.HTTP_400_BAD_REQUEST
    assert client.get(reverse("gyms_v1:gym-gallery-list")).status_code == status.HTTP_400_BAD_REQUEST
    assert client.get(reverse("amenities_v1:gym-amenities-configured")).status_code == status.HTTP_400_BAD_REQUEST


# =====================================================================
# 6. SECURITY & INJECTION TESTING
# =====================================================================

@pytest.mark.django_db
@pytest.mark.parametrize("payload_str", [
    "' OR '1'='1",
    "'; DROP TABLE gyms; --",
    "' UNION SELECT NULL, NULL, NULL --",
    "admin' --",
    "\" OR \"\"=\"",
])
def test_sqli_resilience_across_phase2(payload_str):
    owner, client, _ = create_user_with_tokens(f"sqli_{payload_str[:4]}@manygym.com")
    gym = create_gym(owner_user=owner, name="SQLi Gym")

    # 1. In gym overview name
    res1 = client.patch(
        f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={gym.id}",
        {"name": f"Gym {payload_str}"},
        format="json",
    )
    assert res1.status_code == status.HTTP_200_OK
    assert Gym.objects.get(id=gym.id).name == f"Gym {payload_str}"

    # 2. In location address
    res2 = client.patch(
        f"{reverse('gyms_v1:gym-profile-location')}?gym_id={gym.id}",
        {"address": payload_str, "latitude": "40.0", "longitude": "-74.0"},
        format="json",
    )
    assert res2.status_code == status.HTTP_200_OK

    # 3. In gallery caption
    res3 = client.post(
        f"{reverse('gyms_v1:gym-gallery-list')}?gym_id={gym.id}",
        {"media_url": "https://cdn.com/1.jpg", "caption": payload_str[:150]},
        format="json",
    )
    assert res3.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
@pytest.mark.parametrize("xss_payload", [
    "<script>alert('XSS')</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(document.cookie)",
    "<svg/onload=alert(1)>",
    "'\"><script src=//evil.com></script>",
])
def test_xss_payload_safety_across_phase2(xss_payload):
    owner, client, _ = create_user_with_tokens(f"xss_{xss_payload[:4]}@manygym.com")
    gym = create_gym(owner_user=owner, name="XSS Gym")

    # Store XSS safely without executing or crashing
    res = client.patch(
        f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={gym.id}",
        {"name": xss_payload},
        format="json",
    )
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["name"] == xss_payload


@pytest.mark.django_db
@pytest.mark.parametrize("unicode_text", [
    "🏋️‍♂️🔥💪⚡️",
    "مرحبا بكم في جيم ماني",
    "こんにちは世界",
    "Z͔̭̞̺͑ͫ̓aͧ͠lͫͥgͩo",
    "Café & Ñandú",
])
def test_unicode_and_special_character_resilience(unicode_text):
    owner, client, _ = create_user_with_tokens(f"unicode_{unicode_text[:2]}@manygym.com")
    gym = create_gym(owner_user=owner, name="Unicode Gym")

    # Overview name & description
    valid_desc = f"{unicode_text} " * 20
    assert len(valid_desc) >= 120
    res = client.patch(
        f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={gym.id}",
        {"name": unicode_text, "short_description": valid_desc},
        format="json",
    )
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["name"] == unicode_text


# =====================================================================
# 7. AUTHENTICATION & AUTHORIZATION
# =====================================================================

@pytest.mark.django_db
def test_unauthenticated_requests_rejected():
    client = APIClient()  # No Authorization header
    dummy_id = str(uuid.uuid4())

    endpoints = [
        ("POST", reverse("gyms_v1:gym-create"), {"name": "Test Gym"}),
        ("GET", f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={dummy_id}", None),
        ("PATCH", f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={dummy_id}", {"name": "New"}),
        ("GET", f"{reverse('gyms_v1:gym-profile-location')}?gym_id={dummy_id}", None),
        ("PATCH", f"{reverse('gyms_v1:gym-profile-location')}?gym_id={dummy_id}", {"address": "Addr"}),
        ("GET", f"{reverse('gyms_v1:gym-opening-hours')}?gym_id={dummy_id}", None),
        ("PUT", f"{reverse('gyms_v1:gym-opening-hours')}?gym_id={dummy_id}", {"hours": []}),
        ("GET", f"{reverse('gyms_v1:gym-gallery-list')}?gym_id={dummy_id}", None),
        ("POST", f"{reverse('gyms_v1:gym-gallery-list')}?gym_id={dummy_id}", {"media_url": "url"}),
        ("PATCH", f"{reverse('gyms_v1:gym-gallery-reorder')}?gym_id={dummy_id}", {"items": []}),
        ("DELETE", f"/api/v1/gyms/gallery/{dummy_id}/", None),
        ("GET", reverse("amenities_v1:amenity-catalog"), None),
        ("GET", f"{reverse('amenities_v1:gym-amenities-configured')}?gym_id={dummy_id}", None),
        ("PUT", f"{reverse('amenities_v1:gym-amenities-sync')}?gym_id={dummy_id}", {"free_amenity_ids": []}),
    ]

    for method, url, data in endpoints:
        if method == "GET":
            res = client.get(url)
        elif method == "POST":
            res = client.post(url, data, format="json")
        elif method == "PATCH":
            res = client.patch(url, data, format="json")
        elif method == "PUT":
            res = client.put(url, data, format="json")
        elif method == "DELETE":
            res = client.delete(url)
        assert res.status_code == status.HTTP_401_UNAUTHORIZED, f"Failed for {method} {url}"


# =====================================================================
# 8. IDOR & CROSS-TENANT ISOLATION
# =====================================================================

@pytest.mark.django_db
def test_cross_tenant_idor_protection():
    # User A owns Gym A
    user_a, client_a, _ = create_user_with_tokens("owner_a@manygym.com")
    gym_a = create_gym(owner_user=user_a, name="Gym A")
    item_a = add_gallery_item(gym_a, media_url="https://cdn.com/a.jpg")

    # User B owns Gym B
    user_b, client_b, _ = create_user_with_tokens("owner_b@manygym.com")
    gym_b = create_gym(owner_user=user_b, name="Gym B")
    item_b = add_gallery_item(gym_b, media_url="https://cdn.com/b.jpg")

    # User B attempts to tamper with Gym A:
    # 1. Update Gym A overview -> 403 Forbidden
    res1 = client_b.patch(
        f"{reverse('gyms_v1:gym-profile-overview')}?gym_id={gym_a.id}",
        {"name": "Hacked Gym A"},
        format="json",
    )
    assert res1.status_code == status.HTTP_403_FORBIDDEN

    # 2. Update Gym A location -> 403 Forbidden
    res2 = client_b.patch(
        f"{reverse('gyms_v1:gym-profile-location')}?gym_id={gym_a.id}",
        {"address": "Hacked Address", "latitude": "10.0", "longitude": "20.0"},
        format="json",
    )
    assert res2.status_code == status.HTTP_403_FORBIDDEN

    # 3. Update Gym A opening hours -> 403 Forbidden
    res3 = client_b.put(
        f"{reverse('gyms_v1:gym-opening-hours')}?gym_id={gym_a.id}",
        {"hours": [{"day_of_week": 0, "start_time": "08:00:00", "end_time": "20:00:00", "is_closed": False}]},
        format="json",
    )
    assert res3.status_code == status.HTTP_403_FORBIDDEN

    # 4. Upload photo to Gym A -> 403 Forbidden
    res4 = client_b.post(
        f"{reverse('gyms_v1:gym-gallery-list')}?gym_id={gym_a.id}",
        {"media_url": "https://cdn.com/hacked.jpg"},
        format="json",
    )
    assert res4.status_code == status.HTTP_403_FORBIDDEN

    # 5. Reorder Gym A -> 403 Forbidden
    res5 = client_b.patch(
        f"{reverse('gyms_v1:gym-gallery-reorder')}?gym_id={gym_a.id}",
        {"items": [{"id": str(item_a.id), "order_index": 5}]},
        format="json",
    )
    assert res5.status_code == status.HTTP_403_FORBIDDEN

    # 6. Delete Gym A's gallery item -> 403 Forbidden
    res6 = client_b.delete(
        f"/api/v1/gyms/gallery/{item_a.id}/?gym_id={gym_a.id}",
    )
    assert res6.status_code == status.HTTP_403_FORBIDDEN
    assert GymGallery.objects.filter(id=item_a.id).exists()

    # 7. Sync Gym A's amenities -> 403 Forbidden
    res7 = client_b.put(
        f"{reverse('amenities_v1:gym-amenities-sync')}?gym_id={gym_a.id}",
        {"free_amenity_ids": []},
        format="json",
    )
    assert res7.status_code == status.HTTP_403_FORBIDDEN


# =====================================================================
# 9. BUSINESS LOGIC & STATE TRANSITIONS
# =====================================================================

@pytest.mark.django_db
def test_amenities_mutual_exclusion_invariant():
    owner, client, _ = create_user_with_tokens("amenity_invariant@manygym.com")
    gym = create_gym(owner_user=owner, name="Amenity Invariant Gym")
    url = f"{reverse('amenities_v1:gym-amenities-sync')}?gym_id={gym.id}"

    catalog_items = list(AmenityCatalog.objects.all()[:2])
    item_conflict = str(catalog_items[0].id)
    item_second = str(catalog_items[1].id)

    # Core invariant: Item 0 cannot be both FREE and PAID simultaneously
    payload = {
        "free_amenity_ids": [item_conflict, item_second],
        "paid_amenities": [
            {"amenity_id": item_conflict, "default_price": "15.00"}
        ],
    }
    res = client.put(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Mutual exclusion violation" in str(res.json())


@pytest.mark.django_db
def test_sync_nonexistent_catalog_amenity_id():
    owner, client, _ = create_user_with_tokens("nonexistent_amenity@manygym.com")
    gym = create_gym(owner_user=owner, name="Nonexistent Amenity Gym")
    url = f"{reverse('amenities_v1:gym-amenities-sync')}?gym_id={gym.id}"

    fake_id = str(uuid.uuid4())
    payload = {
        "free_amenity_ids": [fake_id],
        "paid_amenities": [],
    }
    res = client.put(url, payload, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid amenity catalog IDs" in str(res.json())


@pytest.mark.django_db
def test_delete_already_deleted_gallery_item():
    owner, client, _ = create_user_with_tokens("double_del@manygym.com")
    gym = create_gym(owner_user=owner, name="Del Gym")
    item = add_gallery_item(gym, media_url="https://cdn.com/del.jpg")

    url = f"/api/v1/gyms/gallery/{item.id}/?gym_id={gym.id}"
    # First delete -> 200 OK
    assert client.delete(url).status_code == status.HTTP_200_OK

    # Second delete on already deleted item -> 404 NOT FOUND
    assert client.delete(url).status_code == status.HTTP_404_NOT_FOUND


# =====================================================================
# 10. HTTP METHOD VALIDATION
# =====================================================================

@pytest.mark.django_db
def test_unsupported_http_methods():
    owner, client, _ = create_user_with_tokens("methods_test@manygym.com")
    gym = create_gym(owner_user=owner, name="Method Gym")

    # 1. GET on gym-create -> 405 Method Not Allowed
    assert client.get(reverse("gyms_v1:gym-create")).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # 2. POST on location -> 405 Method Not Allowed
    assert client.post(f"{reverse('gyms_v1:gym-profile-location')}?gym_id={gym.id}", {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # 3. POST on amenity-catalog -> 405 Method Not Allowed
    assert client.post(reverse("amenities_v1:amenity-catalog"), {}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    # 4. DELETE on opening hours -> 405 Method Not Allowed
    assert client.delete(f"{reverse('gyms_v1:gym-opening-hours')}?gym_id={gym.id}").status_code == status.HTTP_405_METHOD_NOT_ALLOWED


# =====================================================================
# 11. STANDARDIZED ERROR ENVELOPE FORMAT VALIDATION
# =====================================================================

@pytest.mark.django_db
def test_standardized_error_envelope_consistency():
    owner, client, _ = create_user_with_tokens("envelope_test@manygym.com")

    # Trigger a 400 validation error
    res = client.post(reverse("gyms_v1:gym-create"), {"name": ""}, format="json")
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    data = res.json()

    # Must contain code, message, details
    assert "code" in data
    assert "message" in data
    assert "details" in data
    assert data["code"] == "VALIDATION_ERROR"
