# Frontend Integration Document: Search Nearby Gym & Location Management

## 1. Overview

This document specifies the frontend API contract for Gym Discovery, Nearby Search (Live Location Radius and City/Category filters), Public Gym Details, and Gym Location Management.

---

## 2. API Endpoints Summary

| Feature | Method | Endpoint | Auth Required |
|---|---|---|---|
| Search Nearby Gyms | `GET` | `/api/v1/gyms/nearby/` (Alias: `/api/v1/gyms/search/`) | Optional |
| Get Public Gym Details | `GET` | `/api/v1/gyms/{gym_id}/public/` (Alias: `/api/v1/gyms/{gym_id}/detail/`) | Optional |
| Get Gym Location | `GET` | `/api/v1/gyms/profile/location/` | Required (Bearer JWT) |
| Update Gym Location | `PATCH` | `/api/v1/gyms/profile/location/` | Required (Owner/Staff) |

---

## 3. Endpoint 1: Search Nearby Gyms

Searches gyms within a default 20 km live location radius or by city, category, and keyword.

- **Method:** `GET`
- **Path:** `/api/v1/gyms/nearby/`
- **Headers:**
  - `Accept: application/json`
  - `Authorization: Bearer <access_token>` (Optional)

### 3.1. Query Parameters

| Parameter | Type | Required | Default | Validation & Constraints | Description |
|---|---|---|---|---|---|
| `latitude` | `number` | Optional | `null` | Min: `-90.0`, Max: `90.0`. Required if `longitude` is provided. | User live latitude from browser Geolocation API. |
| `longitude` | `number` | Optional | `null` | Min: `-180.0`, Max: `180.0`. Required if `latitude` is provided. | User live longitude from browser Geolocation API. |
| `radius` | `number` | Optional | `20.0` | Min: `0.1`, Max: `500.0`. Unit: kilometers. | Search radius in kilometers. Defaults to 20 km. |
| `category` | `string` | Optional | `null` | Allowed values: `general_fitness_gym`, `strength_bodybuilding_gym`, `functional_fitness_gym`, `personal_training_studio`, `boutique_fitness_studio`, `boxing_martial_arts_gym`, `yoga_pilates_studio`, `indoor_cycling_studio`, `sports_performance_centre`, `other`. | Filters matching gym primary or secondary type. |
| `city` | `string` | Optional | `null` | Max length: 100 characters. | Case-insensitive city search when user does not share GPS. |
| `search` | `string` | Optional | `null` | Max length: 255 characters. | Free-text search matching name, bio, address, or city. |
| `q` | `string` | Optional | `null` | Max length: 255 characters. | Alias for `search`. |
| `page` | `integer` | Optional | `1` | Min: `1`. | Page number. |
| `page_size` | `integer` | Optional | `20` | Min: `1`, Max: `100`. | Number of items per page. |

### 3.2. Response Payload (`200 OK`)

```json
{
  "count": 2,
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
      "short_description": "A premier fitness institution dedicated to empowering members with elite equipment and guidance.",
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
        "Infrared Sauna",
        "Showers",
        "Free Wi-Fi"
      ],
      "followers_count": 142,
      "is_following": false,
      "created_at": "2026-11-01T10:00:00Z"
    },
    {
      "id": "f84b0ed1-8d29-4c83-a223-89e21c8c2302",
      "name": "Uttara Functional Arena",
      "profile_picture_url": "https://api.manygym.com/media/gyms/profiles/uttara.webp",
      "cover_photo_url": null,
      "short_description": "Elite functional fitness studio offering daily HIIT and strength workouts.",
      "primary_type": "functional_fitness_gym",
      "primary_type_display": "Functional Fitness Gym",
      "secondary_type": null,
      "secondary_type_display": null,
      "gender_required": "everyone",
      "gender_required_display": "Everyone",
      "min_age": 14,
      "timezone": "UTC",
      "location": {
        "id": "b23cd45e-0000-0000-0000-000000000002",
        "address": "Sector 3, Uttara",
        "latitude": "23.87590000",
        "longitude": "90.37950000",
        "city": "Dhaka",
        "country": "Bangladesh",
        "postal_code": "1230",
        "is_primary": true,
        "updated_at": "2026-11-09T18:00:00Z"
      },
      "distance_km": 14.4,
      "is_open_now": true,
      "today_opening_hours": "06:00 - 22:00",
      "amenities_preview": [
        "Lockers",
        "Water Station"
      ],
      "followers_count": 89,
      "is_following": false,
      "created_at": "2026-11-03T12:00:00Z"
    }
  ]
}
```

