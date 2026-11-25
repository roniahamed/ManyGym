# Central Search API & Frontend Integration Documentation

## 1. General Configuration

- **Method:** `GET`
- **Endpoint:** `/api/v1/search/`
- **Authentication:** Required (`Bearer <access_token>`)
- **Headers:**
  - `Authorization: Bearer <access_token>` (Required)
  - `Accept: application/json`
- **Response Format:** `application/json`

---

## 2. Endpoint Modes

| Mode | Query Setting | Behavior |
| :--- | :--- | :--- |
| **Search Bar Preview & All Tab** | `filter=all` (default) | Returns grouped top items for `gyms`, `people`, `posts`, `membership_plans`, and `amenities` (capped by `limit`, default `5`) plus `counts`. |
| **Dedicated Search Result Page Tab** | `filter=gym \| people \| post \| plan \| amenity` | Returns paginated results (`page`, `page_size`) for the selected category alongside `query`, `filter`, and `counts`. |

---

## 3. Request Query Parameters

### 3.1. Core & Pagination Parameters

| Parameter | Type | Required | Default | Validation & Constraints | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `q` | `string` | Optional | `""` | Max length: `255`. Null characters (`\u0000`) rejected. | Search keyword matching gyms, people, posts, membership plans, or amenities. |
| `search` | `string` | Optional | `""` | Max length: `255`. | Alias for `q` (used when `q` is omitted or empty). |
| `filter` | `string` | Optional | `"all"` | Canonical: `all`, `gym`, `people`, `post`, `plan`, `amenity`. Aliases: `gyms`, `person`, `user`, `users`, `posts`, `plans`, `membership_plan`, `membership_plans`, `amenities`. Case-insensitive. | Target search category. |
| `type` | `string` | Optional | `null` | Same values and aliases as `filter`. | Alias for `filter` (used when `filter` is not explicitly provided). |
| `limit` | `integer` | Optional | `5` | Min: `1`, Max: `20`. | Maximum items per category when `filter=all`. |
| `page` | `integer` | Optional | `1` | Min: `1`. | Page number when `filter` is a single category. |
| `page_size` | `integer` | Optional | `20` | Min: `1`, Max: `100`. | Items per page when `filter` is a single category. |

### 3.2. Gym & Location Filters

| Parameter | Type | Required | Default | Allowed Values / Constraints | Applies To |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `city` | `string` | Optional | `""` | Max length: `100`. Case-insensitive substring match. | Gyms, People (public or followed), Membership Plans, Amenities |
| `gym_category` | `string` | Optional | `null` | `general_fitness_gym`, `strength_bodybuilding_gym`, `functional_fitness_gym`, `personal_training_studio`, `boutique_fitness_studio`, `boxing_martial_arts_gym`, `yoga_pilates_studio`, `indoor_cycling_studio`, `sports_performance_centre`, `other` | Gyms (primary or secondary type), Membership Plans, Amenities |
| `category` | `string` | Optional | `null` | Same values as `gym_category`. | Alias for `gym_category` (used when `gym_category` is omitted) |
| `gender_required` | `string` | Optional | `null` | `everyone`, `women_only`, `men_only` | Gyms |
| `latitude` | `number` | Optional | `null` | Min: `-90.0`, Max: `90.0`. Required if `longitude` is provided. | Gyms |
| `longitude` | `number` | Optional | `null` | Min: `-180.0`, Max: `180.0`. Required if `latitude` is provided. | Gyms |
| `radius` | `number` | Optional | `20.0` | Min: `0.1`, Max: `500.0` (km). | Gyms |

### 3.3. People Filters

| Parameter | Type | Required | Default | Allowed Values / Constraints | Applies To |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `gender` | `string` | Optional | `null` | `male`, `female`, `other`, `prefer_not_to_say` | People (public or followed profiles) |
| `is_following` | `boolean` | Optional | `null` | `true`, `false` | People |

### 3.4. Post, Membership Plan & Amenity Filters

