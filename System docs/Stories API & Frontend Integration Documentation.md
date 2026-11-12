# Stories API & Frontend Integration Documentation

## 1. General Configuration

- **Base URL:** `/api/v1/stories/`
- **Authentication:** Bearer JWT Token (`Authorization: Bearer <access_token>`)
- **Accepted Request Formats:** `multipart/form-data`, `application/x-www-form-urlencoded`, `application/json`
- **Response Format:** `application/json`
- **Standard Headers:**
  - `Authorization: Bearer <access_token>` (Required for create, update, delete, `my`, `view`, `viewers`; optional for `list`, `tray`, `detail`)
  - `Accept: application/json`
  - `Content-Type: application/json` (or `multipart/form-data` for file upload)
  - `X-Gym-Context: <gym_uuid>` (Optional fallback header when the JWT token does not carry `gym_id`)

### Automatic Token Context & Read-Only Fields

| Field | Source | Behavior |
| :--- | :--- | :--- |
| `owner_type` | Bearer JWT (`context_type`) or `X-Gym-Context` | Read-only. Automatically set to `"user"` (personal context) or `"gym"` (gym context). Cannot be overridden in request payload. |
| `user_id` | Bearer JWT (`user_id`) | Read-only. Always taken from the authenticated user (author for user stories, uploader/staff for gym stories). |
| `gym_id` | Bearer JWT (`gym_id`) or `X-Gym-Context` | Read-only. Populated when `owner_type` is `"gym"`; `null` when `owner_type` is `"user"`. |
| `media_type` | Uploaded file / `media_url` / `source_post_id` | Read-only. Auto-detected as `"picture"` or `"video"` from file extension, MIME type, URL path extension, or source post attachment. |

---

## 2. Global Error Envelope & Status Codes