### 3.3. Response Fields Specification

| Field Path | Type | Nullable | Description |
|---|---|---|---|
| `count` | `integer` | No | Total number of matching gyms across all pages. |
| `total_pages` | `integer` | No | Total number of pagination pages. |
| `current_page` | `integer` | No | Active page number. |
| `next` | `string` | Yes | URL link for the next results page (`null` if on the last page). |
| `previous` | `string` | Yes | URL link for the previous results page (`null` if on the first page). |
| `results[]` | `array` | No | List of gym search item objects. |
| `results[].id` | `string (uuid)` | No | Gym unique identifier. |
| `results[].name` | `string` | No | Registered gym workspace name. |
| `results[].profile_picture_url` | `string (url)` | Yes | Absolute URL to gym profile image. |
| `results[].cover_photo_url` | `string (url)` | Yes | Absolute URL to gym cover banner photo. |
| `results[].short_description` | `string` | Yes | Gym bio description text. |
| `results[].primary_type` | `string` | No | Primary fitness category identifier. |
| `results[].primary_type_display` | `string` | No | Human-readable label for primary category. |
| `results[].secondary_type` | `string` | Yes | Secondary fitness category identifier. |
| `results[].secondary_type_display` | `string` | Yes | Human-readable label for secondary category. |
| `results[].gender_required` | `string` | No | Gender restriction (`everyone`, `women_only`, `men_only`). |
| `results[].gender_required_display` | `string` | No | Human-readable label for gender restriction. |
| `results[].min_age` | `integer` | No | Minimum allowed member age (1-99). |
| `results[].timezone` | `string` | No | Gym IANA timezone identifier (e.g. `UTC`, `Asia/Dhaka`). |
| `results[].location` | `object` | Yes | Primary gym location object. |
| `results[].location.id` | `string (uuid)` | No | Location record identifier. |
| `results[].location.address` | `string` | No | Physical street address. |
| `results[].location.latitude` | `string (decimal)` | No | Latitude coordinate string (8 decimal places). |
| `results[].location.longitude` | `string (decimal)` | No | Longitude coordinate string (8 decimal places). |
| `results[].location.city` | `string` | Yes | City name. |
| `results[].location.country` | `string` | Yes | Country name. |
| `results[].location.postal_code` | `string` | Yes | Postal / ZIP code. |
| `results[].location.is_primary` | `boolean` | No | Whether this is the main headquarters branch. |
| `results[].location.updated_at` | `string (datetime)` | No | ISO 8601 timestamp of last location update. |
| `results[].distance_km` | `number` | Yes | Distance from user GPS coordinates in kilometers. `null` if searched by city without coordinates. |
| `results[].is_open_now` | `boolean` | No | Real-time open/closed status based on gym timezone and current operating schedule. |
| `results[].today_opening_hours` | `string` | No | Today's operating schedule (e.g. `06:00 - 22:00` or `Closed`). |
| `results[].amenities_preview[]` | `array of strings` | No | List of up to 5 prominent amenity names available at the gym. |
| `results[].followers_count` | `integer` | No | Count of total active gym followers. |
| `results[].is_following` | `boolean` | No | `true` if authenticated user follows this gym; `false` otherwise. |
| `results[].created_at` | `string (datetime)` | No | ISO 8601 creation timestamp of gym. |

---