| Parameter | Type | Required | Default | Allowed Values / Constraints | Applies To |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `owner_type` | `string` | Optional | `null` | `user`, `gym` | Posts |
| `is_repost` | `boolean` | Optional | `null` | `true`, `false` | Posts |
| `plan_type` | `string` | Optional | `null` | `time_based`, `session_based` | Membership Plans |
| `amenity_group` | `string` | Optional | `null` | `changing_and_storage`, `wellness_and_recovery`, `comfort_and_convenience`, `food_and_drink`, `parking_and_transport`, `accessibility`, `family_facilities` | Amenities |
| `is_paid` | `boolean` | Optional | `null` | `true`, `false` | Amenities |

---

## 4. Request Payload (JSON Query Parameters)

Since `GET /api/v1/search/` is a `GET` endpoint, parameters are transmitted as URL query parameters. Below are the equivalent JSON parameter payloads.

### 4.1. Overview Search Request (`filter=all`)

```json
{
  "q": "Titan",
  "filter": "all",
  "limit": 5,
  "city": "Dhaka"
}
```

### 4.2. Dedicated Search Page — Gym Filter Request

```json
{
  "q": "Titan",
  "filter": "gym",
  "gym_category": "strength_bodybuilding_gym",
  "gender_required": "everyone",
  "city": "Dhaka",
  "latitude": 23.7465,
  "longitude": 90.376,
  "radius": 20.0,
  "page": 1,
  "page_size": 20
}
```

### 4.3. Dedicated Search Page — People Filter Request

```json
{
  "q": "Bob",
  "filter": "people",
  "city": "Dhaka",
  "gender": "male",
  "is_following": true,
  "page": 1,
  "page_size": 20
}
```

### 4.4. Dedicated Search Page — Post, Plan & Amenity Filter Requests

```json
{
  "q": "Titan",
  "filter": "post",
  "owner_type": "gym",
  "is_repost": false,
  "page": 1,
  "page_size": 20
}
```

```json
{
  "q": "Monthly",
  "filter": "plan",
  "plan_type": "time_based",
  "city": "Dhaka",
  "gym_category": "strength_bodybuilding_gym",
  "page": 1,
  "page_size": 20
}
```

```json
{
  "q": "Sauna",
  "filter": "amenity",
  "amenity_group": "wellness_and_recovery",
  "is_paid": false,
  "city": "Dhaka",
  "gym_category": "strength_bodybuilding_gym",
  "page": 1,
  "page_size": 20
}
```

---

## 5. Response Schema Specification (All Fields)

### 5.1. Top-Level Response Envelope (`filter=all`)

| Field Path | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `query` | `string` | No | Normalized search keyword (`""` when omitted). |
| `filter` | `string` | No | Canonical active filter (`"all"`). |
| `counts` | `object` | No | Total matching counts across all 5 categories. |
| `results` | `object` | No | Grouped arrays of matching items capped by `limit`. |
| `results.gyms` | `array<object>` | No | List of matching gym objects. |S
| `results.people` | `array<object>` | No | List of matching person objects. |
| `results.posts` | `array<object>` | No | List of matching post/repost objects. |
| `results.membership_plans` | `array<object>` | No | List of matching active membership plan objects. |
| `results.amenities` | `array<object>` | No | List of matching gym-configured amenity objects. |

### 5.2. Top-Level Paginated Response Envelope (`filter=gym | people | post | plan | amenity`)

| Field Path | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `query` | `string` | No | Normalized search keyword (`""` when omitted). |
| `filter` | `string` | No | Canonical active filter (`"gym"`, `"people"`, `"post"`, `"plan"`, or `"amenity"`). |
| `counts` | `object` | No | Total matching counts across all 5 categories for search result tabs. |
| `count` | `integer` | No | Total matching records in the active `filter` category. |
| `total_pages` | `integer` | No | Total pagination pages. |
| `current_page` | `integer` | No | Current page number. |
| `next` | `string (uri)` | Yes | Next page URL (`null` on last page). |
| `previous` | `string (uri)` | Yes | Previous page URL (`null` on first page). |
| `results` | `array<object>` | No | Paginated list of items matching the active `filter` schema. |

### 5.3. `counts` Object