All `4xx` and `5xx` error responses use the following JSON structure:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Validation failed for domain requirements.",
  "details": {
    "field_name": [
      "Field error message."
    ]
  }
}
```

### Status Codes

| Status Code | Error Code | Meaning |
| :--- | :--- | :--- |
| `400 Bad Request` | `VALIDATION_ERROR` | Invalid field type, unsupported format/extension, multi-file upload (>1 file), invalid lifetime, invalid privacy for `owner_type`, or missing media. |
| `401 Unauthorized` | `UNAUTHORIZED` / `UNAUTHORIZED_CONTEXT` | Missing, expired, or invalid Bearer token. |
| `403 Forbidden` | `PERMISSION_DENIED` | Insufficient gym RBAC permission (`stories:manage` / `posts:manage`), non-owner edit/delete/viewers access, blocked user, age restriction, or restricted privacy audience. |
| `404 Not Found` | `RESOURCE_NOT_FOUND` | Story or `source_post_id` does not exist, is deleted/unpublished, or is expired/archived for non-owners. |
| `405 Method Not Allowed` | `METHOD_NOT_ALLOWED` | HTTP method not supported on endpoint. |
| `409 Conflict` | `RESOURCE_CONFLICT` | Resource state conflict. |

---

## 3. Enums & Validation Reference

### `owner_type`

| Value | Description |
| :--- | :--- |
| `"user"` | Personal / Public User story |
| `"gym"` | Gym story |

### `media_type` (Read-Only, Auto-Detected)

| Value | Supported Extensions | Size Limit (Multipart File) |
| :--- | :--- | :--- |
| `"picture"` | `.jpg`, `.jpeg`, `.png`, `.webp` | Max `10 MB` (`10485760` bytes) |
| `"video"` | `.mp4`, `.mov` | Max `200 MB` (`209715200` bytes) |

### `processing_status` (Read-Only)

| Value | Meaning |
| :--- | :--- |
| `"pending"` | Queued for background media optimization |
| `"processing"` | Media optimization currently running |
| `"completed"` | Optimization finished (or direct `media_url` / `source_post_id` media ready) |
| `"failed"` | Background optimization failed (`original_url` remains usable) |

### `lifetime_hours` / `lifetime`

| Value | `lifetime_label` | Notes |
| :--- | :--- | :--- |
| `6` | `"6 hours"` | Accepts `6`, `"6"`, `"6h"`, `"6 hours"`, `"6_hours"` |
| `12` | `"12 hours"` | Accepts `12`, `"12"`, `"12h"`, `"12 hours"`, `"12_hours"` |
| `18` | `"18 hours"` | **Default** when omitted or null |
| `24` | `"24 hours"` | Accepts `24`, `"24"`, `"24h"`, `"24 hours"`, `"24_hours"` |
| `48` | `"48 hours"` | Accepts `48`, `"48"`, `"48h"`, `"48 hours"`, `"48_hours"` |

### `privacy`

| Value | Public User (`owner_type: "user"`) | Gym (`owner_type: "gym"`) | Visibility Rule |
| :--- | :--- | :--- | :--- |
| `"public"` | Allowed (**Default**) | Allowed (**Default**) | Visible to everyone (respecting private account / gym status / blocks / age restriction) |
| `"followers"` | Allowed | Allowed | Visible to followers of the user or gym |
| `"members_only"` | Rejected (`400`) | Allowed (alias: `"gym_members_only"`) | Visible only to gym members and authorized gym staff/owner |
| `"private"` | Allowed | Allowed | Visible only to the story owner (or authorized gym staff/owner) |

### `feed_type` (List & Tray Query Parameter)

| Value | Accepted Aliases | Behavior |
| :--- | :--- | :--- |
| `"all"` | — (**Default**) | All visible stories |
| `"followed"` | `"following"` | Only stories from followed public users and followed gyms |
| `"connected"` | `"connected_gym"`, `"my_gym"` | Only stories from gyms where the user is a member, staff, or owner |
| `"public"` | `"explore"` | Only stories with `privacy: "public"` |

---

## 4. Schema Models (All Fields)

### 4.1. Story Object

| Field | Type | Nullable | Read-Only | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | `string (uuid)` | No | Yes | Unique story ID. |
| `owner_type` | `string (enum)` | No | Yes | Uploader type: `"user"` or `"gym"`. |
| `user_id` | `string (uuid)` | No | Yes | Uploader user UUID. |
| `user_name` | `string` | No | Yes | Uploader full name (falls back to email). |
| `user_avatar_url` | `string (uri)` | Yes | Yes | Absolute URL of uploader avatar. |
| `gym_id` | `string (uuid)` | Yes | Yes | Gym UUID when `owner_type="gym"`; `null` for public user stories. |
| `gym_name` | `string` | Yes | Yes | Gym name when `owner_type="gym"`; `null` otherwise. |
| `gym_avatar_url` | `string (uri)` | Yes | Yes | Absolute URL of gym profile picture when `owner_type="gym"`; `null` otherwise. |
| `source_post_id` | `string (uuid)` | Yes | Yes | Shared community post UUID, if shared from a post. |
| `source_post` | `object` | Yes | Yes | Summary object of the shared `GymPost` (see 4.2), or `null`. |
| `media_url` | `string (uri)` | No | Yes | Best resolved absolute URL for playback/display (`optimized_url` > `media_url` > `original_url`). |
| `original_url` | `string (uri)` | Yes | Yes | Original uploaded/provided media URL. |
| `optimized_url` | `string (uri)` | Yes | Yes | Optimized WebP image or compressed MP4 URL once processed. |
| `thumbnail_url` | `string (uri)` | Yes | Yes | Thumbnail / video poster URL (falls back to optimized or original). |
| `media_type` | `string (enum)` | No | Yes | Auto-detected media type: `"picture"` or `"video"`. |
| `processing_status` | `string (enum)` | No | Yes | `"pending"`, `"processing"`, `"completed"`, or `"failed"`. |
| `file_size_bytes` | `integer` | No | Yes | Media file size in bytes (default `0`). |
| `width` | `integer` | Yes | Yes | Media width in pixels (populated after image optimization or inherited from `source_post`). |
| `height` | `integer` | Yes | Yes | Media height in pixels (populated after image optimization or inherited from `source_post`). |
| `duration_seconds` | `number (float)` | Yes | Yes | Optional video playback duration in seconds (`>= 0`). |
| `caption` | `string` | Yes | No (via `POST`/`PATCH`) | Story overlay caption (max `500` characters). |
| `background_color` | `string` | Yes | No (via `POST`/`PATCH`) | Hex color code (e.g. `#111827`, `#fff`, `#111827CC`). |
| `lifetime_hours` | `integer (enum)` | No | No (via `POST`/`PATCH`) | Story duration in hours: `6`, `12`, `18`, `24`, or `48`. |
| `lifetime_label` | `string` | No | Yes | Human-readable label (`"6 hours"`, `"12 hours"`, `"18 hours"`, `"24 hours"`, `"48 hours"`). |
| `privacy` | `string (enum)` | No | No (via `POST`/`PATCH`) | `"public"`, `"followers"`, `"members_only"` (gym only), or `"private"`. |
| `published_at` | `string (datetime)` | No | Yes | ISO 8601 UTC publish timestamp. |
| `expires_at` | `string (datetime)` | No | Yes | ISO 8601 UTC expiration timestamp (`published_at + lifetime_hours`). |
| `is_expired` | `boolean` | No | Yes | `true` if current server time `>= expires_at`. |
| `is_archived` | `boolean` | No | No (via `PATCH`) | Whether the story is manually archived (`false` by default). |
| `views_count` | `integer` | No | Yes | Total unique non-owner/non-manager views. |
| `has_viewed` | `boolean` | No | Yes | `true` if the requesting authenticated user has viewed this story; `false` otherwise. |
| `created_at` | `string (datetime)` | No | Yes | ISO 8601 record creation timestamp. |
| `updated_at` | `string (datetime)` | No | Yes | ISO 8601 last update timestamp. |

