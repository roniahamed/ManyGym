# Posts & Reposts API & Frontend Integration Documentation

## 1. General Configuration

* **Base URL:** `/api/v1/posts/`
* **Authentication:** JWT Bearer Token (`Authorization: Bearer <token>`)
* **Accepted Request Formats:**
  * `application/json` (for text-only posts, URL-backed media posts, reposts, updates, and reads)
  * `multipart/form-data` (for direct file uploads during post creation, story repost with optional media, or custom video thumbnail upload)
* **Standard Headers:**
  * `Authorization: Bearer <token>` (Required for write endpoints and `/my/`; optional for public `GET` endpoints)
  * `X-Gym-Context: <gym_uuid>` (Optional fallback gym context header when switching to a gym without embedding `gym_id` inside the JWT claims)
  * `Content-Type: application/json` or `multipart/form-data`

### 1.1 Automatic Token Context & Read-Only Fields

All write operations and `/api/v1/posts/my/` resolve `owner_type`, `author_user_id`, and `gym_id` directly from the authenticated Bearer JWT claims (`context_type`, `gym_id`) and optional `X-Gym-Context` header (`gym_id` query/body parameter is also accepted for backward-compatible gym management calls when managing an existing gym context).

| Context | JWT / Header State | Resolved `owner_type` | `author_user_id` | `gym_id` | Permission Rule |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Public User (Personal Profile)** | Default (`context_type: "personal"` or omitted, no `gym_id`) | `"user"` | Authenticated user UUID | `null` | Any authenticated active user |
| **Gym Profile / Page** | `context_type: "gym"` with `gym_id`, or `X-Gym-Context: <gym_uuid>` (or explicit `gym_id` override on create/detail/thumbnail) | `"gym"` | Authenticated actor UUID | Target gym UUID | Gym owner, active gym staff (`GymStaff`), or superuser |

Clients MUST NOT send `owner_type`, `author_user_id`, `is_repost`, or `reposts_count` in create/repost/update requests; these are server-derived.

---

## 2. Global Error Envelope & Status Codes

