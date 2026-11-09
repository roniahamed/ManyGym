# Nearby Gym Search API & Frontend Integration Documentation

## 1. Overview & Architecture

The **Nearby Gym Search** system provides high-performance, real-time discovery of gyms for prospective members, travelers, and fitness enthusiasts.

It supports dual search modes:
1. **Live Location Radius Search**: Browser / Device live GPS sharing with user consent, querying gyms within a **20 km radius** (customizable via `radius` parameter) and ordering by proximity.
2. **City & Category Search**: Manual city selection (e.g. Dhaka, New York, London) and fitness domain category filtering (e.g. Strength & Bodybuilding, Yoga & Pilates Studio).

```
   ┌────────────────────────────────────────────────────────────────────────┐
   │                       Client (Web / Mobile App)                        │
   │  - Browser Live Geolocation API (navigator.geolocation + Consent)     │
   │  - Fallback City Dropdown & Gym Category Selector                      │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       │
                                       ▼
                     GET /api/v1/gyms/nearby/?lat=...&lon=...
                                       │
                  ┌────────────────────┴────────────────────┐
                  │                                         │
                  ▼                                         ▼
        [1. Fast Path: Redis GEO]              [2. Fallback Path: PostgreSQL / PostGIS]
       - Redis GEOSEARCH (<1ms)                 - PostGIS ST_DistanceSphere (if installed)
       - Key: `gyms:geo:locations`              - Standard Haversine spherical formula
       - Returns IDs & Distances (km)           - Auto-warms Redis GEO on cache miss
                  │                                         │
                  └────────────────────┬────────────────────┘
                                       │
                                       ▼
                       Hydrate with Prefetched Data:
             - Operating Hours (Live is_open_now & today hours)
             - Primary Location Details & Pin Coordinates
             - Categorized Amenities Preview (Complimentary & Paid)
             - Follower Count & Following Status (if authenticated)
```

---

## 2. API Endpoints Reference

### 2.1. Search Nearby Gyms
- **Endpoint:** `GET /api/v1/gyms/nearby/` (Alias: `GET /api/v1/gyms/search/`)
- **Authentication:** Optional (`AllowAny`). If a valid Bearer JWT is supplied, `is_following` will reflect the user's relationship with each gym.
- **Query Parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `latitude` | `float` | Optional* | None | User's live latitude (-90.0 to 90.0). *Must be provided with `longitude`. |
| `longitude` | `float` | Optional* | None | User's live longitude (-180.0 to 180.0). *Must be provided with `latitude`. |
| `radius` | `float` | Optional | `20.0` | Search radius in kilometers (min: 0.1, max: 500.0). |
| `category` | `string` | Optional | None | Choice from `GymTypeEnum` (e.g. `strength_bodybuilding_gym`, `functional_fitness_gym`, `yoga_pilates_studio`). Matches primary or secondary type. |
| `city` | `string` | Optional | None | Case-insensitive city search (e.g. `Dhaka`, `Chittagong`). |
| `search` / `q` | `string` | Optional | None | Free-text keyword search matching gym name, bio, address, or city. |
| `page` | `integer` | Optional | `1` | Pagination page number. |
| `page_size` | `integer` | Optional | `20` | Results per page (max: 100). |

#### Request Examples:
- **Live Location 20 km search:**
  ```http
  GET /api/v1/gyms/nearby/?latitude=23.7465&longitude=90.3760&radius=20 HTTP/1.1
  Host: api.manygym.com
  Accept: application/json
  ```
- **Category + 20 km radius search:**
  ```http
  GET /api/v1/gyms/nearby/?latitude=23.7465&longitude=90.3760&category=strength_bodybuilding_gym HTTP/1.1
  ```
- **City search without GPS:**
  ```http
  GET /api/v1/gyms/nearby/?city=Dhaka&category=functional_fitness_gym HTTP/1.1
  ```