### 4.2. Source Post Summary Object (`source_post`)

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string (uuid)` | No | Original `GymPost` UUID. |
| `gym_id` | `string (uuid)` | No | Author gym UUID of the source post. |
| `gym_name` | `string` | No | Author gym name of the source post. |
| `content_text` | `string` | No | Text body of the source post. |
| `privacy` | `string` | No | Original post privacy setting. |
| `published_at` | `string (datetime)` | No | Original post publish timestamp. |

### 4.3. Story Tray Bucket Object

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `owner_type` | `string (enum)` | No | `"user"` or `"gym"`. |
| `owner_id` | `string (uuid)` | No | `user_id` for `"user"`, or `gym_id` for `"gym"`. |
| `owner_name` | `string` | No | Display name of user or gym. |
| `owner_avatar_url` | `string (uri)` | Yes | Absolute avatar/logo URL of owner. |
| `latest_story_at` | `string (datetime)` | No | Timestamp of the newest active story in this bucket. |
| `has_unviewed` | `boolean` | No | `true` if at least one story in `stories` has `has_viewed: false`. |
| `stories_count` | `integer` | No | Number of active stories in this bucket. |
| `stories` | `array<Story>` | No | Active stories for this owner ordered oldest-to-newest by `published_at`. |

### 4.4. Story Viewer Object

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string (uuid)` | No | `StoryView` record UUID. |
| `viewer_user_id` | `string (uuid)` | No | Viewer user UUID. |
| `viewer_name` | `string` | No | Viewer full name (falls back to email). |
| `viewer_avatar_url` | `string (uri)` | Yes | Absolute URL of viewer avatar. |
| `viewed_at` | `string (datetime)` | No | ISO 8601 timestamp when viewer first viewed the story. |

### 4.5. Standard Paginated Envelope

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `count` | `integer` | No | Total matching records. |
| `total_pages` | `integer` | No | Total number of pages. |
| `current_page` | `integer` | No | Active 1-based page number. |
| `next` | `string (uri)` | Yes | URL for the next page, or `null`. |
| `previous` | `string (uri)` | Yes | URL for the previous page, or `null`. |
| `results` | `array` | No | Array of items for the current page. |

---

## 5. API Endpoints

### 5.1. Upload Story

- **Method:** `POST`
- **Endpoint:** `/api/v1/stories/`
- **Authentication:** Required
- **Permissions:**
  - Personal token context (`owner_type="user"`): Any authenticated user.
  - Gym token context (`owner_type="gym"`): Active gym owner, superuser, or active staff with `stories:manage` or `posts:manage` scope.

#### Request Fields

| Field | Type | Required | Default | Rules |
| :--- | :--- | :--- | :--- | :--- |
| `file` | `file` (multipart) | Conditional | — | Strictly **1 file** (`file`, `media_file`, `media`, or `files` key). Multiple files are rejected with `400`. Image (`jpg`/`jpeg`/`png`/`webp` <= 10 MB) or Video (`mp4`/`mov` <= 200 MB). Omit if using `media_url`. |
| `media_url` | `string` | Conditional | — | Max `1000` chars. Valid `http://`, `https://`, or `/media/...` path with supported image/video extension. Omit if uploading `file`. Do not provide both `file` and `media_url`. |
| `source_post_id` | `string (uuid)` | No | `null` | UUID of an accessible `GymPost`. If both `file` and `media_url` are omitted, media is inherited from the first attachment of the source post (fails with `400` if source post has no media). |
| `thumbnail_url` | `string` | No | `null` | Max `1000` chars. Used when submitting `media_url`. |
| `file_size_bytes` | `integer` | No | `0` | Integer `>= 0`. Auto-populated for multipart uploads. |
| `duration_seconds` | `number (float)` | No | `null` | Non-negative float `>= 0.0` (e.g. `12.5` for video stories). |
| `lifetime_hours` | `integer \| string` | No | `18` | Allowed: `6`, `12`, `18`, `24`, `48` (or `"18h"`, `"24 hours"`). |
| `lifetime` | `integer \| string` | No | `18` | Alias for `lifetime_hours`. Do not send conflicting values with `lifetime_hours`. |
| `privacy` | `string` | No | `"public"` | User: `"public"`, `"followers"`, `"private"`. Gym: `"public"`, `"followers"`, `"members_only"` (`"gym_members_only"`), `"private"`. |
| `caption` | `string` | No | `null` | Max `500` chars (trimmed; blank becomes `null`). |
| `background_color` | `string` | No | `null` | Max `20` chars. Valid 3-, 6-, or 8-digit hex color (e.g. `"#111827"`). |