| Field Path | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `counts.gyms` | `integer` | No | Total matching gyms. |
| `counts.people` | `integer` | No | Total matching people. |
| `counts.posts` | `integer` | No | Total matching posts and reposts. |
| `counts.membership_plans` | `integer` | No | Total matching active membership plans. |
| `counts.amenities` | `integer` | No | Total matching gym-configured amenities. |
| `counts.total` | `integer` | No | Sum of all 5 category counts. |

### 5.4. Gym Item Schema (`gyms[]` / `filter=gym`)

| Field Path | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string (uuid)` | No | Gym unique identifier. |
| `name` | `string` | No | Gym name. |
| `profile_picture_url` | `string (uri)` | Yes | Absolute URL to gym profile picture. |
| `cover_photo_url` | `string (uri)` | Yes | Absolute URL to gym cover photo. |
| `short_description` | `string` | Yes | Gym description text. |
| `primary_type` | `string` | No | Primary gym category key. |
| `primary_type_display` | `string` | No | Human-readable primary category label. |
| `secondary_type` | `string` | Yes | Secondary gym category key. |
| `secondary_type_display` | `string` | Yes | Human-readable secondary category label. |
| `gender_required` | `string` | No | Gender policy (`everyone`, `women_only`, `men_only`). |
| `gender_required_display` | `string` | No | Human-readable gender policy label. |
| `min_age` | `integer` | No | Minimum required member age. |
| `timezone` | `string` | No | IANA timezone string. |
| `location` | `object` | Yes | Primary gym location object (`null` if unset). |
| `location.id` | `string (uuid)` | No | Location unique identifier. |
| `location.address` | `string` | No | Street address. |
| `location.latitude` | `string (decimal)` | No | Latitude coordinate (`8` decimal places). |
| `location.longitude` | `string (decimal)` | No | Longitude coordinate (`8` decimal places). |
| `location.city` | `string` | Yes | City name. |
| `location.country` | `string` | Yes | Country name. |
| `location.postal_code` | `string` | Yes | Postal/ZIP code. |
| `location.is_primary` | `boolean` | No | Whether this is the primary location. |
| `location.updated_at` | `string (datetime)` | No | ISO-8601 location update timestamp. |
| `distance_km` | `number` | Yes | Distance in kilometers when `latitude` and `longitude` are provided; `null` otherwise. |
| `is_open_now` | `boolean` | No | Live open/closed status evaluated in the gym's timezone. |
| `today_opening_hours` | `string` | No | Today's hours (e.g. `"06:00 - 22:00"` or `"Closed"`). |
| `amenities_preview` | `array<string>` | No | Preview list of up to 10 amenity names. |
| `followers_count` | `integer` | No | Total followers of the gym. |
| `is_following` | `boolean` | No | Whether the authenticated user follows the gym. |
| `created_at` | `string (datetime)` | No | ISO-8601 gym creation timestamp. |

### 5.5. Person Item Schema (`people[]` / `filter=people`)

| Field Path | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string (uuid)` | No | User unique identifier. |
| `first_name` | `string` | No | User first name. |
| `last_name` | `string` | No | User last name. |
| `full_name` | `string` | No | Concatenated full name (`first_name last_name`). |
| `avatar_url` | `string (uri)` | Yes | Absolute URL to user avatar image. |
| `is_private` | `boolean` | No | Whether the user's account is private. |
| `city` | `string` | Yes | User city (`null` if `is_private=true` and viewer does not follow). |
| `home_town` | `string` | Yes | User hometown (`null` if `is_private=true` and viewer does not follow). |
| `about_you` | `string` | Yes | User short bio (`null` if `is_private=true` and viewer does not follow). |
| `followers_count` | `integer` | No | Total followers of the user. |
| `is_following` | `boolean` | No | Whether the authenticated user follows this person. |
| `has_pending_follow_request` | `boolean` | No | Whether the authenticated user has a pending follow request to this person. |

### 5.6. Post Item Schema (`posts[]` / `filter=post`)