All error responses return a uniform JSON envelope:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Human-readable error summary.",
  "details": {
    "privacy": [
      "Public users can only choose public, followers, or private privacy."
    ]
  }
}
```

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `code` | string | No | Machine-readable error code: `VALIDATION_ERROR`, `UNAUTHORIZED_CONTEXT`, `RESOURCE_CONFLICT`, `PERMISSION_DENIED`, `RESOURCE_NOT_FOUND` |
| `message` | string | No | Summary message describing the failure |
| `details` | object \| array \| null | Yes | Field-level validation errors or context object; `null` when unavailable |

### HTTP Status Codes

| Status Code | Error Code | Cause |
| :--- | :--- | :--- |
| `400 Bad Request` | `VALIDATION_ERROR` | Invalid UUID, invalid privacy for owner type, invalid target, invalid media format/size, missing required fields, or self-inconsistent payload |
| `401 Unauthorized` | `UNAUTHORIZED_CONTEXT` | Missing, expired, or invalid Bearer token on authenticated endpoints |
| `403 Forbidden` | `PERMISSION_DENIED` | Insufficient gym staff/owner role, blocked user relationship, underage restriction (`< 18` for 18+ gym/post), or private/restricted `source_post` |
| `404 Not Found` | `RESOURCE_NOT_FOUND` | Post, `source_post_id`, `gym_id`, or `media_id` does not exist or is soft-deleted |
| `405 Method Not Allowed` | `METHOD_NOT_ALLOWED` | Unsupported HTTP method on the endpoint |

---

## 3. Enums & Validation Reference

### 3.1 `owner_type` (`PostOwnerTypeEnum`)

| Value | Label | Description |
| :--- | :--- | :--- |
| `"user"` | Public User | Post/Repost published on a personal user profile (`gym_id` is `null`) |
| `"gym"` | Gym | Post/Repost published on a gym page (`gym_id` is set) |

### 3.2 `target` (`RepostTargetEnum`)

| Accepted Input | Canonical Value | Description |
| :--- | :--- | :--- |
| `"profile"`, `"profile_feed"`, `"feed"` | `"profile"` | Share onto the actor's profile feed as a `GymPost` repost (`is_repost: true`) |
| `"story"` | `"story"` | Share onto the actor's active Story feed as a `Story` (`source_post_id` set) |

### 3.3 `privacy` (`PostPrivacyEnum`) by Owner Type

| Canonical Value | Accepted Input Aliases | Personal User (`owner_type: "user"`) | Gym (`owner_type: "gym"`) | Visibility Rule |
| :--- | :--- | :--- | :--- | :--- |
| `"public"` | `"public"` | Allowed (Default) | Allowed (Default) | Visible to all users (including unauthenticated/guest viewers unless blocked or underage) |
| `"followers"` | `"followers"` | Allowed | Allowed | Visible to the author/gym staff and users following the post owner (`UserFollow` for user posts, `GymFollow` for gym posts) |
| `"members_only"` | `"members_only"`, `"gym_members_only"` | **Rejected (`400`)** | Allowed | Visible to connected/verified members of the owning gym, gym owner, and active gym staff |
| `"private"` | `"private"` | Allowed | Allowed | User post: author only. Gym post: gym owner, active gym staff, or post author |

### 3.4 `feed_type` / `source` (`FeedTypeEnum`)

| Canonical Value | Accepted Input Aliases | Description |
| :--- | :--- | :--- |
| `"all"` | `"all"` | Default combined feed matching viewer's social/visibility context |
| `"followed"` | `"followed"`, `"following"` | Only posts/reposts from users or gyms the authenticated user follows (plus own posts); requires authentication if viewer-specific, otherwise returns empty |
| `"connected"` | `"connected"`, `"connected_gym"`, `"my_gym"` | Only posts/reposts from gyms the authenticated user is connected to |
| `"public"` | `"public"`, `"explore"` | Public discovery feed across eligible users and gyms |

### 3.5 `media_type` & `processing_status`

| Field | Values |
| :--- | :--- |
| `media_type` | `"picture"`, `"video"` |
| `processing_status` | `"pending"`, `"processing"`, `"completed"`, `"failed"` |

### 3.6 Story Lifetime (`lifetime_hours` / `lifetime` when `target: "story"`)

| Accepted Numeric Values | Accepted String Aliases | Canonical Integer Returned | Display Label (`lifetime_label`) |
| :--- | :--- | :--- | :--- |
| `6` | `"6"`, `"6h"`, `"6 hours"`, `"6_hours"` | `6` | `"6 hours"` |
| `12` | `"12"`, `"12h"`, `"12 hours"`, `"12_hours"` | `12` | `"12 hours"` |
| `18` | `"18"`, `"18h"`, `"18 hours"`, `"18_hours"` | `18` (Default) | `"18 hours"` |
| `24` | `"24"`, `"24h"`, `"24 hours"`, `"24_hours"` | `24` | `"24 hours"` |
| `48` | `"48"`, `"48h"`, `"48 hours"`, `"48_hours"` | `48` | `"48 hours"` |

### 3.7 Media Upload Constraints

| Upload Type | Allowed Extensions | Max File Size | Max Items Per Request |
| :--- | :--- | :--- | :--- |
| Post Picture (`files` / `media_files` / `file`) | `.jpg`, `.jpeg`, `.png`, `.webp` | 10 MB | Combined total of `files` + `media_items` = 10 |
| Post Video (`files` / `media_files` / `file`) | `.mp4`, `.mov` | 200 MB | Combined total of `files` + `media_items` = 10 |
| Repost to Story (`file`) | Same as above | Same as above | 1 |
| Custom Video Thumbnail (`thumbnail_image` / `file`) | `.jpg`, `.jpeg`, `.png`, `.webp` | 10 MB | 1 (video attachments only) |

---

## 4. Schema Models (All Fields)

### 4.1 Post / Profile Repost Object (`GymPostListSerializer` / `GymPostDetailSerializer`)

Returned by feed, my-posts, detail, create (profile target), repost (`target: "profile"`), reposts list, and update endpoints.

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | string (UUID) | No | Unique post/repost identifier |
| `owner_type` | string (`"user"` \| `"gym"`) | No | Ownership scope of this post/repost |
| `gym_id` | string (UUID) | Yes | Owning gym UUID (`null` when `owner_type: "user"`) |
| `gym_name` | string | Yes | Owning gym name (`null` when `owner_type: "user"`) |
| `gym_avatar_url` | string (URI) | Yes | Owning gym logo/avatar absolute URI (`null` when `owner_type: "user"` or unset) |
| `author_user_id` | string (UUID) | No | Author user UUID |
| `author_name` | string | No | Author full name (fallback: email, then `"Unknown"`) |
| `author_avatar_url` | string (URI) | Yes | Author profile image absolute URI or `null` |
| `content_text` | string | Yes | Post body text or optional commentary added to a repost |
| `privacy` | string | No | Canonical privacy (`"public"`, `"followers"`, `"members_only"`, `"private"`) |
| `is_repost` | boolean | No | `true` if this entry is a repost of another post; `false` otherwise |
| `source_post_id` | string (UUID) | Yes | UUID of the original/referenced post (`null` if not a repost or if source was hard-deleted) |
| `source_post` | object ([4.2](#42-embedded-source-post-summary-object-sourcepostsummaryserializer)) | Yes | Embedded summary of the original post; `null` if not a repost, soft-deleted, or hidden from current viewer |
| `source_post_unavailable` | boolean | No | `true` when `is_repost: true` but `source_post` cannot be displayed (deleted, blocked, private, or restricted) |
| `reposts_count` | integer | No | Total repost/share count incremented when profile reposts or story shares are created from this post (decremented when a profile repost is deleted) |
| `published_at` | string (ISO 8601) | No | Publication timestamp |
| `media_count` | integer | No | Count of non-deleted media attachments directly on this post |
| `media_attachments` | array\<object\> ([4.3](#43-post-media-attachment-object-gympostmediaserializer)) | No | Ordered list (`order_index` ascending) of direct media attachments |
| `is_following_gym` | boolean | No | `true` if authenticated viewer follows `gym_id` (always `false` for user posts or unauthenticated viewers) |
| `is_following_author` | boolean | No | `true` if authenticated viewer follows `author_user_id` |
| `is_connected_gym` | boolean | No | `true` if authenticated viewer is connected to `gym_id` (always `false` for user posts or unauthenticated viewers) |
| `created_at` | string (ISO 8601) | No | Record creation timestamp |
| `updated_at` | string (ISO 8601) | No | Record last update timestamp |
| `target` | string (`"profile"`) | Yes | Included only in `201 Created` responses from `POST .../repost/` when `target` is `"profile"` |

### 4.2 Embedded Source Post Summary Object (`SourcePostSummarySerializer`)

Nested inside `source_post` on a Post/Repost when `is_repost: true` and the viewer is authorized to see the source post.

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | string (UUID) | No | Source post UUID |
| `owner_type` | string (`"user"` \| `"gym"`) | No | Source post owner type |
| `gym_id` | string (UUID) | Yes | Source post gym UUID (`null` if user-owned) |
| `gym_name` | string | Yes | Source post gym name (`null` if user-owned) |
| `gym_avatar_url` | string (URI) | Yes | Source post gym avatar URI (`null` if user-owned or unset) |
| `author_user_id` | string (UUID) | No | Source post author UUID |
| `author_name` | string | No | Source post author display name |
| `author_avatar_url` | string (URI) | Yes | Source post author profile image URI or `null` |
| `content_text` | string | Yes | Source post body text |
| `privacy` | string | No | Source post canonical privacy |
| `is_repost` | boolean | No | Whether the source post itself was a repost |
| `source_post_id` | string (UUID) | Yes | Parent source UUID if the source post was itself a repost |
| `reposts_count` | integer | No | Total reposts count of the source post |
| `published_at` | string (ISO 8601) | No | Source post publication timestamp |
| `media_count` | integer | No | Number of direct media attachments on the source post |
| `media_attachments` | array\<object\> ([4.3](#43-post-media-attachment-object-gympostmediaserializer)) | No | Media attachments belonging to the source post |
| `created_at` | string (ISO 8601) | No | Source post creation timestamp |
| `updated_at` | string (ISO 8601) | No | Source post last update timestamp |

### 4.3 Post Media Attachment Object (`GymPostMediaSerializer`)

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | string (UUID) | No | Media attachment UUID |
| `post_id` | string (UUID) | No | Parent post UUID |
| `media_url` | string (URI) | No | Best resolved playback/display URI (optimized URL if available, else original URL) |
| `original_url` | string (URI) | Yes | Original uploaded/provided media URI |
| `optimized_url` | string (URI) | Yes | Transcoded/optimized media URI if processed |
| `media_type` | string (`"picture"` \| `"video"`) | No | Attachment media type |
| `thumbnail_url` | string (URI) | Yes | Video thumbnail URI (`null` for pictures or if not yet generated) |
| `file_size_bytes` | integer | No | File size in bytes |
| `order_index` | integer | No | 0-based display order index |
| `processing_status` | string | No | Async optimization status (`"pending"`, `"processing"`, `"completed"`, `"failed"`) |
| `created_at` | string (ISO 8601) | No | Attachment creation timestamp |

### 4.4 Story Repost Response Object (`StorySerializer` + `target`)

Returned on `201 Created` when `target: "story"` is passed to `POST /api/v1/posts/{post_id}/repost/`, `POST /api/v1/posts/repost/`, or `POST /api/v1/posts/`.

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | string (UUID) | No | Created Story UUID |
| `target` | string (`"story"`) | No | Included on repost/share-to-story response |
| `owner_type` | string (`"user"` \| `"gym"`) | No | Story owner type resolved from token context |
| `user_id` | string (UUID) | No | Story author/creator user UUID |
| `user_name` | string | No | Story author display name |
| `user_avatar_url` | string (URI) | Yes | Story author avatar URI or `null` |
| `gym_id` | string (UUID) | Yes | Story owning gym UUID (`null` when `owner_type: "user"`) |
| `gym_name` | string | Yes | Story owning gym name (`null` when `owner_type: "user"`) |
| `gym_avatar_url` | string (URI) | Yes | Story owning gym avatar URI or `null` |
| `source_post_id` | string (UUID) | Yes | Shared source post UUID |
| `source_post` | object ([4.4.1](#441-story-embedded-source-post-object-storysourcepostsummaryserializer)) | Yes | Summary of the shared post |
| `media_url` | string (URI) | No | Resolved Story media URI (inherited from source post/root post or uploaded media) |
| `original_url` | string (URI) | Yes | Original media URI |
| `optimized_url` | string (URI) | Yes | Optimized media URI |
| `thumbnail_url` | string (URI) | Yes | Video thumbnail URI |
| `media_type` | string (`"picture"` \| `"video"`) | No | Media type of the Story |
| `processing_status` | string | No | `"pending"`, `"processing"`, `"completed"`, `"failed"` |
| `file_size_bytes` | integer | No | File size in bytes |
| `width` | integer | Yes | Media width in pixels |
| `height` | integer | Yes | Media height in pixels |
| `duration_seconds` | number (float) | Yes | Video duration in seconds |
| `caption` | string | Yes | Story caption (`caption`, fallback to `content_text` if provided) |
| `background_color` | string | Yes | Hex background color (e.g., `"#121212"`) |
| `lifetime_hours` | integer | No | Configured expiration hours (`6`, `12`, `18`, `24`, `48`) |
| `lifetime_label` | string | No | Display label (e.g., `"24 hours"`) |
| `privacy` | string | No | Story privacy (`"public"`, `"followers"`, `"members_only"`, `"private"`) |
| `published_at` | string (ISO 8601) | No | Publication timestamp |
| `expires_at` | string (ISO 8601) | No | Expiration timestamp (`published_at + lifetime_hours`) |
| `is_expired` | boolean | No | Whether `expires_at` has passed |
| `is_archived` | boolean | No | Whether the story is archived |
| `views_count` | integer | No | Total Story views |
| `has_viewed` | boolean | No | Whether the requesting user has viewed the Story |
| `created_at` | string (ISO 8601) | No | Creation timestamp |
| `updated_at` | string (ISO 8601) | No | Last update timestamp |

#### 4.4.1 Story Embedded Source Post Object (`StorySourcePostSummarySerializer`)

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | string (UUID) | No | Source post UUID |
| `owner_type` | string (`"user"` \| `"gym"`) | No | Source post owner type |
| `gym_id` | string (UUID) | Yes | Source post gym UUID (`null` if user-owned) |
| `gym_name` | string | Yes | Source post gym name (`null` if user-owned) |
| `author_user_id` | string (UUID) | No | Source post author UUID |
| `author_name` | string | No | Source post author display name |
| `content_text` | string | Yes | Source post text content |
| `privacy` | string | No | Source post canonical privacy |
| `is_repost` | boolean | No | Whether the source post was itself a repost |
| `source_post_id` | string (UUID) | Yes | Parent source UUID if `is_repost: true` |
| `published_at` | string (ISO 8601) | No | Source post publication timestamp |

### 4.5 Standard Paginated Envelope (`StandardResultsSetPagination`)

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `count` | integer | No | Total matching items across all pages |
| `total_pages` | integer | No | Total pages available |
| `current_page` | integer | No | Current 1-based page number |
| `next` | string (URI) | Yes | Full URL for next page or `null` |
| `previous` | string (URI) | Yes | Full URL for previous page or `null` |
| `results` | array\<object\> | No | Page slice of post/repost objects ([4.1](#41-post--profile-repost-object-gympostlistserializer--gympostdetailserializer)) |

### 4.6 Message Response Object (`MessageResponseSerializer`)

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `message` | string | No | Confirmation message |

---

## 5. Complete API Endpoints

### 5.1 List Community & Profile Feed

* **Method:** `GET`
* **Endpoint:** `/api/v1/posts/` (Alias: `/api/v1/posts/feed/`)
* **Auth Required:** Optional (`AllowAny`)

#### Query Parameters (`GymFeedFilterSerializer`)

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `owner_type` | string | No | `null` | Filter by `"user"` or `"gym"` |
| `user_id` | string (UUID) | No | `null` | Filter profile posts/reposts authored/owned by a specific public user |
| `gym_id` | string (UUID) | No | `null` | Filter posts/reposts owned by a specific gym |
| `feed_type` | string | No | `"all"` | Feed filter: `"all"`, `"followed"` (`"following"`), `"connected"` (`"connected_gym"`, `"my_gym"`), `"public"` (`"explore"`) |
| `source` | string | No | `null` | Legacy alias for `feed_type` (cannot conflict with `feed_type`) |
| `privacy` | string | No | `null` | Filter by canonical privacy or alias (`"public"`, `"followers"`, `"members_only"`, `"gym_members_only"`, `"private"`) |
| `is_repost` | boolean | No | `null` | `true` for reposts only, `false` for original posts only |
| `search` | string | No | `null` | Case-insensitive text search across post text, original `source_post` text, gym name, or author name (max 200 chars) |
| `page` | integer | No | `1` | 1-based page number (min `1`) |
| `page_size` | integer | No | `20` | Items per page (`1` to `100`) |

#### Response JSON (`200 OK`)

```json
{
  "count": 2,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "9a1c8e12-4b7d-4e92-a311-112233445566",
      "owner_type": "user",
      "gym_id": null,
      "gym_name": null,
      "gym_avatar_url": null,
      "author_user_id": "2c8d1f10-1234-4abc-8def-001122334455",
      "author_name": "Alex Rivera",
      "author_avatar_url": "https://cdn.example.com/avatars/alex.jpg",
      "content_text": "Great Sunday leg day routine!",
      "privacy": "followers",
      "is_repost": true,
      "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
      "source_post": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "owner_type": "gym",
        "gym_id": "7b21a900-8899-4111-9222-334455667788",
        "gym_name": "Iron Peak Gym",
        "gym_avatar_url": "https://cdn.example.com/gyms/iron-peak.png",
        "author_user_id": "8e44c210-7766-4321-8899-aabbccddeeff",
        "author_name": "Coach Sam",
        "author_avatar_url": "https://cdn.example.com/avatars/sam.jpg",
        "content_text": "Squat clinic starts at 9 AM.",
        "privacy": "public",
        "is_repost": false,
        "source_post_id": null,
        "reposts_count": 4,
        "published_at": "2026-11-12T08:00:00Z",
        "media_count": 1,
        "media_attachments": [
          {
            "id": "aa11bb22-cc33-44dd-88ee-ff0011223344",
            "post_id": "550e8400-e29b-41d4-a716-446655440000",
            "media_url": "https://cdn.example.com/posts/squat-clinic.jpg",
            "original_url": "https://cdn.example.com/posts/squat-clinic.jpg",
            "optimized_url": null,
            "media_type": "picture",
            "thumbnail_url": null,
            "file_size_bytes": 245120,
            "order_index": 0,
            "processing_status": "completed",
            "created_at": "2026-11-12T08:00:00Z"
          }
        ],
        "created_at": "2026-11-12T08:00:00Z",
        "updated_at": "2026-11-12T08:00:00Z"
      },
      "source_post_unavailable": false,
      "reposts_count": 0,
      "published_at": "2026-11-12T10:30:00Z",
      "media_count": 0,
      "media_attachments": [],
      "is_following_gym": false,
      "is_following_author": true,
      "is_connected_gym": false,
      "created_at": "2026-11-12T10:30:00Z",
      "updated_at": "2026-11-12T10:30:00Z"
    }
  ]
}
```

---

### 5.2 List My Profile Feed

* **Method:** `GET`
* **Endpoint:** `/api/v1/posts/my/`
* **Auth Required:** Yes (`IsAuthenticated`)
* **Context Behavior:**
  * Personal token context: returns all posts and profile reposts where `owner_type: "user"` and `author_user_id` matches the authenticated user (including `public`, `followers`, and `private`).
  * Gym token context (`context_type: "gym"` + `gym_id` or `X-Gym-Context` header): returns all posts and profile reposts belonging to that gym (requires gym owner, active staff, or superuser; returns `403 PERMISSION_DENIED` otherwise).

#### Query Parameters

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `privacy` | string | No | `null` | Filter by privacy (`"public"`, `"followers"`, `"members_only"`, `"private"`) |
| `is_repost` | boolean | No | `null` | Filter to reposts (`true`) or original posts (`false`) |
| `search` | string | No | `null` | Text search across post content or source post content |
| `page` | integer | No | `1` | 1-based page number |
| `page_size` | integer | No | `20` | Items per page (`1` to `100`) |

#### Response JSON (`200 OK`)

Same paginated envelope as [5.1](#response-json-200-ok) (`count`, `total_pages`, `current_page`, `next`, `previous`, `results`).

---

### 5.3 Create Post or Profile Repost (Personal User or Gym)

* **Method:** `POST`
* **Endpoint:** `/api/v1/posts/` (Alias: `/api/v1/posts/feed/`)
* **Auth Required:** Yes (`IsAuthenticated`)
* **Context Behavior:** Automatically creates a personal user post (`owner_type: "user"`) or gym post (`owner_type: "gym"`) based on Bearer token claims / `X-Gym-Context`. If `source_post_id` is provided, behaves identically to a repost to `target` (`"profile"` or `"story"`).

#### Request Fields (`GymPostCreateSerializer`)

| Field | Type | Required | Default | Constraints / Notes |
| :--- | :--- | :--- | :--- | :--- |
| `content_text` | string | Conditional | `null` | Required unless `media_items`, `files`, or `source_post_id` is supplied |
| `privacy` | string | No | `"public"` | User allows: `"public"`, `"followers"`, `"private"`. Gym allows: `"public"`, `"followers"`, `"members_only"` (`"gym_members_only"`), `"private"` |
| `source_post_id` | string (UUID) | No | `null` | If supplied, creates a repost of that post targeting `target` |
| `target` | string | No | `"profile"` | Used when `source_post_id` is provided (`"profile"` or `"story"`). Passing `target: "story"` without `source_post_id` returns `400 VALIDATION_ERROR` |
| `caption` | string | No | `null` | Optional caption when `target: "story"` and `source_post_id` is supplied (max 500 chars) |
| `background_color` | string | No | `null` | Optional hex background color when `target: "story"` (max 20 chars) |
| `lifetime_hours` | integer \| string | No | `18` | Story lifetime when `target: "story"` (`6`, `12`, `18`, `24`, `48`) |
| `lifetime` | integer \| string | No | `null` | Alias for `lifetime_hours` (cannot conflict with `lifetime_hours`) |
| `media_url` | string (URI) | No | `null` | Single external media URL fallback when `target: "story"` (max 1000 chars) |
| `thumbnail_url` | string (URI) | No | `null` | Optional thumbnail URL when `target: "story"` (max 1000 chars) |
| `file_size_bytes` | integer | No | `0` | Optional file size (>= `0`) when `media_url` is provided with `target: "story"` |
| `duration_seconds` | number (float) | No | `null` | Optional duration (>= `0.0`) when `target: "story"` |
| `media_items` | array\<object\> | No | `[]` | JSON list of pre-uploaded media descriptors (see [5.3.1](#531-media_items-element-schema)) |
| `files` | array\<file\> | No | `[]` | Multipart file uploads (`files`, `media_files`, or `file` keys accepted; max 10 total items) |
| `gym_id` | string (UUID) | No | `null` | Optional query/body gym UUID when managing a gym outside token `gym_id` claims (validated for gym permissions) |

#### 5.3.1 `media_items` Element Schema

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `media_url` | string (URI) | Yes | - | Media URL (max 1000 chars) |
| `media_type` | string | Yes | - | `"picture"` or `"video"` |
| `thumbnail_url` | string (URI) | No | `null` | Video thumbnail URL (max 1000 chars) |
| `file_size_bytes` | integer | No | `0` | File size in bytes (min `0`) |
| `order_index` | integer | No | item index | 0-based order index (min `0`) |

#### Request Payload Example 1: Personal User Post (`application/json`)

```json
{
  "content_text": "Morning 10K run completed before work!",
  "privacy": "followers",
  "media_items": [
    {
      "media_url": "https://cdn.example.com/uploads/run-stats.png",
      "media_type": "picture",
      "file_size_bytes": 182400,
      "order_index": 0
    }
  ]
}
```

#### Request Payload Example 2: Gym Post (`application/json`, Gym Token or `X-Gym-Context`)

```json
{
  "content_text": "New Olympic lifting platforms are now open for all members.",
  "privacy": "members_only"
}
```

#### Response JSON (`201 Created` — Personal User Post)

```json
{
  "id": "d4e5f6a7-1122-4334-9556-778899aabbcc",
  "owner_type": "user",
  "gym_id": null,
  "gym_name": null,
  "gym_avatar_url": null,
  "author_user_id": "2c8d1f10-1234-4abc-8def-001122334455",
  "author_name": "Alex Rivera",
  "author_avatar_url": "https://cdn.example.com/avatars/alex.jpg",
  "content_text": "Morning 10K run completed before work!",
  "privacy": "followers",
  "is_repost": false,
  "source_post_id": null,
  "source_post": null,
  "source_post_unavailable": false,
  "reposts_count": 0,
  "published_at": "2026-11-12T12:00:00Z",
  "media_count": 1,
  "media_attachments": [
    {
      "id": "11223344-5566-4777-8888-999900001111",
      "post_id": "d4e5f6a7-1122-4334-9556-778899aabbcc",
      "media_url": "https://cdn.example.com/uploads/run-stats.png",
      "original_url": "https://cdn.example.com/uploads/run-stats.png",
      "optimized_url": null,
      "media_type": "picture",
      "thumbnail_url": null,
      "file_size_bytes": 182400,
      "order_index": 0,
      "processing_status": "completed",
      "created_at": "2026-11-12T12:00:00Z"
    }
  ],
  "is_following_gym": false,
  "is_following_author": false,
  "is_connected_gym": false,
  "created_at": "2026-11-12T12:00:00Z",
  "updated_at": "2026-11-12T12:00:00Z"
}
```

---

### 5.4 Repost Post (Share on Profile or Share on Story)

* **Method:** `POST`
* **Endpoints:**
  * `/api/v1/posts/{post_id}/repost/`
  * `/api/v1/posts/repost/`
* **Auth Required:** Yes (`IsAuthenticated`)
* **Context Behavior:** Actor identity (`owner_type`: `"user"` or `"gym"`, plus `gym_id` if gym context) is automatically resolved from the Bearer token / `X-Gym-Context` header. Can repost any accessible post (another user's post, a gym's post, or your own previous post).

#### Path Parameters

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `post_id` | string (UUID) | Conditional | Required on `/api/v1/posts/{post_id}/repost/`. Omit on `/api/v1/posts/repost/` |

#### Request Fields (`RepostCreateSerializer`)

| Field | Type | Required | Default | Constraints / Notes |
| :--- | :--- | :--- | :--- | :--- |
| `source_post_id` | string (UUID) | Conditional | `null` | Required when calling `/api/v1/posts/repost/`. Optional on `/api/v1/posts/{post_id}/repost/` (if provided, must match URL `post_id`) |
| `target` | string | No | `"profile"` | `"profile"` (aliases: `"profile_feed"`, `"feed"`) or `"story"` |
| `privacy` | string | No | `"public"` | User allows: `"public"`, `"followers"`, `"private"`. Gym allows: `"public"`, `"followers"`, `"members_only"` (`"gym_members_only"`), `"private"` |
| `content_text` | string | No | `null` | Optional commentary text on profile reposts; also used as `caption` fallback when `target: "story"` and `caption` is omitted |
| `caption` | string | No | `null` | Story caption when `target: "story"` (max 500 chars) |
| `background_color` | string | No | `null` | Story background hex color when `target: "story"` (max 20 chars) |
| `lifetime_hours` | integer \| string | No | `18` | Story lifetime when `target: "story"` (`6`, `12`, `18`, `24`, `48`) |
| `lifetime` | integer \| string | No | `null` | Alias for `lifetime_hours` when `target: "story"` |
| `media_url` | string (URI) | No | `null` | Optional fallback media URL when sharing a text-only post to Story (max 1000 chars) |
| `thumbnail_url` | string (URI) | No | `null` | Optional thumbnail URL when `target: "story"` (max 1000 chars) |
| `file_size_bytes` | integer | No | `0` | Optional file size (>= `0`) when `media_url` is provided with `target: "story"` |
| `duration_seconds` | number (float) | No | `null` | Optional video duration (>= `0.0`) when `target: "story"` |
| `file` | file (binary) | No | `null` | Optional single media upload (`multipart/form-data`) when `target: "story"`. Not required if source post (or root original post) already contains media |

#### Request Payload Example A: Share on Profile (`target: "profile"`, `application/json`)

```json
{
  "target": "profile",
  "privacy": "followers",
  "content_text": "Sharing this workout tip to my profile!"
}
```

#### Response JSON (`201 Created` — Share on Profile)

```json
{
  "id": "f9e8d7c6-5432-4100-9abc-def012345678",
  "owner_type": "user",
  "gym_id": null,
  "gym_name": null,
  "gym_avatar_url": null,
  "author_user_id": "2c8d1f10-1234-4abc-8def-001122334455",
  "author_name": "Alex Rivera",
  "author_avatar_url": "https://cdn.example.com/avatars/alex.jpg",
  "content_text": "Sharing this workout tip to my profile!",
  "privacy": "followers",
  "is_repost": true,
  "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_post": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "owner_type": "gym",
    "gym_id": "7b21a900-8899-4111-9222-334455667788",
    "gym_name": "Iron Peak Gym",
    "gym_avatar_url": "https://cdn.example.com/gyms/iron-peak.png",
    "author_user_id": "8e44c210-7766-4321-8899-aabbccddeeff",
    "author_name": "Coach Sam",
    "author_avatar_url": "https://cdn.example.com/avatars/sam.jpg",
    "content_text": "Squat clinic starts at 9 AM.",
    "privacy": "public",
    "is_repost": false,
    "source_post_id": null,
    "reposts_count": 5,
    "published_at": "2026-11-12T08:00:00Z",
    "media_count": 1,
    "media_attachments": [
      {
        "id": "aa11bb22-cc33-44dd-88ee-ff0011223344",
        "post_id": "550e8400-e29b-41d4-a716-446655440000",
        "media_url": "https://cdn.example.com/posts/squat-clinic.jpg",
        "original_url": "https://cdn.example.com/posts/squat-clinic.jpg",
        "optimized_url": null,
        "media_type": "picture",
        "thumbnail_url": null,
        "file_size_bytes": 245120,
        "order_index": 0,
        "processing_status": "completed",
        "created_at": "2026-11-12T08:00:00Z"
      }
    ],
    "created_at": "2026-11-12T08:00:00Z",
    "updated_at": "2026-11-12T08:00:00Z"
  },
  "source_post_unavailable": false,
  "reposts_count": 0,
  "published_at": "2026-11-12T12:15:00Z",
  "media_count": 0,
  "media_attachments": [],
  "is_following_gym": false,
  "is_following_author": false,
  "is_connected_gym": false,
  "created_at": "2026-11-12T12:15:00Z",
  "updated_at": "2026-11-12T12:15:00Z",
  "target": "profile"
}
```

#### Request Payload Example B: Share on Story via `/api/v1/posts/repost/` (`target: "story"`, `application/json`)

```json
{
  "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
  "target": "story",
  "privacy": "public",
  "caption": "Check out today's squat clinic!",
  "background_color": "#121212",
  "lifetime_hours": 24
}
```

#### Response JSON (`201 Created` — Share on Story)

```json
{
  "id": "c1d2e3f4-6789-4abc-8def-112233445566",
  "owner_type": "gym",
  "user_id": "8e44c210-7766-4321-8899-aabbccddeeff",
  "user_name": "Coach Sam",
  "user_avatar_url": "https://cdn.example.com/avatars/sam.jpg",
  "gym_id": "7b21a900-8899-4111-9222-334455667788",
  "gym_name": "Iron Peak Gym",
  "gym_avatar_url": "https://cdn.example.com/gyms/iron-peak.png",
  "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_post": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "owner_type": "gym",
    "gym_id": "7b21a900-8899-4111-9222-334455667788",
    "gym_name": "Iron Peak Gym",
    "author_user_id": "8e44c210-7766-4321-8899-aabbccddeeff",
    "author_name": "Coach Sam",
    "content_text": "Squat clinic starts at 9 AM.",
    "privacy": "public",
    "is_repost": false,
    "source_post_id": null,
    "published_at": "2026-11-12T08:00:00Z"
  },
  "media_url": "https://cdn.example.com/posts/squat-clinic.jpg",
  "original_url": "https://cdn.example.com/posts/squat-clinic.jpg",
  "optimized_url": null,
  "thumbnail_url": null,
  "media_type": "picture",
  "processing_status": "completed",
  "file_size_bytes": 245120,
  "width": null,
  "height": null,
  "duration_seconds": null,
  "caption": "Check out today's squat clinic!",
  "background_color": "#121212",
  "lifetime_hours": 24,
  "lifetime_label": "24 hours",
  "privacy": "public",
  "published_at": "2026-11-12T12:20:00Z",
  "expires_at": "2026-11-13T12:20:00Z",
  "is_expired": false,
  "is_archived": false,
  "views_count": 0,
  "has_viewed": false,
  "created_at": "2026-11-12T12:20:00Z",
  "updated_at": "2026-11-12T12:20:00Z",
  "target": "story"
}
```

#### Error Example (`400 Bad Request` — Invalid Privacy for Public User)

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Invalid input.",
  "details": {
    "privacy": [
      "Public users can only choose public, followers, or private privacy."
    ]
  }
}
```

