# Central Search API & Frontend Integration Documentation

## 1. Overview

This document defines the backend API contract and frontend integration architecture for Many Gym's **Central Search** experience across both:
1. **Global Search Bar Quick Preview** (`filter=all`) — top results grouped by category with live counts.
2. **Dedicated Search Result Page** (`filter=all | gym | people | post | plan | amenity`) — full tabbed, filterable, paginated search results across Gyms, People, Posts, Membership Plans, and Amenities.

---

## 2. General Configuration

- **Endpoint:** `GET /api/v1/search/`
- **Authentication:** Required (`IsAuthenticated`)
- **Headers:**
  - `Authorization: Bearer <access_token>` (Required)
  - `Accept: application/json`
- **Response Format:** `application/json`

---

## 3. Frontend UI Architecture: Search Bar + Dedicated Search Result Page

### 3.1. Global Header Search Bar (Quick Dropdown)
- Debounce user typing (`300ms`) and call `GET /api/v1/search/?q=<query>&filter=all&limit=5`.
- Render grouped sections in the dropdown (`Gyms`, `People`, `Posts`, `Membership Plans`, `Amenities`) using `results.*` and show category totals from `counts.*`.
- Pressing **Enter** or clicking **"See all results"** navigates to the **Dedicated Search Result Page**, e.g.:
  - `/search?q=<encoded_query>&filter=all`

### 3.2. Dedicated Search Result Page (`/search`)
- **URL State Sync:** Sync query string state (`q`, `filter`, `page`, and active Gym/People/Other filters) with browser URL search params so searches are shareable and back/forward navigation works cleanly.
- **Category Tabs (with live badge counts from `counts`):**
  - **All** (`filter=all`) — displays section previews with a "View all X" CTA that switches `filter` to that tab.
  - **Gyms** (`filter=gym`) — paginated gym cards (`StandardResultsSetPagination`), showing Gym filters (`city`, `gym_category`, `gender_required`, and optional `Use My Location` with `latitude`, `longitude`, `radius`).
  - **People** (`filter=people`) — paginated person cards with Follow / Requested / Following button states (`is_following`, `has_pending_follow_request`, `is_private`), showing People filters (`city`, `gender`, `is_following`).
  - **Posts** (`filter=post`) — paginated feed post/repost cards (`GymPostListSerializer` schema), showing Post filters (`owner_type`, `is_repost`).
  - **Membership Plans** (`filter=plan`) — paginated active membership plan cards linking to the gym, showing Plan filters (`plan_type`, `city`, `gym_category`).
  - **Amenities** (`filter=amenity`) — paginated gym amenity cards linking to the gym, showing Amenity filters (`amenity_group`, `is_paid`, `city`, `gym_category`).

---

## 4. Query Parameters Reference

### 4.1. Core Parameters

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `q` | `string` | Optional | `""` | Free-text search keyword (max 255 chars). Alias: `search`. |
| `filter` | `string` | Optional | `"all"` | Target scope: `all`, `gym`, `people`, `post`, `plan`, `amenity` (plurals & `users`/`membership_plans` aliases supported). Alias: `type`. |
| `limit` | `integer` | Optional | `5` | Max items per category returned when `filter=all` (min: `1`, max: `20`). |
| `page` | `integer` | Optional | `1` | Page number when `filter != all` (min: `1`). |
| `page_size` | `integer` | Optional | `20` | Items per page when `filter != all` (min: `1`, max: `100`). |

### 4.2. Gym & Location Filters

| Parameter | Type | Allowed Values / Constraints | Applies To |
| :--- | :--- | :--- | :--- |
| `city` | `string` | Max 100 chars (case-insensitive substring match) | Gyms, People (public/followed), Plans, Amenities |
| `gym_category` | `string` | `general_fitness_gym`, `strength_bodybuilding_gym`, `functional_fitness_gym`, `personal_training_studio`, `boutique_fitness_studio`, `boxing_martial_arts_gym`, `yoga_pilates_studio`, `indoor_cycling_studio`, `sports_performance_centre`, `other` (Alias: `category`) | Gyms, Plans, Amenities |
| `gender_required` | `string` | `everyone`, `women_only`, `men_only` | Gyms |
| `latitude` | `number` | `-90.0` to `90.0` (must be paired with `longitude`) | Gyms |
| `longitude` | `number` | `-180.0` to `180.0` (must be paired with `latitude`) | Gyms |
| `radius` | `number` | `0.1` to `500.0` km (default: `20.0`) | Gyms |

### 4.3. People Filters

| Parameter | Type | Allowed Values | Applies To |
| :--- | :--- | :--- | :--- |
| `gender` | `string` | `male`, `female`, `other`, `prefer_not_to_say` | People (public/followed profiles) |
| `is_following` | `boolean` | `true` or `false` | People |

### 4.4. Post, Plan & Amenity ("Others") Filters

| Parameter | Type | Allowed Values | Applies To |
| :--- | :--- | :--- | :--- |
| `owner_type` | `string` | `user`, `gym` | Posts |
| `is_repost` | `boolean` | `true` or `false` | Posts |
| `plan_type` | `string` | `time_based`, `session_based` | Membership Plans |
| `amenity_group` | `string` | `changing_and_storage`, `wellness_and_recovery`, `comfort_and_convenience`, `food_and_drink`, `parking_and_transport`, `accessibility`, `family_facilities` | Amenities |
| `is_paid` | `boolean` | `true` or `false` | Amenities |