#### Request Payload Example (JSON with `media_url`)

```json
{
  "source_post_id": "a1b2c3d4-1111-2222-3333-444455556666",
  "media_url": "https://cdn.manygym.com/stories/clips/morning_workout.mp4",
  "thumbnail_url": "https://cdn.manygym.com/stories/thumbs/morning_workout.jpg",
  "file_size_bytes": 5242880,
  "duration_seconds": 14.5,
  "lifetime_hours": 24,
  "privacy": "followers",
  "caption": "Morning leg day session!",
  "background_color": "#111827"
}
```

#### Request Payload Example (Multipart Form-Data Fields)

- `file`: `<binary single image or video file>`
- `lifetime`: `18`
- `privacy`: `members_only`
- `caption`: `Gym maintenance notice at 6 PM`
- `background_color`: `#0F172A`
- `duration_seconds`: `10.0`
- `source_post_id`: `a1b2c3d4-1111-2222-3333-444455556666`

#### Response `201 Created` (Public User Story)

```json
{
  "id": "9f8c2a1b-3d4e-4f5a-9b1c-7e6d5c4b3a21",
  "owner_type": "user",
  "user_id": "84c9826f-9988-4433-2211-123456789abc",
  "user_name": "Alex Carter",
  "user_avatar_url": "https://api.manygym.com/media/users/avatars/alex.webp",
  "gym_id": null,
  "gym_name": null,
  "gym_avatar_url": null,
  "source_post_id": "a1b2c3d4-1111-2222-3333-444455556666",
  "source_post": {
    "id": "a1b2c3d4-1111-2222-3333-444455556666",
    "gym_id": "11111111-2222-3333-4444-555566667777",
    "gym_name": "Iron Peak Fitness",
    "content_text": "New squat racks installed today!",
    "privacy": "public",
    "published_at": "2026-11-12T08:00:00Z"
  },
  "media_url": "https://cdn.manygym.com/stories/clips/morning_workout.mp4",
  "original_url": "https://cdn.manygym.com/stories/clips/morning_workout.mp4",
  "optimized_url": null,
  "thumbnail_url": "https://cdn.manygym.com/stories/thumbs/morning_workout.jpg",
  "media_type": "video",
  "processing_status": "completed",
  "file_size_bytes": 5242880,
  "width": null,
  "height": null,
  "duration_seconds": 14.5,
  "caption": "Morning leg day session!",
  "background_color": "#111827",
  "lifetime_hours": 24,
  "lifetime_label": "24 hours",
  "privacy": "followers",
  "published_at": "2026-11-12T10:30:00Z",
  "expires_at": "2026-11-13T10:30:00Z",
  "is_expired": false,
  "is_archived": false,
  "views_count": 0,
  "has_viewed": false,
  "created_at": "2026-11-12T10:30:00Z",
  "updated_at": "2026-11-12T10:30:00Z"
}
```

#### Response `201 Created` (Gym Story)

```json
{
  "id": "c7e3b210-1234-4abc-8def-112233445566",
  "owner_type": "gym",
  "user_id": "55555555-6666-7777-8888-999999999999",
  "user_name": "Coach Maya",
  "user_avatar_url": "https://api.manygym.com/media/users/avatars/maya.webp",
  "gym_id": "11111111-2222-3333-4444-555566667777",
  "gym_name": "Iron Peak Fitness",
  "gym_avatar_url": "https://api.manygym.com/media/gyms/logos/iron_peak.webp",
  "source_post_id": null,
  "source_post": null,
  "media_url": "https://api.manygym.com/media/stories/media/original/banner.jpg",
  "original_url": "https://api.manygym.com/media/stories/media/original/banner.jpg",
  "optimized_url": null,
  "thumbnail_url": "https://api.manygym.com/media/stories/media/original/banner.jpg",
  "media_type": "picture",
  "processing_status": "pending",
  "file_size_bytes": 412890,
  "width": null,
  "height": null,
  "duration_seconds": null,
  "caption": "Gym maintenance notice at 6 PM",
  "background_color": "#0F172A",
  "lifetime_hours": 18,
  "lifetime_label": "18 hours",
  "privacy": "members_only",
  "published_at": "2026-11-12T10:35:00Z",
  "expires_at": "2026-11-13T04:35:00Z",
  "is_expired": false,
  "is_archived": false,
  "views_count": 0,
  "has_viewed": false,
  "created_at": "2026-11-12T10:35:00Z",
  "updated_at": "2026-11-12T10:35:00Z"
}
```

