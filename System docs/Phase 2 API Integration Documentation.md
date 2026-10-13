# Phase 2: Gym Profile, Multi-Location, Operating Hours, Gallery & Amenities System

## Overview & Architecture
This module implements complete end-to-end management for Gym Profiles, Multi-Location tracking, Operating Hours with validation, categorized media galleries with display ordering, and the Master Amenities Catalog with complimentary vs paid configuration.

Adheres strictly to the **Layered Architectural Pattern**:
- **Models**: `Gym`, `GymLocation`, `GymOpeningHours`, `GymGallery`, `AmenityCatalog`, `GymAmenity`
- **Selectors**: Pure, cache-friendly read operations (`apps/gyms/selectors.py`, `apps/amenities/selectors.py`)
- **Services**: Atomic business logic with strict invariants (`apps/gyms/services.py`, `apps/amenities/services.py`)
- **Serializers**: Typed schema validation and documentation (`apps/gyms/rest_api/v1/serializers.py`, `apps/amenities/rest_api/v1/serializers.py`)
- **Views**: Declarative DRF APIViews with OpenAPI 3.0 / Swagger schema decorators (`apps/gyms/rest_api/v1/views.py`, `apps/amenities/rest_api/v1/views.py`)

---

## Business Invariants & Rules Enforced
1. **Description Length Requirement**:
   - `short_description` must be **at least 120 characters** long when provided or updated.
2. **Opening Hours Validation**:
   - 7 days of the week (`0` = Sunday through `6` = Saturday).
   - When open (`is_closed=False`), both `start_time` and `end_time` are mandatory and `start_time < end_time`.
   - When closed (`is_closed=True`), both `start_time` and `end_time` are automatically nullified.
3. **Mutual Exclusion on Amenities**:
   - An amenity **CANNOT be simultaneously complimentary (free) and paid**.
   - If an amenity catalog ID appears in both `free_amenity_ids` and `paid_amenities`, the synchronization operation immediately aborts with `400 Bad Request` (`DomainValidationError`).
4. **Context & Ownership Authorization**:
   - Gym profile mutations require the requester to either be the Gym Owner or possess appropriate scoped permissions (`gym_profile:edit`, `gym:profile:write`).

---

## Complete API Endpoints List

### 1. Gym Profile & Overview
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `POST` | `/api/v1/gyms/` | Initialize a new Gym entity with default location and 7-day schedule | Bearer JWT |
| `GET` | `/api/v1/gyms/profile/overview/` | Retrieve gym overview details (or `/profile/`) | Bearer JWT |
| `PATCH` | `/api/v1/gyms/profile/overview/` | Update gym overview (enforces min 120 chars description) | Bearer JWT (Owner/Staff) |

### 2. Location
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/api/v1/gyms/profile/location/` | Retrieve gym primary location coordinates and address | Bearer JWT |
| `PATCH` | `/api/v1/gyms/profile/location/` | Update address, city, country, postal code, lat/lng | Bearer JWT (Owner/Staff) |

### 3. Operating Hours
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/api/v1/gyms/opening-hours/` | Retrieve 7-day schedule with human-readable day names | Bearer JWT |
| `PUT` | `/api/v1/gyms/opening-hours/` | Atomic bulk update of operating hours schedule | Bearer JWT (Owner/Staff) |

### 4. Gallery & Media Management
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/api/v1/gyms/gallery/` | List gallery assets (supports filter: `?category=equipment`) | Bearer JWT |
| `POST` | `/api/v1/gyms/gallery/` | Add photo/video with category and caption | Bearer JWT (Owner/Staff) |
| `PATCH` | `/api/v1/gyms/gallery/reorder/` | Reorder gallery display sequence | Bearer JWT (Owner/Staff) |
| `DELETE` | `/api/v1/gyms/gallery/<uuid:item_id>/` | Delete a gallery media asset | Bearer JWT (Owner/Staff) |

### 5. Amenities Management
| Method | Endpoint | Description | Auth Required |
|---|---|---|---|
| `GET` | `/api/v1/amenities/catalog/` | Get master amenities catalog grouped across 7 domains | Bearer JWT |
| `GET` | `/api/v1/amenities/gym-amenities/` | Get gym's configured free & paid amenities | Bearer JWT |
| `PUT` | `/api/v1/amenities/gym-amenities/sync/` | Sync free vs paid amenities (enforces mutual exclusion) | Bearer JWT (Owner/Staff) |

---

## 7 Standard Domain Categories for Amenities
1. **Changing & Storage** (Changing rooms, Showers, Day-use lockers, Personal lockers, Towel service)
2. **Wellness & Recovery** (Sauna, Steam room, Swimming pool, Hot tub, Massage room)
3. **Comfort & Convenience** (Air conditioning, Wi-Fi, Drinking water station, Seating area)
4. **Food & Drink** (Cafe, Smoothie/protein bar, Vending machines)
5. **Parking & Transport** (Parking, Bicycle parking)
6. **Accessibility** (Step-free entrance, Lift access, Accessible toilet, Accessible changing room)
7. **Family Facilities** (Childcare, Children’s waiting area)