---

## 5. Responses & Examples

### 5.1. Overview Response (`GET /api/v1/search/?q=Titan&filter=all&limit=5`)

```json
{
  "query": "Titan",
  "filter": "all",
  "counts": {
    "gyms": 2,
    "people": 1,
    "posts": 3,
    "membership_plans": 1,
    "amenities": 1,
    "total": 8
  },
  "results": {
    "gyms": [
      {
        "id": "e93f9dc2-7c18-4b72-9112-78d10b7b1201",
        "name": "Titan Strength Club",
        "profile_picture_url": "https://api.manygym.com/media/gyms/profiles/titan.webp",
        "cover_photo_url": null,
        "short_description": "A premier fitness institution...",
        "primary_type": "strength_bodybuilding_gym",
        "primary_type_display": "Strength & Bodybuilding Gym",
        "secondary_type": null,
        "secondary_type_display": null,
        "gender_required": "everyone",
        "gender_required_display": "Everyone",
        "min_age": 16,
        "timezone": "UTC",
        "location": {
          "id": "a12bc34d-0000-0000-0000-000000000001",
          "address": "Road 7, Dhanmondi",
          "latitude": "23.74650000",
          "longitude": "90.37600000",
          "city": "Dhaka",
          "country": "Bangladesh",
          "postal_code": "1205",
          "is_primary": true,
          "updated_at": "2026-11-09T18:00:00Z"
        },
        "distance_km": null,
        "is_open_now": true,
        "today_opening_hours": "06:00 - 22:00",
        "amenities_preview": ["Titan Infrared Sauna"],
        "followers_count": 142,
        "is_following": true,
        "created_at": "2026-11-01T10:00:00Z"
      }
    ],
    "people": [
      {
        "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "first_name": "Bob",
        "last_name": "Titan",
        "full_name": "Bob Titan",
        "avatar_url": null,
        "is_private": false,
        "city": "Dhaka",
        "home_town": "Sylhet",
        "about_you": "Powerlifting coach at Titan",
        "followers_count": 1,
        "is_following": true,
        "has_pending_follow_request": false
      }
    ],
    "posts": [],
    "membership_plans": [
      {
        "id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
        "gym_id": "e93f9dc2-7c18-4b72-9112-78d10b7b1201",
        "gym_name": "Titan Strength Club",
        "gym_profile_picture_url": null,
        "city": "Dhaka",
        "name": "Titan Gold Monthly",
        "description": "Full access to all Titan strength equipment...",
        "plan_type": "time_based",
        "plan_type_display": "Time Based",
        "price": "59.99",
        "duration_value": 1,
        "duration_unit": "month",
        "duration_display": "1 Month",
        "joining_fee": "0.00",
        "included_amenities_count": 0,
        "created_at": "2026-11-01T10:00:00Z"
      }
    ],
    "amenities": [
      {
        "id": "d4e5f6a7-b8c9-0123-def0-123456789013",
        "amenity_id": "f5e6a7b8-c9d0-1234-ef01-234567890124",
        "name": "Titan Infrared Sauna",
        "group_name": "wellness_and_recovery",
        "group_display": "Wellness & Recovery",
        "is_paid": false,
        "default_price": "0.00",
        "gym_id": "e93f9dc2-7c18-4b72-9112-78d10b7b1201",
        "gym_name": "Titan Strength Club",
        "gym_profile_picture_url": null,
        "city": "Dhaka"
      }
    ]
  }
}
```

### 5.2. Paginated Tab Response (`GET /api/v1/search/?q=Titan&filter=gym&page=1&page_size=20`)

```json
{
  "query": "Titan",
  "filter": "gym",
  "counts": {
    "gyms": 2,
    "people": 1,
    "posts": 3,
    "membership_plans": 1,
    "amenities": 1,
    "total": 8
  },
  "count": 2,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "e93f9dc2-7c18-4b72-9112-78d10b7b1201",
      "name": "Titan Strength Club",
      "primary_type": "strength_bodybuilding_gym",
      "primary_type_display": "Strength & Bodybuilding Gym",
      "is_following": true
    }
  ]
}
```

---

## 6. Privacy, Visibility & Security Rules

1. **Authentication Required:** Unauthenticated requests receive `401 Unauthorized`.
2. **Gyms, Plans & Amenities:** Automatically exclude unpublished, deactivated, soft-deleted gyms, and gyms that blocked the requesting user. Only `active` membership plans are searchable.
3. **People:** Excludes self, soft-deleted/deactivated accounts, and mutually blocked users. Private accounts (`is_private=true`) are only matchable by name (`first_name`, `last_name`) and hide `city`, `home_town`, and `about_you` unless already followed.
4. **Posts:** Enforces the same privacy (`public`, `followers`, `members_only`, `private`), blocklist, and gym age-restriction checks as the Community Feed.

---

## 7. Error Responses

| Status Code | Code | Meaning |
| :--- | :--- | :--- |
| `400 Bad Request` | `VALIDATION_ERROR` | Invalid `filter`, invalid choice enum, `latitude` without `longitude`, or null characters in `q`. |
| `401 Unauthorized` | `UNAUTHORIZED` | Missing or invalid Bearer JWT token. |