---

### 5.2. List Active Stories

- **Method:** `GET`
- **Endpoint:** `/api/v1/stories/`
- **Authentication:** Optional (authenticated requests include private/followers/members_only stories the user is permitted to see, and accurate `has_viewed`)
- **Request Body:** None

#### Query Parameters

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `owner_type` | `string (enum)` | No | — | Filter by `"user"` or `"gym"`. |
| `user_id` | `string (uuid)` | No | — | Filter by uploader user UUID. |
| `gym_id` | `string (uuid)` | No | — | Filter by gym UUID. |
| `feed_type` | `string` | No | `"all"` | `"all"`, `"followed"`, `"connected"`, or `"public"`. |
| `privacy` | `string (enum)` | No | — | `"public"`, `"followers"`, `"members_only"`, or `"private"`. |
| `page` | `integer` | No | `1` | 1-based page number (`>= 1`). |
| `page_size` | `integer` | No | `20` | Items per page (`1` to `100`). |

#### Response `200 OK`

```json
{
  "count": 2,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "c7e3b210-1234-4abc-8def-112233445566",
      "owner_type": "gym",
      "user_id": "55555555-6666-7777-8888-999999999999",
      "user_name": "Coach Maya",
      "user_avatar_url": "https://api.manygym.com/media/users/avatars/maya.webp",
      "gym_id": "11111111-2222-3333-4444-555566667777",
      "gym_name": "Iron Peak Fitness",
      "gym_avatar_url": "https://api.manygym.com/media/gyms/logos/iron_peak.webp",
      "source_post_id": null,
      "source_post": null,
      "media_url": "https://api.manygym.com/media/stories/media/original/optimized/banner_optimized.webp",
      "original_url": "https://api.manygym.com/media/stories/media/original/banner.jpg",
      "optimized_url": "https://api.manygym.com/media/stories/media/original/optimized/banner_optimized.webp",
      "thumbnail_url": "https://api.manygym.com/media/stories/media/original/thumbnails/banner_thumb.webp",
      "media_type": "picture",
      "processing_status": "completed",
      "file_size_bytes": 412890,
      "width": 1080,
      "height": 1920,
      "duration_seconds": null,
      "caption": "Gym maintenance notice at 6 PM",
      "background_color": "#0F172A",
      "lifetime_hours": 18,
      "lifetime_label": "18 hours",
      "privacy": "members_only",
      "published_at": "2026-11-12T10:35:00Z",
      "expires_at": "2026-11-13T04:35:00Z",
      "is_expired": false,
      "is_archived": false,
      "views_count": 42,
      "has_viewed": false,
      "created_at": "2026-11-12T10:35:00Z",
      "updated_at": "2026-11-12T10:35:02Z"
    }
  ]
}
```

---

### 5.3. Get Story Tray (Grouped by Owner)

- **Method:** `GET`
- **Endpoint:** `/api/v1/stories/tray/`
- **Authentication:** Optional
- **Ordering:** Buckets with `has_unviewed: true` first, then descending by `latest_story_at`. Within each bucket, `stories` are ordered chronologically (oldest first) for sequential playback.
- **Request Body:** None

#### Query Parameters

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `owner_type` | `string (enum)` | No | — | Filter by `"user"` or `"gym"`. |
| `feed_type` | `string` | No | `"all"` | `"all"`, `"followed"`, `"connected"`, or `"public"`. |

#### Response `200 OK`