#### Response `200 OK`:
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
      "short_description": "A premier fitness institution dedicated to empowering members with elite bodybuilding equipment, powerlifting platforms, and certified personal trainers.",
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
        "Changing Rooms & Showers",
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
      "short_description": "Elite functional fitness studio offering daily HIIT classes, endurance conditioning, and community workout challenges for all levels.",
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
        "Drinking Water Station"
      ],
      "followers_count": 89,
      "is_following": false,
      "created_at": "2026-11-03T12:00:00Z"
    }
  ]
}
```

---

### 2.2. Get Public Gym Details
- **Endpoint:** `GET /api/v1/gyms/<uuid:gym_id>/public/` (Alias: `GET /api/v1/gyms/<uuid:gym_id>/detail/`)
- **Authentication:** Optional (`AllowAny`).
- **Response `200 OK`:** Complete profile payload including:
  - Full branding info & overview
  - Primary location and multi-branch addresses with GPS coordinates
  - 7-day schedule with live `is_open_now` indicator for current local time
  - Amenities divided into complimentary vs paid with prices
  - Media gallery items (with original, WebP optimized, and thumbnail variants)
  - Active membership pricing plans
  - Follower & member statistics

#### Response Example:
```json
{
  "id": "e93f9dc2-7c18-4b72-9112-78d10b7b1201",
  "name": "Titan Strength Club",
  "profile_picture_url": "https://api.manygym.com/media/gyms/profiles/titan.webp",
  "cover_photo_url": "https://api.manygym.com/media/gyms/covers/titan_cover.webp",
  "short_description": "A premier fitness institution dedicated to empowering members...",
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
    }
  ],
  "amenities": {
    "free_amenities": [
      {
        "id": "ga-01",
        "amenity_id": "cat-01",
        "name": "Infrared Sauna",
        "group_name": "wellness_and_recovery",
        "group_display": "Wellness & Recovery",
        "is_paid": false,
        "default_price": "0.00"
      }
    ],
    "paid_amenities": [],
    "total_count": 1
  },
  "gallery": [
    {
      "id": "gal-01",
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
      "id": "plan-01",
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

---

## 3. Frontend Integration Guide (Browser Live Location + Consent)

### 3.1. Standard Workflow
1. When user lands on the **"Search Nearby Gym"** page, display a location prompt asking for permission to access their live location to find gyms within **20 km**.
2. Call the HTML5 Geolocation API: `navigator.geolocation.getCurrentPosition(successCallback, errorCallback, options)`.
3. If permission is granted:
   - Extract `latitude = position.coords.latitude` and `longitude = position.coords.longitude`.
   - Call `/api/v1/gyms/nearby/?latitude=${latitude}&longitude=${longitude}&radius=20`.
4. If permission is denied or device does not support geolocation:
   - Gracefully display the **City Selector Dropdown / Input** (e.g. "Dhaka", "Chittagong", "Sylhet").
   - Call `/api/v1/gyms/nearby/?city=${selectedCity}`.

### 3.2. Complete React Hook Implementation

```typescript
import { useState, useEffect, useCallback } from "react";

interface GymLocation {
  address: string;
  city: string;
  country: string;
  latitude: number;
  longitude: number;
}

interface GymSearchItem {
  id: string;
  name: string;
  profile_picture_url: string | null;
  short_description: string | null;
  primary_type: string;
  primary_type_display: string;
  location: GymLocation | null;
  distance_km: number | null;
  is_open_now: boolean;
  today_opening_hours: string;
  amenities_preview: string[];
  followers_count: number;
  is_following: boolean;
}

export function useNearbyGyms() {
  const [gyms, setGyms] = useState<GymSearchItem[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(null);
  const [locationPermission, setLocationPermission] = useState<"prompt" | "granted" | "denied">("prompt");

  // Request browser live location with consent
  const requestLiveLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setLocationPermission("denied");
      setError("Geolocation is not supported by your browser.");
      return;
    }

    setLoading(true);
    setError(null);

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const userLat = position.coords.latitude;
        const userLon = position.coords.longitude;
        setCoords({ latitude: userLat, longitude: userLon });
        setLocationPermission("granted");
        fetchGyms({ latitude: userLat, longitude: userLon, radius: 20 });
      },
      (err) => {
        setLoading(false);
        setLocationPermission("denied");
        if (err.code === err.PERMISSION_DENIED) {
          setError("Location access was denied. Please select your city to discover gyms.");
        } else {
          setError("Unable to retrieve your location. Please select your city.");
        }
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 60000, // Cache GPS for 60 seconds
      }
    );
  }, []);

  // Fetch gyms from Many Gym API
  const fetchGyms = async (params: {
    latitude?: number;
    longitude?: number;
    radius?: number;
    city?: string;
    category?: string;
    search?: string;
  }) => {
    setLoading(true);
    setError(null);

    const query = new URLSearchParams();
    if (params.latitude !== undefined && params.longitude !== undefined) {
      query.append("latitude", params.latitude.toString());
      query.append("longitude", params.longitude.toString());
      query.append("radius", (params.radius || 20).toString());
    }
    if (params.city) query.append("city", params.city);
    if (params.category) query.append("category", params.category);
    if (params.search) query.append("search", params.search);

    try {
      const response = await fetch(`/api/v1/gyms/nearby/?${query.toString()}`, {
        headers: {
          Accept: "application/json",
        },
      });

      if (!response.ok) {
        throw new Error("Failed to search gyms.");
      }

      const data = await response.json();
      setGyms(data.results || []);
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred.");
    } finally {
      setLoading(false);
    }
  };

  return {
    gyms,
    loading,
    error,
    coords,
    locationPermission,
    requestLiveLocation,
    fetchGyms,
  };
}
```

---

## 4. Backend Geospatial Synchronization Details

### 4.1. Location Recording (`create_gym` & `update_gym_location`)
When a gym owner or staff creates or updates physical location (`latitude` and `longitude`):
1. **Validation**: Latitude must be between `-90.0` and `+90.0`, longitude between `-180.0` and `+180.0`.
2. **PostgreSQL Persistence**: Saved in `gym_locations` table with `is_primary=True`.
3. **Redis Geospatial Indexing (`GEOADD`)**:
   ```python
   # Key: gyms:geo:locations
   # Coordinates: (longitude, latitude, member_id)
   redis_client.geoadd("gyms:geo:locations", (lon, lat, str(gym.id)))
   ```

### 4.2. Access Control & Deactivation Synchronization
When a gym workspace state transitions:
- **`unpublish` / `deactivate` / `delete`**: The gym member ID is immediately removed from Redis GEO via `ZREM gyms:geo:locations <gym_id>`.
- **`publish` / `reactivate` / `restore`**: The primary location coordinates are re-indexed via `GEOADD`.

### 4.3. Management Command for Operators
To warm up or re-index all published gyms into Redis GEO:
```bash
python manage.py warm_gym_geo_cache
```
Example output:
```text
Warming Redis GEO cache with active gym locations...
Successfully cached 124 gym locations in Redis GEO index.
```