| Field Path | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string (uuid)` | No | Post unique identifier. |
| `owner_type` | `string` | No | Author entity type (`user` or `gym`). |
| `gym_id` | `string (uuid)` | Yes | Owning gym UUID (`null` when `owner_type="user"`). |
| `gym_name` | `string` | Yes | Owning gym name (`null` when `owner_type="user"`). |
| `gym_avatar_url` | `string (uri)` | Yes | Absolute URL to owning gym profile picture. |
| `author_user_id` | `string (uuid)` | No | Author user UUID. |
| `author_name` | `string` | No | Author display name (or email fallback). |
| `author_avatar_url` | `string (uri)` | Yes | Absolute URL to author user avatar. |
| `content_text` | `string` | Yes | Post text content. |
| `privacy` | `string` | No | Privacy level (`public`, `followers`, `members_only`, `gym_members_only`, `private`). |
| `is_repost` | `boolean` | No | Whether this post is a repost/share. |
| `source_post_id` | `string (uuid)` | Yes | Original post UUID when `is_repost=true`. |
| `source_post` | `object` | Yes | Original post summary (`null` if not a repost or `source_post_unavailable=true`). |
| `source_post_unavailable` | `boolean` | No | `true` when `is_repost=true` and the original post is deleted or restricted for the viewer. |
| `reposts_count` | `integer` | No | Total repost count. |
| `comments_count` | `integer` | No | Total comment count. |
| `reactions_count` | `integer` | No | Total reaction count. |
| `published_at` | `string (datetime)` | No | ISO-8601 publication timestamp. |
| `media_count` | `integer` | No | Number of attached media items. |
| `media_attachments` | `array<object>` | No | Ordered list of attached media items. |
| `is_following_gym` | `boolean` | No | Whether the authenticated user follows the owning gym (`false` for user posts). |
| `is_following_author` | `boolean` | No | Whether the authenticated user follows the post author. |
| `is_connected_gym` | `boolean` | No | Whether the authenticated user is owner, active staff, or member of the owning gym. |
| `created_at` | `string (datetime)` | No | ISO-8601 creation timestamp. |
| `updated_at` | `string (datetime)` | No | ISO-8601 update timestamp. |

#### `source_post` Object (`posts[].source_post`)

| Field Path | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string (uuid)` | No | Original post UUID. |
| `owner_type` | `string` | No | Original post owner type (`user` or `gym`). |
| `gym_id` | `string (uuid)` | Yes | Original post gym UUID. |
| `gym_name` | `string` | Yes | Original post gym name. |
| `gym_avatar_url` | `string (uri)` | Yes | Original post gym profile picture URL. |
| `author_user_id` | `string (uuid)` | No | Original post author user UUID. |
| `author_name` | `string` | No | Original post author display name. |
| `author_avatar_url` | `string (uri)` | Yes | Original post author avatar URL. |
| `content_text` | `string` | Yes | Original post text content. |
| `privacy` | `string` | No | Original post privacy level. |
| `is_repost` | `boolean` | No | Whether the source post itself is a repost. |
| `source_post_id` | `string (uuid)` | Yes | Upstream source post UUID if nested. |
| `reposts_count` | `integer` | No | Original post repost count. |
| `comments_count` | `integer` | No | Original post comment count. |
| `reactions_count` | `integer` | No | Original post reaction count. |
| `published_at` | `string (datetime)` | No | ISO-8601 publication timestamp. |
| `media_count` | `integer` | No | Number of media items on the original post. |
| `media_attachments` | `array<object>` | No | Ordered list of original post media attachments. |
| `created_at` | `string (datetime)` | No | ISO-8601 creation timestamp. |
| `updated_at` | `string (datetime)` | No | ISO-8601 update timestamp. |

#### Media Attachment Object (`media_attachments[]`)