```json
[
  {
    "owner_type": "gym",
    "owner_id": "11111111-2222-3333-4444-555566667777",
    "owner_name": "Iron Peak Fitness",
    "owner_avatar_url": "https://api.manygym.com/media/gyms/logos/iron_peak.webp",
    "latest_story_at": "2026-11-12T10:35:00Z",
    "has_unviewed": true,
    "stories_count": 1,
    "stories": [
      {
        "id": "c7e3b210-1234-4abc-8def-112233445566",
        "owner_type": "gym",
        "user_id": "55555555-6666-7777-8888-999999999999",
        "user_name": "Coach Maya",
        "user_avatar_url": "https://api.manygym.com/media/users/avatars/maya.webp",
        "gym_id": "11111111-2222-3333-4444-555566667777",
        "gym_name": "Iron Peak Fitness",
        "gym_avatar_url": "https://api.manygym.com/media/gyms/logos/iron_peak.webp",
        "source_post_id": null,
        "source_post": null,
        "media_url": "https://api.manygym.com/media/stories/media/original/optimized/banner_optimized.webp",
        "original_url": "https://api.manygym.com/media/stories/media/original/banner.jpg",
        "optimized_url": "https://api.manygym.com/media/stories/media/original/optimized/banner_optimized.webp",
        "thumbnail_url": "https://api.manygym.com/media/stories/media/original/thumbnails/banner_thumb.webp",
        "media_type": "picture",
        "processing_status": "completed",
        "file_size_bytes": 412890,
        "width": 1080,
        "height": 1920,
        "duration_seconds": null,
        "caption": "Gym maintenance notice at 6 PM",
        "background_color": "#0F172A",
        "lifetime_hours": 18,
        "lifetime_label": "18 hours",
        "privacy": "members_only",
        "published_at": "2026-11-12T10:35:00Z",
        "expires_at": "2026-11-13T04:35:00Z",
        "is_expired": false,
        "is_archived": false,
        "views_count": 42,
        "has_viewed": false,
        "created_at": "2026-11-12T10:35:00Z",
        "updated_at": "2026-11-12T10:35:02Z"
      }
    ]
  },
  {
    "owner_type": "user",
    "owner_id": "84c9826f-9988-4433-2211-123456789abc",
    "owner_name": "Alex Carter",
    "owner_avatar_url": "https://api.manygym.com/media/users/avatars/alex.webp",
    "latest_story_at": "2026-11-12T10:30:00Z",
    "has_unviewed": false,
    "stories_count": 1,
    "stories": [
      {
        "id": "9f8c2a1b-3d4e-4f5a-9b1c-7e6d5c4b3a21",
        "owner_type": "user",
        "user_id": "84c9826f-9988-4433-2211-123456789abc",
        "user_name": "Alex Carter",
        "user_avatar_url": "https://api.manygym.com/media/users/avatars/alex.webp",
        "gym_id": null,
        "gym_name": null,
        "gym_avatar_url": null,
        "source_post_id": "a1b2c3d4-1111-2222-3333-444455556666",
        "source_post": {
          "id": "a1b2c3d4-1111-2222-3333-444455556666",
          "gym_id": "11111111-2222-3333-4444-555566667777",
          "gym_name": "Iron Peak Fitness",
          "content_text": "New squat racks installed today!",
          "privacy": "public",
          "published_at": "2026-11-12T08:00:00Z"
        },
        "media_url": "https://cdn.manygym.com/stories/clips/morning_workout.mp4",
        "original_url": "https://cdn.manygym.com/stories/clips/morning_workout.mp4",
        "optimized_url": null,
        "thumbnail_url": "https://cdn.manygym.com/stories/thumbs/morning_workout.jpg",
        "media_type": "video",
        "processing_status": "completed",
        "file_size_bytes": 5242880,
        "width": null,
        "height": null,
        "duration_seconds": 14.5,
        "caption": "Morning leg day session!",
        "background_color": "#111827",
        "lifetime_hours": 24,
        "lifetime_label": "24 hours",
        "privacy": "followers",
        "published_at": "2026-11-12T10:30:00Z",
        "expires_at": "2026-11-13T10:30:00Z",
        "is_expired": false,
        "is_archived": false,
        "views_count": 15,
        "has_viewed": true,
        "created_at": "2026-11-12T10:30:00Z",
        "updated_at": "2026-11-12T10:30:00Z"
      }
    ]
  }
]
```

---

### 5.4. List My Stories (Personal or Active Gym Context)