#### Error Example (`400 Bad Request` — Text-Only Post Shared to Story Without Media)

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Cannot share a text-only post to Story without uploading media or providing a media_url.",
  "details": null
}
```

---

### 5.5 List Reposts of a Post

* **Method:** `GET`
* **Endpoint:** `/api/v1/posts/{post_id}/reposts/`
* **Auth Required:** Optional (`AllowAny`)
* **Behavior:** Validates viewer permission on `{post_id}` first (`404`/`403` if hidden or nonexistent), then returns paginated profile reposts referencing `{post_id}` that are visible to the requesting viewer.

#### Path & Query Parameters

| Parameter | Location | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `post_id` | Path | string (UUID) | Yes | - | Original post UUID |
| `page` | Query | integer | No | `1` | 1-based page number |
| `page_size` | Query | integer | No | `20` | Items per page (`1` to `100`) |

#### Response JSON (`200 OK`)

Same paginated envelope as [5.1](#response-json-200-ok), with each item matching schema [4.1](#41-post--profile-repost-object-gympostlistserializer--gympostdetailserializer).

---

### 5.6 Get Post / Repost Detail

* **Method:** `GET`
* **Endpoint:** `/api/v1/posts/{post_id}/`
* **Auth Required:** Optional (`AllowAny`)

#### Path & Query Parameters

| Parameter | Location | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `post_id` | Path | string (UUID) | Yes | Post or repost UUID |

#### Response JSON (`200 OK` — Repost Whose Source Post Is Deleted or Inaccessible)

```json
{
  "id": "f9e8d7c6-5432-4100-9abc-def012345678",
  "owner_type": "user",
  "gym_id": null,
  "gym_name": null,
  "gym_avatar_url": null,
  "author_user_id": "2c8d1f10-1234-4abc-8def-001122334455",
  "author_name": "Alex Rivera",
  "author_avatar_url": "https://cdn.example.com/avatars/alex.jpg",
  "content_text": "Sharing this workout tip to my profile!",
  "privacy": "public",
  "is_repost": true,
  "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_post": null,
  "source_post_unavailable": true,
  "reposts_count": 0,
  "published_at": "2026-11-12T12:15:00Z",
  "media_count": 0,
  "media_attachments": [],
  "is_following_gym": false,
  "is_following_author": true,
  "is_connected_gym": false,
  "created_at": "2026-11-12T12:15:00Z",
  "updated_at": "2026-11-12T12:15:00Z"
}
```

---

### 5.7 Update Post / Repost

* **Method:** `PATCH`
* **Endpoint:** `/api/v1/posts/{post_id}/`
* **Auth Required:** Yes (`IsAuthenticated`)
* **Permissions:**
  * User post (`owner_type: "user"`): only `author_user_id` (or superuser).
  * Gym post (`owner_type: "gym"`): gym owner, active gym staff, or superuser.

#### Path & Query Parameters

| Parameter | Location | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `post_id` | Path | string (UUID) | Yes | Post or repost UUID |
| `gym_id` | Query | string (UUID) | No | Optional explicit gym context override for gym posts |

#### Request Body Fields (`GymPostUpdateSerializer`)

| Field | Type | Required | Constraints / Notes |
| :--- | :--- | :--- | :--- |
| `content_text` | string | No | Nullable/blankable for reposts or posts with media; cannot be cleared if post is non-repost with zero media |
| `privacy` | string | No | Validated against the target post's `owner_type` (`members_only` rejected for user posts) |
| `media_order` | array\<object\> | No | List of `{"media_id": "<uuid>", "order_index": <int >= 0>}` objects |

#### Request Payload Example (`application/json`)

```json
{
  "content_text": "Updated commentary for my followers.",
  "privacy": "private"
}
```

#### Response JSON (`200 OK`)

Returns the full updated object matching schema [4.1](#41-post--profile-repost-object-gympostlistserializer--gympostdetailserializer).

---

### 5.8 Delete Post / Repost

* **Method:** `DELETE`
* **Endpoint:** `/api/v1/posts/{post_id}/`
* **Auth Required:** Yes (`IsAuthenticated`)
* **Permissions:** Same as [5.7](#57-update-post--repost). Soft-deletes the post/repost; if deleting a profile repost, atomically decrements `source_post.reposts_count`.

#### Path & Query Parameters

| Parameter | Location | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `post_id` | Path | string (UUID) | Yes | Post or repost UUID |
| `gym_id` | Query | string (UUID) | No | Optional explicit gym context override for gym posts |

#### Response JSON (`200 OK`)

```json
{
  "message": "Post deleted successfully."
}
```

---

### 5.9 Upload Custom Video Thumbnail

* **Method:** `PATCH`
* **Endpoint:** `/api/v1/posts/{post_id}/media/{media_id}/thumbnail/`
* **Auth Required:** Yes (`IsAuthenticated`)
* **Content-Type:** `multipart/form-data`
* **Permissions:** Same as [5.7](#57-update-post--repost). Target `media_id` must have `media_type: "video"`.

#### Path, Query & Form Fields

| Field | Location | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `post_id` | Path | string (UUID) | Yes | Post UUID |
| `media_id` | Path | string (UUID) | Yes | Video media attachment UUID |
| `gym_id` | Query | string (UUID) | No | Optional explicit gym context override for gym posts |
| `thumbnail_image` | Form (File) | file (binary) | Yes (`file` key also accepted) | `.jpg`, `.jpeg`, `.png`, or `.webp` image, max 10 MB |

#### Response JSON (`200 OK`)

Returns the updated media attachment object matching schema [4.3](#43-post-media-attachment-object-gympostmediaserializer):

```json
{
  "id": "cc33dd44-ee55-4666-8777-889900112233",
  "post_id": "d4e5f6a7-1122-4334-9556-778899aabbcc",
  "media_url": "https://cdn.example.com/posts/workout.mp4",
  "original_url": "https://cdn.example.com/posts/workout.mp4",
  "optimized_url": "https://cdn.example.com/posts/workout_opt.mp4",
  "media_type": "video",
  "thumbnail_url": "https://cdn.example.com/posts/thumbnails/custom-thumb.jpg",
  "file_size_bytes": 15480210,
  "order_index": 0,
  "processing_status": "completed",
  "created_at": "2026-11-12T12:00:00Z"
}
```

---

## 6. Visibility, Blocklist & Source Post Behavior

| Rule | Description |
| :--- | :--- |
| **Own Previous Posts** | Users and gyms can repost their own accessible posts (`profile` or `story`) as well as posts from other users/gyms |
| **Repost Chains** | Reposting another repost is allowed; when shared to Story (`target: "story"`), media is inherited from the immediate source post or its accessible root post if the intermediate repost had no direct media |
| **Deleted or Restricted Source Post** | If `source_post` is later deleted, made private, restricted by follow/member privacy, or belongs to a blocked/18+ restricted entity, the outer repost remains visible (according to the reposter's privacy) with `source_post: null` and `source_post_unavailable: true` |
| **Block Enforcement** | Bidirectional user blocks (`UserBlock`), gym blocks (`GymBlock`), and `is_18_plus` restrictions are enforced on feeds, post detail, repost creation, and embedded `source_post` serialization |
| **Counter Semantics** | `reposts_count` increments by `1` on every `POST .../repost/` (`target: "profile"` or `target: "story"`) and decrements when a profile repost is deleted |