| Field Path | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string (uuid)` | No | Media attachment unique identifier. |
| `post_id` | `string (uuid)` | No | Parent post UUID. |
| `media_url` | `string (uri)` | No | Resolved primary media URL. |
| `original_url` | `string (uri)` | Yes | Original uploaded asset URL. |
| `optimized_url` | `string (uri)` | Yes | Background-optimized asset URL. |
| `media_type` | `string` | No | Media type (`picture` or `video`). |
| `thumbnail_url` | `string (uri)` | Yes | Resolved thumbnail/poster image URL. |
| `file_size_bytes` | `integer` | No | File size in bytes. |
| `order_index` | `integer` | No | Zero-based display order index. |
| `processing_status` | `string` | No | Async optimization status (`pending`, `processing`, `completed`, `failed`). |
| `created_at` | `string (datetime)` | No | ISO-8601 creation timestamp. |

### 5.7. Membership Plan Item Schema (`membership_plans[]` / `filter=plan`)

| Field Path | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string (uuid)` | No | Membership plan unique identifier. |
| `gym_id` | `string (uuid)` | No | Owning gym UUID. |
| `gym_name` | `string` | No | Owning gym name. |
| `gym_profile_picture_url` | `string (uri)` | Yes | Absolute URL to owning gym profile picture. |
| `city` | `string` | Yes | Primary city of the owning gym. |
| `name` | `string` | No | Membership plan name. |
| `description` | `string` | Yes | Membership plan description. |
| `plan_type` | `string` | No | Plan type key (`time_based` or `session_based`). |
| `plan_type_display` | `string` | No | Human-readable plan type label (`Time Based` or `Session Based`). |
| `price` | `string (decimal)` | No | Plan price formatted to `2` decimal places. |
| `duration_value` | `integer` | No | Numeric duration quantity. |
| `duration_unit` | `string` | No | Duration unit (`day`, `week`, `month`, `session`). |
| `duration_display` | `string` | No | Formatted duration label (e.g. `"1 Month"`, `"10 Sessions"`). |
| `joining_fee` | `string (decimal)` | No | One-time joining fee formatted to `2` decimal places. |
| `included_amenities_count` | `integer` | No | Count of bundled gym amenities included in the plan. |
| `created_at` | `string (datetime)` | No | ISO-8601 creation timestamp. |

### 5.8. Amenity Item Schema (`amenities[]` / `filter=amenity`)