- **Method:** `GET`
- **Endpoint:** `/api/v1/stories/my/`
- **Authentication:** Required (returns personal stories in personal token context, or the active gym's stories in gym token context if authorized)
- **Request Body:** None

#### Query Parameters

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `include_expired` | `boolean` | No | `false` | Accepts `true`, `1`, `yes`. When `true`, includes expired stories. |
| `include_archived` | `boolean` | No | `true` | Accepts `true`, `1`, `yes`, or `false`, `0`, `no`. |
| `page` | `integer` | No | `1` | 1-based page number (`>= 1`). |
| `page_size` | `integer` | No | `20` | Items per page (`1` to `100`). |

#### Response `200 OK`

```json
{
  "count": 1,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "9f8c2a1b-3d4e-4f5a-9b1c-7e6d5c4b3a21",
      "owner_type": "user",
      "user_id": "84c9826f-9988-4433-2211-123456789abc",
      "user_name": "Alex Carter",
      "user_avatar_url": "https://api.manygym.com/media/users/avatars/alex.webp",
      "gym_id": null,
      "gym_name": null,
      "gym_avatar_url": null,
      "source_post_id": "a1b2c3d4-1111-2222-3333-444455556666",
      "source_post": {
        "id": "a1b2c3d4-1111-2222-3333-444455556666",
        "gym_id": "11111111-2222-3333-4444-555566667777",
        "gym_name": "Iron Peak Fitness",
        "content_text": "New squat racks installed today!",
        "privacy": "public",
        "published_at": "2026-11-12T08:00:00Z"
      },
      "media_url": "https://cdn.manygym.com/stories/clips/morning_workout.mp4",
      "original_url": "https://cdn.manygym.com/stories/clips/morning_workout.mp4",
      "optimized_url": null,
      "thumbnail_url": "https://cdn.manygym.com/stories/thumbs/morning_workout.jpg",
      "media_type": "video",
      "processing_status": "completed",
      "file_size_bytes": 5242880,
      "width": null,
      "height": null,
      "duration_seconds": 14.5,
      "caption": "Morning leg day session!",
      "background_color": "#111827",
      "lifetime_hours": 24,
      "lifetime_label": "24 hours",
      "privacy": "followers",
      "published_at": "2026-11-12T10:30:00Z",
      "expires_at": "2026-11-13T10:30:00Z",
      "is_expired": false,
      "is_archived": false,
      "views_count": 15,
      "has_viewed": false,
      "created_at": "2026-11-12T10:30:00Z",
      "updated_at": "2026-11-12T10:30:00Z"
    }
  ]
}
```

---

### 5.5. Get Story Detail

- **Method:** `GET`
- **Endpoint:** `/api/v1/stories/{story_id}/`
- **Authentication:** Optional
- **Request Body:** None

#### Path & Query Parameters

| Parameter | Location | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `story_id` | Path | `string (uuid)` | Yes | — | Target story UUID. |
| `mark_viewed` | Query | `boolean` | No | `false` | Accepts `true`, `1`, `yes`. When `true` and authenticated, records a unique view and sets `has_viewed: true`. |

#### Response `200 OK`

```json
{
  "id": "9f8c2a1b-3d4e-4f5a-9b1c-7e6d5c4b3a21",
  "owner_type": "user",
  "user_id": "84c9826f-9988-4433-2211-123456789abc",
  "user_name": "Alex Carter",
  "user_avatar_url": "https://api.manygym.com/media/users/avatars/alex.webp",
  "gym_id": null,
  "gym_name": null,
  "gym_avatar_url": null,
  "source_post_id": "a1b2c3d4-1111-2222-3333-444455556666",
  "source_post": {
    "id": "a1b2c3d4-1111-2222-3333-444455556666",
    "gym_id": "11111111-2222-3333-4444-555566667777",
    "gym_name": "Iron Peak Fitness",
    "content_text": "New squat racks installed today!",
    "privacy": "public",
    "published_at": "2026-11-12T08:00:00Z"
  },
  "media_url": "https://cdn.manygym.com/stories/clips/morning_workout.mp4",
  "original_url": "https://cdn.manygym.com/stories/clips/morning_workout.mp4",
  "optimized_url": null,
  "thumbnail_url": "https://cdn.manygym.com/stories/thumbs/morning_workout.jpg",
  "media_type": "video",
  "processing_status": "completed",
  "file_size_bytes": 5242880,
  "width": null,
  "height": null,
  "duration_seconds": 14.5,
  "caption": "Morning leg day session!",
  "background_color": "#111827",
  "lifetime_hours": 24,
  "lifetime_label": "24 hours",
  "privacy": "followers",
  "published_at": "2026-11-12T10:30:00Z",
  "expires_at": "2026-11-13T10:30:00Z",
  "is_expired": false,
  "is_archived": false,
  "views_count": 16,
  "has_viewed": true,
  "created_at": "2026-11-12T10:30:00Z",
  "updated_at": "2026-11-12T10:30:00Z"
}
```

---

### 5.6. Update Story

- **Method:** `PATCH`
- **Endpoint:** `/api/v1/stories/{story_id}/`
- **Authentication:** Required (story owner, superuser, or authorized gym owner/staff with `stories:manage` / `posts:manage`)

#### Path & Request Fields

| Field | Location | Type | Required | Rules |
| :--- | :--- | :--- | :--- | :--- |
| `story_id` | Path | `string (uuid)` | Yes | Target story UUID. |
| `caption` | Body | `string \| null` | No | Max `500` chars. Send `null` or `""` to clear. |
| `background_color` | Body | `string \| null` | No | Max `20` chars. Valid hex color (`#RGB`, `#RRGGBB`, `#RRGGBBAA`) or `null` / `""` to clear. |
| `privacy` | Body | `string` | No | Must match the story's `owner_type` (`public`/`followers`/`private` for user; `public`/`followers`/`members_only`/`private` for gym). |
| `lifetime_hours` | Body | `integer \| string` | No | `6`, `12`, `18`, `24`, or `48`. Recalculates `expires_at = published_at + lifetime_hours`. |
| `lifetime` | Body | `integer \| string` | No | Alias for `lifetime_hours`. Do not send conflicting values with `lifetime_hours`. |
| `is_archived` | Body | `boolean` | No | Strictly boolean (`true` / `false`). |

#### Request Payload

```json
{
  "caption": "Updated leg day highlights!",
  "background_color": "#1E293B",
  "privacy": "public",
  "lifetime_hours": 48,
  "is_archived": false
}
```

#### Response `200 OK`

```json
{
  "id": "9f8c2a1b-3d4e-4f5a-9b1c-7e6d5c4b3a21",
  "owner_type": "user",
  "user_id": "84c9826f-9988-4433-2211-123456789abc",
  "user_name": "Alex Carter",
  "user_avatar_url": "https://api.manygym.com/media/users/avatars/alex.webp",
  "gym_id": null,
  "gym_name": null,
  "gym_avatar_url": null,
  "source_post_id": "a1b2c3d4-1111-2222-3333-444455556666",
  "source_post": {
    "id": "a1b2c3d4-1111-2222-3333-444455556666",
    "gym_id": "11111111-2222-3333-4444-555566667777",
    "gym_name": "Iron Peak Fitness",
    "content_text": "New squat racks installed today!",
    "privacy": "public",
    "published_at": "2026-11-12T08:00:00Z"
  },
  "media_url": "https://cdn.manygym.com/stories/clips/morning_workout.mp4",
  "original_url": "https://cdn.manygym.com/stories/clips/morning_workout.mp4",
  "optimized_url": null,
  "thumbnail_url": "https://cdn.manygym.com/stories/thumbs/morning_workout.jpg",
  "media_type": "video",
  "processing_status": "completed",
  "file_size_bytes": 5242880,
  "width": null,
  "height": null,
  "duration_seconds": 14.5,
  "caption": "Updated leg day highlights!",
  "background_color": "#1E293B",
  "lifetime_hours": 48,
  "lifetime_label": "48 hours",
  "privacy": "public",
  "published_at": "2026-11-12T10:30:00Z",
  "expires_at": "2026-11-14T10:30:00Z",
  "is_expired": false,
  "is_archived": false,
  "views_count": 16,
  "has_viewed": false,
  "created_at": "2026-11-12T10:30:00Z",
  "updated_at": "2026-11-12T11:00:00Z"
}
```

---

### 5.7. Delete Story

- **Method:** `DELETE`
- **Endpoint:** `/api/v1/stories/{story_id}/`
- **Authentication:** Required (story owner, superuser, or authorized gym owner/staff with `stories:manage` / `posts:manage`)
- **Request Body:** None

#### Path Parameter

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `story_id` | `string (uuid)` | Yes | Target story UUID. |

#### Response `200 OK`

```json
{
  "message": "Story deleted successfully."
}
```

---

### 5.8. Record Story View

- **Method:** `POST`
- **Endpoint:** `/api/v1/stories/{story_id}/view/`
- **Authentication:** Required
- **Behavior:** Idempotent per `(story_id, viewer_user_id)`. Self-views (and views by managing staff of the owning gym) do not increment `views_count` (`newly_viewed: false`).
- **Request Body:** None (`{}`)

#### Path Parameter

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `story_id` | `string (uuid)` | Yes | Active, visible story UUID. |

#### Response Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `message` | `string` | `"Story view recorded."` on first view, or `"Story already viewed."` on repeat/self view. |
| `views_count` | `integer` | Current total unique view count for the story. |
| `newly_viewed` | `boolean` | `true` if a new view record was created; `false` otherwise. |

#### Response `200 OK`

```json
{
  "message": "Story view recorded.",
  "views_count": 17,
  "newly_viewed": true
}
```

---

### 5.9. List Story Viewers

- **Method:** `GET`
- **Endpoint:** `/api/v1/stories/{story_id}/viewers/`
- **Authentication:** Required (story owner, superuser, or authorized gym owner/staff with `stories:manage` / `posts:manage`; returns `403` for other users)
- **Request Body:** None

#### Path & Query Parameters

| Parameter | Location | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `story_id` | Path | `string (uuid)` | Yes | — | Target story UUID. |
| `page` | Query | `integer` | No | `1` | 1-based page number (`>= 1`). |
| `page_size` | Query | `integer` | No | `20` | Items per page (`1` to `100`). |

#### Response `200 OK`

```json
{
  "count": 1,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "e1f2a3b4-5678-49ab-9cde-0123456789ab",
      "viewer_user_id": "22222222-3333-4444-5555-666666666666",
      "viewer_name": "Jordan Lee",
      "viewer_avatar_url": "https://api.manygym.com/media/users/avatars/jordan.webp",
      "viewed_at": "2026-11-12T10:45:12Z"
    }
  ]
}
```