## 4. Endpoint 2: Get Public Gym Details

Retrieves complete public information for a selected gym.

- **Method:** `GET`
- **Path:** `/api/v1/gyms/{gym_id}/public/` (Alias: `/api/v1/gyms/{gym_id}/detail/`)
- **Headers:**
  - `Accept: application/json`
  - `Authorization: Bearer <access_token>` (Optional)

### 4.1. Path Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `gym_id` | `string (uuid)` | Yes | UUID of the target gym workspace. |

### 4.2. Response Payload (`200 OK`)

```json
{
  "id": "e93f9dc2-7c18-4b72-9112-78d10b7b1201",
  "name": "Titan Strength Club",
  "profile_picture_url": "https://api.manygym.com/media/gyms/profiles/titan.webp",
  "cover_photo_url": "https://api.manygym.com/media/gyms/covers/titan_cover.webp",
  "short_description": "A premier fitness institution dedicated to empowering members with elite equipment and guidance.",
  "primary_type": "strength_bodybuilding_gym",
  "primary_type_display": "Strength & Bodybuilding Gym",
  "secondary_type": null,
  "secondary_type_display": null,
  "gender_required": "everyone",
  "gender_required_display": "Everyone",
  "min_age": 16,
  "timezone": "UTC",
  "created_at": "2026-11-01T10:00:00Z",
  "owner_public": {
    "id": "31b2c45d-789a-4123-b123-456789abcdef",
    "name": "Alice Owner"
  },
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
  "locations": [
    {
      "id": "a12bc34d-0000-0000-0000-000000000001",
      "address": "House 12, Road 7, Dhanmondi",
      "latitude": "23.74650000",
      "longitude": "90.37600000",
      "city": "Dhaka",
      "country": "Bangladesh",
      "postal_code": "1205",
      "is_primary": true,
      "updated_at": "2026-11-09T18:00:00Z"
    }
  ],
  "today_status": {
    "is_open_now": true,
    "today_hours": "06:00 - 22:00"
  },
  "operating_hours": [
    {
      "id": "c1111111-0000-0000-0000-000000000001",
      "day_of_week": 0,
      "day_name": "Sunday",
      "start_time": "08:00:00",
      "end_time": "20:00:00",
      "is_closed": false
    },
    {
      "id": "c1111111-0000-0000-0000-000000000002",
      "day_of_week": 1,
      "day_name": "Monday",
      "start_time": "06:00:00",
      "end_time": "22:00:00",
      "is_closed": false
    },
    {
      "id": "c1111111-0000-0000-0000-000000000003",
      "day_of_week": 2,
      "day_name": "Tuesday",
      "start_time": "06:00:00",
      "end_time": "22:00:00",
      "is_closed": false
    },
    {
      "id": "c1111111-0000-0000-0000-000000000004",
      "day_of_week": 3,
      "day_name": "Wednesday",
      "start_time": "06:00:00",
      "end_time": "22:00:00",
      "is_closed": false
    },
    {
      "id": "c1111111-0000-0000-0000-000000000005",
      "day_of_week": 4,
      "day_name": "Thursday",
      "start_time": "06:00:00",
      "end_time": "22:00:00",
      "is_closed": false
    },
    {
      "id": "c1111111-0000-0000-0000-000000000006",
      "day_of_week": 5,
      "day_name": "Friday",
      "start_time": "06:00:00",
      "end_time": "22:00:00",
      "is_closed": false
    },
    {
      "id": "c1111111-0000-0000-0000-000000000007",
      "day_of_week": 6,
      "day_name": "Saturday",
      "start_time": "08:00:00",
      "end_time": "20:00:00",
      "is_closed": false
    }
  ],
  "amenities": {
    "free_amenities": [
      {
        "id": "ga-001",
        "amenity_id": "cat-001",
        "name": "Infrared Sauna",
        "group_name": "wellness_and_recovery",
        "group_display": "Wellness & Recovery",
        "is_paid": false,
        "default_price": "0.00"
      }
    ],
    "paid_amenities": [
      {
        "id": "ga-002",
        "amenity_id": "cat-002",
        "name": "Personal Lockers",
        "group_name": "changing_and_storage",
        "group_display": "Changing & Storage",
        "is_paid": true,
        "default_price": "15.00"
      }
    ],
    "total_count": 2
  },
  "gallery": [
    {
      "id": "d1234567-0000-0000-0000-000000000001",
      "media_url": "https://api.manygym.com/media/gyms/gallery/original/weights.jpg",
      "media_type": "picture",
      "category": "equipment",
      "category_display": "Equipment",
      "caption": "Olympic lifting racks and dumbbells",
      "order_index": 0,
      "original_url": "https://api.manygym.com/media/gyms/gallery/original/weights.jpg",
      "optimized_url": "https://api.manygym.com/media/gyms/gallery/optimized/weights.webp",
      "thumbnail_url": "https://api.manygym.com/media/gyms/gallery/thumbnails/weights.webp",
      "processing_status": "completed"
    }
  ],
  "membership_plans": [
    {
      "id": "p1234567-0000-0000-0000-000000000001",
      "name": "Monthly Gold Pass",
      "description": "Full access to gym equipment and sauna.",
      "plan_type": "time_based",
      "plan_type_display": "Time Based",
      "price": "49.99",
      "duration_value": 1,
      "duration_unit": "month",
      "duration_unit_display": "Month",
      "joining_fee": "0.00"
    }
  ],
  "social": {
    "followers_count": 142,
    "members_count": 65,
    "is_following": false
  }
}
```