| Field Path | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string (uuid)` | No | Gym-configured amenity record UUID (`GymAmenity.id`). |
| `amenity_id` | `string (uuid)` | No | Master catalog amenity UUID (`AmenityCatalog.id`). |
| `name` | `string` | No | Amenity display name. |
| `group_name` | `string` | No | Amenity group key. |
| `group_display` | `string` | No | Human-readable amenity group label. |
| `is_paid` | `boolean` | No | `true` if paid extra amenity; `false` if complimentary. |
| `default_price` | `string (decimal)` | No | Amenity price formatted to `2` decimal places (`"0.00"` when free). |
| `gym_id` | `string (uuid)` | No | Owning gym UUID. |
| `gym_name` | `string` | No | Owning gym name. |
| `gym_profile_picture_url` | `string (uri)` | Yes | Absolute URL to owning gym profile picture. |
| `city` | `string` | Yes | Primary city of the owning gym. |

---

## 6. JSON Response Examples

### 6.1. `200 OK` — Grouped Overview (`GET /api/v1/search/?q=Titan&filter=all&limit=5`)

```json
{
  "query": "Titan",
  "filter": "all",
  "counts": {
    "gyms": 1,
    "people": 1,
    "posts": 1,
    "membership_plans": 1,
    "amenities": 1,
    "total": 5
  },
  "results": {
    "gyms": [
      {
        "id": "e93f9dc2-7c18-4b72-9112-78d10b7b1201",
        "name": "Titan Strength Club",
        "profile_picture_url": "https://api.manygym.com/media/gyms/profiles/titan.webp",
        "cover_photo_url": "https://api.manygym.com/media/gyms/covers/titan_cover.webp",
        "short_description": "A premier fitness institution dedicated to empowering members with elite strength equipment.",
        "primary_type": "strength_bodybuilding_gym",
        "primary_type_display": "Strength & Bodybuilding Gym",
        "secondary_type": "functional_fitness_gym",
        "secondary_type_display": "Functional Fitness Gym",
        "gender_required": "everyone",
        "gender_required_display": "Everyone",
        "min_age": 16,
        "timezone": "Asia/Dhaka",
        "location": {
          "id": "a12bc34d-0000-0000-0000-000000000001",
          "address": "House 12, Road 7, Dhanmondi",
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
        "amenities_preview": [
          "Titan Infrared Sauna",
          "Showers"
        ],
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
        "avatar_url": "https://api.manygym.com/media/users/avatars/bob.webp",
        "is_private": false,
        "city": "Dhaka",
        "home_town": "Sylhet",
        "about_you": "Powerlifting coach at Titan Strength Club.",
        "followers_count": 58,
        "is_following": true,
        "has_pending_follow_request": false
      }
    ],
    "posts": [
      {
        "id": "f1a2b3c4-d5e6-7890-abcd-1234567890ef",
        "owner_type": "user",
        "gym_id": null,
        "gym_name": null,
        "gym_avatar_url": null,
        "author_user_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "author_name": "Bob Titan",
        "author_avatar_url": "https://api.manygym.com/media/users/avatars/bob.webp",
        "content_text": "Reposting Titan Strength Club squat rack upgrade!",
        "privacy": "public",
        "is_repost": true,
        "source_post_id": "11223344-5566-7788-99aa-bbccddeeff00",
        "source_post": {
          "id": "11223344-5566-7788-99aa-bbccddeeff00",
          "owner_type": "gym",
          "gym_id": "e93f9dc2-7c18-4b72-9112-78d10b7b1201",
          "gym_name": "Titan Strength Club",
          "gym_avatar_url": "https://api.manygym.com/media/gyms/profiles/titan.webp",
          "author_user_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
          "author_name": "Bob Titan",
          "author_avatar_url": "https://api.manygym.com/media/users/avatars/bob.webp",
          "content_text": "New competition squat racks arrived today.",
          "privacy": "public",
          "is_repost": false,
          "source_post_id": null,
          "reposts_count": 4,
          "comments_count": 9,
          "reactions_count": 37,
          "published_at": "2026-11-24T09:00:00Z",
          "media_count": 1,
          "media_attachments": [
            {
              "id": "99887766-5544-3322-1100-ffeeddccbbaa",
              "post_id": "11223344-5566-7788-99aa-bbccddeeff00",
              "media_url": "https://api.manygym.com/media/posts/racks_optimized.webp",
              "original_url": "https://api.manygym.com/media/posts/racks.jpg",
              "optimized_url": "https://api.manygym.com/media/posts/racks_optimized.webp",
              "media_type": "picture",
              "thumbnail_url": "https://api.manygym.com/media/posts/racks_thumb.webp",
              "file_size_bytes": 420512,
              "order_index": 0,
              "processing_status": "completed",
              "created_at": "2026-11-24T09:00:00Z"
            }
          ],
          "created_at": "2026-11-24T09:00:00Z",
          "updated_at": "2026-11-24T09:00:00Z"
        },
        "source_post_unavailable": false,
        "reposts_count": 0,
        "comments_count": 2,
        "reactions_count": 11,
        "published_at": "2026-11-25T08:30:00Z",
        "media_count": 0,
        "media_attachments": [],
        "is_following_gym": false,
        "is_following_author": true,
        "is_connected_gym": false,
        "created_at": "2026-11-25T08:30:00Z",
        "updated_at": "2026-11-25T08:30:00Z"
      }
    ],
    "membership_plans": [
      {
        "id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
        "gym_id": "e93f9dc2-7c18-4b72-9112-78d10b7b1201",
        "gym_name": "Titan Strength Club",
        "gym_profile_picture_url": "https://api.manygym.com/media/gyms/profiles/titan.webp",
        "city": "Dhaka",
        "name": "Titan Gold Monthly",
        "description": "Full access to all Titan strength equipment, coaching, and sauna facilities.",
        "plan_type": "time_based",
        "plan_type_display": "Time Based",
        "price": "59.99",
        "duration_value": 1,
        "duration_unit": "month",
        "duration_display": "1 Month",
        "joining_fee": "10.00",
        "included_amenities_count": 2,
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
        "gym_profile_picture_url": "https://api.manygym.com/media/gyms/profiles/titan.webp",
        "city": "Dhaka"
      }
    ]
  }
}
```

### 6.2. `200 OK` — Empty Search (No `q` and No Filters)

```json
{
  "query": "",
  "filter": "all",
  "counts": {
    "gyms": 0,
    "people": 0,
    "posts": 0,
    "membership_plans": 0,
    "amenities": 0,
    "total": 0
  },
  "results": {
    "gyms": [],
    "people": [],
    "posts": [],
    "membership_plans": [],
    "amenities": []
  }
}
```

### 6.3. `200 OK` — Paginated Tab (`GET /api/v1/search/?q=Titan&filter=gym&latitude=23.7465&longitude=90.3760&page=1&page_size=20`)

```json
{
  "query": "Titan",
  "filter": "gym",
  "counts": {
    "gyms": 1,
    "people": 1,
    "posts": 1,
    "membership_plans": 1,
    "amenities": 1,
    "total": 5
  },
  "count": 1,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "e93f9dc2-7c18-4b72-9112-78d10b7b1201",
      "name": "Titan Strength Club",
      "profile_picture_url": "https://api.manygym.com/media/gyms/profiles/titan.webp",
      "cover_photo_url": "https://api.manygym.com/media/gyms/covers/titan_cover.webp",
      "short_description": "A premier fitness institution dedicated to empowering members with elite strength equipment.",
      "primary_type": "strength_bodybuilding_gym",
      "primary_type_display": "Strength & Bodybuilding Gym",
      "secondary_type": "functional_fitness_gym",
      "secondary_type_display": "Functional Fitness Gym",
      "gender_required": "everyone",
      "gender_required_display": "Everyone",
      "min_age": 16,
      "timezone": "Asia/Dhaka",
      "location": {
        "id": "a12bc34d-0000-0000-0000-000000000001",
        "address": "House 12, Road 7, Dhanmondi",
        "latitude": "23.74650000",
        "longitude": "90.37600000",
        "city": "Dhaka",
        "country": "Bangladesh",
        "postal_code": "1205",
        "is_primary": true,
        "updated_at": "2026-11-09T18:00:00Z"
      },
      "distance_km": 0.0,
      "is_open_now": true,
      "today_opening_hours": "06:00 - 22:00",
      "amenities_preview": [
        "Titan Infrared Sauna",
        "Showers"
      ],
      "followers_count": 142,
      "is_following": true,
      "created_at": "2026-11-01T10:00:00Z"
    }
  ]
}
```

### 6.4. `200 OK` — Paginated Tab (`GET /api/v1/search/?q=Bob&filter=people&page=1&page_size=20`)

```json
{
  "query": "Bob",
  "filter": "people",
  "counts": {
    "gyms": 0,
    "people": 1,
    "posts": 1,
    "membership_plans": 0,
    "amenities": 0,
    "total": 2
  },
  "count": 1,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "first_name": "Bob",
      "last_name": "Titan",
      "full_name": "Bob Titan",
      "avatar_url": "https://api.manygym.com/media/users/avatars/bob.webp",
      "is_private": false,
      "city": "Dhaka",
      "home_town": "Sylhet",
      "about_you": "Powerlifting coach at Titan Strength Club.",
      "followers_count": 58,
      "is_following": true,
      "has_pending_follow_request": false
    }
  ]
}
```

### 6.5. `400 Bad Request` — Validation Error

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Validation failed for the submitted data.",
  "details": {
    "filter": [
      "Invalid search filter 'unknown'. Allowed values: all, gym, people, post, plan, amenity."
    ]
  }
}
```

### 6.6. `401 Unauthorized` — Missing or Invalid Authentication

```json
{
  "code": "AUTHENTICATION_REQUIRED",
  "message": "Authentication credentials were not provided or are invalid.",
  "details": {
    "detail": "Authentication credentials were not provided."
  }
}
```

---

## 7. Visibility, Privacy & Filtering Rules

1. **Authentication:** Unauthenticated requests return `401 Unauthorized`.
2. **Gyms, Membership Plans & Amenities:** Soft-deleted, deactivated, and unpublished gyms are excluded, as are gyms that blocked the requesting user. Only `active` membership plans are returned.
3. **People:** Excludes the requesting user, soft-deleted/deactivated users, and mutually blocked users. Private accounts (`is_private=true`) only match on `first_name` and `last_name` and return `city`, `home_town`, and `about_you` as `null` to non-followers.
4. **Posts:** Enforces post privacy (`public`, `followers`, `members_only`, `private`), mutual user/gym blocks, gym age restrictions, and `source_post_unavailable` redaction for restricted repost sources.