### 4.3. Response Fields Specification

| Field Path | Type | Nullable | Description |
|---|---|---|---|
| `id` | `string (uuid)` | No | Gym identifier. |
| `name` | `string` | No | Gym name. |
| `profile_picture_url` | `string (url)` | Yes | Absolute URL to profile image. |
| `cover_photo_url` | `string (url)` | Yes | Absolute URL to cover banner photo. |
| `short_description` | `string` | Yes | Bio / description text. |
| `primary_type` | `string` | No | Primary category code. |
| `primary_type_display` | `string` | No | Human-readable primary category label. |
| `secondary_type` | `string` | Yes | Secondary category code. |
| `secondary_type_display` | `string` | Yes | Human-readable secondary category label. |
| `gender_required` | `string` | No | Gender restriction code. |
| `gender_required_display` | `string` | No | Human-readable gender restriction label. |
| `min_age` | `integer` | No | Minimum allowed member age. |
| `timezone` | `string` | No | Gym IANA timezone identifier. |
| `created_at` | `string (datetime)` | No | ISO 8601 gym creation timestamp. |
| `owner_public` | `object` | No | Public owner information. |
| `owner_public.id` | `string (uuid)` | No | Owner user identifier. |
| `owner_public.name` | `string` | No | Owner public full name. |
| `location` | `object` | Yes | Primary gym location object. |
| `locations[]` | `array` | No | Array of all gym branches and physical addresses. |
| `today_status` | `object` | No | Today's open status summary. |
| `today_status.is_open_now` | `boolean` | No | `true` if gym is currently open at this exact moment; `false` otherwise. |
| `today_status.today_hours` | `string` | No | Human-readable today hours string. |
| `operating_hours[]` | `array` | No | 7-day operating schedule array (sorted 0=Sunday to 6=Saturday). |
| `operating_hours[].id` | `string (uuid)` | No | Schedule record identifier. |
| `operating_hours[].day_of_week` | `integer` | No | Integer day of week (`0`=Sunday through `6`=Saturday). |
| `operating_hours[].day_name` | `string` | No | Full day name (`Sunday`, `Monday`, etc.). |
| `operating_hours[].start_time` | `string (time)` | Yes | Opening time (`HH:MM:SS`). `null` if closed. |
| `operating_hours[].end_time` | `string (time)` | Yes | Closing time (`HH:MM:SS`). `null` if closed. |
| `operating_hours[].is_closed` | `boolean` | No | `true` if gym is closed on this day. |
| `amenities` | `object` | No | Categorized amenities container. |
| `amenities.free_amenities[]` | `array` | No | List of complimentary / free amenities. |
| `amenities.paid_amenities[]` | `array` | No | List of extra paid amenities with pricing. |
| `amenities.free_amenities[].id` | `string` | No | Gym amenity mapping record identifier. |
| `amenities.free_amenities[].amenity_id` | `string` | No | Master catalog amenity identifier. |
| `amenities.free_amenities[].name` | `string` | No | Amenity title (e.g. `Infrared Sauna`). |
| `amenities.free_amenities[].group_name` | `string` | No | Domain group key (e.g. `wellness_and_recovery`). |
| `amenities.free_amenities[].group_display` | `string` | No | Human-readable group label (e.g. `Wellness & Recovery`). |
| `amenities.free_amenities[].is_paid` | `boolean` | No | `false` for free amenities. |
| `amenities.free_amenities[].default_price` | `string` | No | Price string (`0.00`). |
| `amenities.paid_amenities[].default_price` | `string` | No | Additional fee string (e.g. `15.00`). |
| `amenities.total_count` | `integer` | No | Total count of configured amenities (`free` + `paid`). |
| `gallery[]` | `array` | No | Media gallery assets list. |
| `gallery[].id` | `string (uuid)` | No | Media item identifier. |
| `gallery[].media_url` | `string (url)` | No | Direct media asset URL. |
| `gallery[].media_type` | `string` | No | Asset media type (`picture`, `video`). |
| `gallery[].category` | `string` | No | Gallery asset category key. |
| `gallery[].category_display` | `string` | No | Human-readable gallery category label. |
| `gallery[].caption` | `string` | Yes | Photo/video caption text. |
| `gallery[].order_index` | `integer` | No | Integer sequence index for UI ordering. |
| `gallery[].original_url` | `string (url)` | Yes | URL of untouched original uploaded file. |
| `gallery[].optimized_url` | `string (url)` | Yes | WebP high-resolution variant URL. |
| `gallery[].thumbnail_url` | `string (url)` | Yes | WebP thumbnail variant URL. |
| `gallery[].processing_status` | `string` | No | Pipeline status (`pending`, `processing`, `completed`, `failed`). |
| `membership_plans[]` | `array` | No | Active public membership pricing plans. |
| `membership_plans[].id` | `string (uuid)` | No | Plan record identifier. |
| `membership_plans[].name` | `string` | No | Plan display title. |
| `membership_plans[].description` | `string` | Yes | Plan description. |
| `membership_plans[].plan_type` | `string` | No | Plan billing structure (`time_based`, `session_based`). |
| `membership_plans[].plan_type_display` | `string` | No | Human-readable plan type label. |
| `membership_plans[].price` | `string` | No | Fee amount string (e.g. `49.99`). |
| `membership_plans[].duration_value` | `integer` | No | Duration integer (e.g. `1`, `3`, `12`). |
| `membership_plans[].duration_unit` | `string` | No | Duration unit code (`day`, `week`, `month`, `session`). |
| `membership_plans[].duration_unit_display` | `string` | No | Human-readable duration unit label. |
| `membership_plans[].joining_fee` | `string` | No | One-time joining fee string (e.g. `0.00`). |
| `social` | `object` | No | Social statistics block. |
| `social.followers_count` | `integer` | No | Total active gym followers. |
| `social.members_count` | `integer` | No | Total enrolled gym members. |
| `social.is_following` | `boolean` | No | `true` if authenticated user follows this gym. |

---

## 5. Endpoint 3: Update Gym Location Coordinates

Saves map pinpoint coordinates and address details for a gym. Automatically updates both PostgreSQL and the Redis Geospatial proximity index.

- **Method:** `PATCH`
- **Path:** `/api/v1/gyms/profile/location/`
- **Headers:**
  - `Content-Type: application/json`
  - `Authorization: Bearer <access_token>` (Required: Gym Owner or staff with `gym_profile:edit` scope)
- **Query Parameters:**
  - `gym_id`: `string (uuid)` (Optional if using active gym context token)

### 5.1. Request Payload

```json
{
  "address": "Sector 3, Road 7, Uttara",
  "latitude": 23.87590000,
  "longitude": 90.37950000,
  "city": "Dhaka",
  "country": "Bangladesh",
  "postal_code": "1230"
}
```

### 5.2. Request Payload Fields Specification

| Field | Type | Required | Validation Rules | Description |
|---|---|---|---|---|
| `address` | `string` | Yes | Cannot be empty or blank. | Physical street address of the gym. |
| `latitude` | `number / decimal` | Yes | Min: `-90.0`, Max: `90.0`. Up to 8 decimal places. | Pinned map latitude coordinate. |
| `longitude` | `number / decimal` | Yes | Min: `-180.0`, Max: `180.0`. Up to 8 decimal places. | Pinned map longitude coordinate. |
| `city` | `string` | No | Max length: 100 characters. | City name. |
| `country` | `string` | No | Max length: 100 characters. | Country name. |
| `postal_code` | `string` | No | Max length: 30 characters. | Postal / ZIP code. |

### 5.3. Response Payload (`200 OK`)

```json
{
  "id": "b23cd45e-0000-0000-0000-000000000002",
  "address": "Sector 3, Road 7, Uttara",
  "latitude": "23.87590000",
  "longitude": "90.37950000",
  "city": "Dhaka",
  "country": "Bangladesh",
  "postal_code": "1230",
  "is_primary": true,
  "updated_at": "2026-11-09T18:30:00Z"
}
```

---

## 6. Endpoint 4: Get Gym Location

Retrieves the saved physical address and map coordinates of the active gym.

- **Method:** `GET`
- **Path:** `/api/v1/gyms/profile/location/`
- **Headers:**
  - `Accept: application/json`
  - `Authorization: Bearer <access_token>` (Required: Gym Owner or staff with `gym_profile:read` scope)
- **Query Parameters:**
  - `gym_id`: `string (uuid)` (Optional if using active gym context token)

### 6.1. Response Payload (`200 OK`)

```json
{
  "id": "a12bc34d-0000-0000-0000-000000000001",
  "address": "House 12, Road 7, Dhanmondi",
  "latitude": "23.74650000",
  "longitude": "90.37600000",
  "city": "Dhaka",
  "country": "Bangladesh",
  "postal_code": "1205",
  "is_primary": true,
  "updated_at": "2026-11-09T18:00:00Z"
}
```

---

## 7. Global Error Responses

### 7.1. Missing Coordinates Pair (`400 Bad Request`)
Returned when `latitude` is provided without `longitude`, or vice versa:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Validation failed.",
  "details": {
    "coordinates": [
      "Both 'latitude' and 'longitude' must be provided together for live location radius search."
    ]
  }
}
```

### 7.2. Out-of-Range Coordinates (`400 Bad Request`)
Returned when `latitude` is not between `-90.0` and `90.0`, or `longitude` is not between `-180.0` and `180.0`:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Validation failed.",
  "details": {
    "latitude": [
      "Ensure this value is less than or equal to 90.0."
    ]
  }
}
```

### 7.3. Resource Not Found (`404 Not Found`)
Returned when querying an invalid gym UUID or a gym that is deactivated, soft-deleted, or unpublished:

```json
{
  "code": "RESOURCE_NOT_FOUND",
  "message": "Gym not found or currently unavailable.",
  "details": null
}
```

### 7.4. Permission Denied (`403 Forbidden`)
Returned when an unauthorized user attempts to update gym location:

```json
{
  "code": "PERMISSION_DENIED",
  "message": "You do not possess the required 'gym_profile:edit' scope for this gym operation.",
  "details": null
}
```
