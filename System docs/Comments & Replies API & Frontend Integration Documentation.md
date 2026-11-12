# Comments & Replies API Frontend Integration Documentation

## 1. General Configuration

* **Base URLs:**
  * Post-scoped Comments & Replies: `/api/v1/posts/{post_id}/comments/`
  * Standalone Comments & Replies: `/api/v1/comments/`
* **Authentication:** JWT Bearer Token (`Authorization: Bearer <token>`)
* **Accepted Content Types:**
  * `application/json` (for reads, text-only comments, URL-backed `comment_photo` / `comment_video` / `comment_gif`, updates, and deletes)
  * `multipart/form-data` (for direct file uploads of `comment_photo`, `comment_video`, or `comment_gif`)
* **Standard Request Headers:**
  * `Authorization: Bearer <token>` — Required for `POST`, `PATCH`, and `DELETE`; optional for `GET` endpoints (determines personalized visibility, blocklists, and own deactivated content).
  * `X-Gym-Context: <gym_uuid>` — Optional fallback header to act as a gym when not embedded in JWT claims.
  * `Content-Type`: `application/json` or `multipart/form-data`.

### 1.1 Actor Context & Server-Derived Fields

| Context | JWT / Header / Param State | Resolved `owner_type` | `user_id` | `gym_id` | Permission Rule |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Personal User** | Default (`context_type: "personal"` or omitted, no `gym_id`) | `"user"` | Authenticated actor UUID | `null` | Any active authenticated user (subject to post visibility, blocklists, and age restrictions) |
| **Gym Page** | `context_type: "gym"` in JWT, `X-Gym-Context: <gym_uuid>`, or `gym_id` query/body param on `POST` | `"gym"` | Authenticated actor UUID | Target gym UUID | Active gym owner, superuser, or active gym staff with `posts:manage` permission |

Read-only server-derived fields (`id`, `user_id`, `owner_type`, `gym_id`, `gym_name`, `gym_avatar_url`, `author_name`, `author_avatar_url`, `root_comment_id`, `depth`, `reply_to_user_id`, `reply_to_user_name`, `media_type`, `media_url`, `thumbnail_url`, `processing_status`, `width`, `height`, `file_size_bytes`, `replies_count`, `total_replies_count`, `has_more_replies`, `replies`, `is_edited`, `edited_at`, `created_at`, `updated_at`) MUST NOT be modified directly by clients.

---

## 2. Global Error Envelope & HTTP Status Codes

### 2.1 Error Response JSON Format

```json
{
  "code": "VALIDATION_ERROR",
  "message": "A comment must contain either comment_text or a media attachment (comment_photo, comment_video, or comment_gif).",
  "details": {
    "comment_text": [
      "This field may not be blank."
    ]
  }
}
```

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `code` | string | No | Machine-readable error code (`VALIDATION_ERROR`, `UNAUTHORIZED_CONTEXT`, `RESOURCE_CONFLICT`, `PERMISSION_DENIED`, `RESOURCE_NOT_FOUND`, `DOMAIN_ERROR`) |
| `message` | string | No | Human-readable error summary |
| `details` | object \| array \| null | Yes | Field-level validation errors or extra context; `null` when unavailable |

### 2.2 HTTP Status Codes

| Status Code | Error Code | Cause |
| :--- | :--- | :--- |
| `400 Bad Request` | `VALIDATION_ERROR` | Empty comment, more than one media type, invalid file format/size, invalid URL, `comment_text` > `5000` chars, invalid UUID, depth > `10`, mismatched URL vs body `source_post_id` / `source_comment_id`, or deactivated gym |
| `401 Unauthorized` | `UNAUTHORIZED_CONTEXT` | Missing, expired, or invalid Bearer token on `POST`, `PATCH`, or `DELETE` |
| `403 Forbidden` | `PERMISSION_DENIED` | Insufficient `posts:manage` permission for gym action, non-owner edit/delete attempt, deactivated/deleted actor account, mutual user block, gym block, private/restricted post, or 18+ age restriction |
| `404 Not Found` | `RESOURCE_NOT_FOUND` | Post, parent comment, target comment, or gym does not exist, is deleted/unpublished, or belongs to a cross-tenant gym context |
| `405 Method Not Allowed` | `METHOD_NOT_ALLOWED` | Unsupported HTTP method on the endpoint |

---

## 3. Enums, Sorting & Validation Rules

### 3.1 `owner_type`

| Value | Description |
| :--- | :--- |
| `"user"` | Personal user comment/reply (`gym_id`, `gym_name`, `gym_avatar_url` are `null`) |
| `"gym"` | Gym page comment/reply (`gym_id`, `gym_name`, `gym_avatar_url` are populated) |

### 3.2 `media_type` & `processing_status`

| Field | Allowed Values | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `media_type` (response) | `"photo"`, `"video"`, `"gif"` | Yes | Attached media kind, or `null` for text-only comments |
| `media_type` (query filter) | `"photo"`, `"video"`, `"gif"`, `"text"` | Yes | Filters listing endpoints (`"text"` matches `media_type` = `null`) |
| `processing_status` | `"pending"`, `"processing"`, `"completed"`, `"failed"` | No | Media optimization lifecycle status (`"completed"` immediately for text-only, URL-backed media, and uploaded GIFs) |

### 3.3 `sort` and `reply_sort`

| Parameter | Allowed Values | Default | Ordering Rule |
| :--- | :--- | :--- | :--- |
| `sort` (Post comments) | `"newest"`, `"oldest"`, `"most_replied"` | `"newest"` | `"newest"`: `-created_at, -id`; `"oldest"`: `created_at, id`; `"most_replied"`: `-replies_count, -created_at, -id` |
| `sort` (Comment replies) | `"newest"`, `"oldest"`, `"most_replied"` | `"oldest"` | Same ordering keys as above |
| `reply_sort` (Nested previews) | `"oldest"`, `"newest"`, `"most_replied"` | `"oldest"` | Ordering for embedded `replies` previews (`"most_replied"` uses `-replies_count, created_at, id`) |

### 3.4 Content, Nesting & Media Constraints

| Rule | Limit / Accepted Values |
| :--- | :--- |
| **Content Requirement** | Must include non-blank `comment_text` and/or one media attachment (`comment_photo`, `comment_video`, or `comment_gif`). |
| **Single Media Rule** | Maximum **1** media attachment per comment/reply (`comment_photo`, `comment_video`, and `comment_gif` are mutually exclusive). |
| **Text Length** | `comment_text`: max `5000` characters (trimmed; null bytes disallowed). |
| **Nesting Depth** | `depth`: `0` for top-level comments on a post; `1` to `10` for nested replies. Replying to a `depth = 10` comment returns `400 Bad Request`. |
| **Media URL Length** | `comment_photo`, `comment_video`, `comment_gif` URL strings: valid `http(s)://...` or `/media/...` path, max `1000` characters. Disallowed extensions: `.exe`, `.sh`, `.bat`, `.cmd`, `.php`, `.js`, `.html`, `.htm`, `.svg`. |
| **Photo Upload (`comment_photo`, aliases `photo`, `image`)** | Formats: `.jpg`, `.jpeg`, `.png`, `.webp` (URLs also allow `.avif`, `.bmp`, `.heic`, `.tiff`, `.jfif`). Max file size: `10 MB`. |
| **Video Upload (`comment_video`, alias `video`)** | Formats: `.mp4`, `.mov` (URLs also allow `.webm`). Max file size: `200 MB`. |
| **GIF Upload (`comment_gif`, alias `gif`)** | Format: `.gif` (`image/gif`). Max file size: `10 MB`. Animated frames are preserved. |

---

## 4. Schema Models (All Fields)

### 4.1 Comment / Reply Object (`PostCommentSerializer`)

Returned by comment list, reply list, comment detail, create, reply, and update endpoints. Each embedded item inside `replies` uses the exact same 34-field structure recursively up to `reply_depth`.

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | string (UUID) | No | Unique comment ID |
| `user_id` | string (UUID) | No | Comment author user ID |
| `owner_type` | string (`"user"` \| `"gym"`) | No | Actor context (`"user"` or `"gym"`) |
| `gym_id` | string (UUID) | Yes | Acting gym ID (`null` when `owner_type: "user"`) |
| `gym_name` | string | Yes | Acting gym name (`null` when `owner_type: "user"`) |
| `gym_avatar_url` | string (URI) | Yes | Acting gym profile picture URI (`null` when `owner_type: "user"` or unset) |
| `author_name` | string | No | Author full name (fallback: email, then `"Unknown"`) |
| `author_avatar_url` | string (URI) | Yes | Author profile avatar URI (`null` if unset) |
| `source_post_id` | string (UUID) | No | Target post ID |
| `source_comment_id` | string (UUID) | Yes | Immediate parent comment ID (`null` for top-level comments) |
| `root_comment_id` | string (UUID) | Yes | Top-level root thread comment ID (`null` for top-level comments) |
| `depth` | integer | No | Nesting level (`0` = top-level comment, `1..10` = nested replies) |
| `reply_to_user_id` | string (UUID) | Yes | Parent comment author user ID (`null` for top-level comments) |
| `reply_to_user_name` | string | Yes | Display name of `reply_to_user_id` (`null` for top-level comments) |
| `comment_text` | string | Yes | Comment text body (`null` when media-only) |
| `comment_photo` | string (URI) | Yes | Photo URI if attached (`null` otherwise) |
| `comment_video` | string (URI) | Yes | Video URI if attached (`null` otherwise) |
| `comment_gif` | string (URI) | Yes | GIF URI if attached (`null` otherwise) |
| `media_type` | string (`"photo"` \| `"video"` \| `"gif"`) | Yes | Active media attachment type (`null` for text-only) |
| `media_url` | string (URI) | Yes | Best resolved media URI (optimized URI if ready, else original/active URI) |
| `thumbnail_url` | string (URI) | Yes | Thumbnail or video poster URI (`null` when no media) |
| `processing_status` | string | No | `"pending"`, `"processing"`, `"completed"`, or `"failed"` |
| `width` | integer | Yes | Media width in pixels (`null` if unavailable) |
| `height` | integer | Yes | Media height in pixels (`null` if unavailable) |
| `file_size_bytes` | integer | No | Uploaded file size in bytes (`0` for text-only or external URLs) |
| `duration_seconds` | number (float) | Yes | Optional video duration in seconds (`null` if unset) |
| `replies_count` | integer | No | Direct child replies count |
| `total_replies_count` | integer | No | Total descendant replies count across all nested depths under this comment |
| `has_more_replies` | boolean | No | `true` if additional visible replies exist beyond the embedded `replies` slice |
| `replies` | array\<object\> | No | Nested child comment objects (same schema, recursive up to `reply_depth` and `replies_limit`) |
| `is_edited` | boolean | No | `true` if modified via `PATCH` |
| `edited_at` | string (ISO 8601) | Yes | Last edit timestamp (`null` if never edited) |
| `created_at` | string (ISO 8601) | No | Creation timestamp |
| `updated_at` | string (ISO 8601) | No | Last update timestamp |

### 4.2 Post Counter Field (On Post & Source Post Schemas)

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `comments_count` | integer | No | Included on `GymPostListSerializer`, `GymPostDetailSerializer`, and `SourcePostSummarySerializer`; reflects total comments + nested replies on the post |

### 4.3 Standard Paginated Envelope (`StandardResultsSetPagination`)

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `count` | integer | No | Total matching items across all pages |
| `total_pages` | integer | No | Total number of pages |
| `current_page` | integer | No | Current 1-based page number |
| `next` | string (URI) | Yes | Next page full URL or `null` |
| `previous` | string (URI) | Yes | Previous page full URL or `null` |
| `results` | array\<object\> | No | Array of Comment / Reply objects ([4.1](#41-comment--reply-object-postcommentserializer)) |

### 4.4 Delete Comment Response Object

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `message` | string | No | `"Comment deleted successfully."` |
| `deleted_count` | integer | No | Total deleted rows (`1` + all nested descendant replies) |

---

## 5. Complete API Endpoints

### 5.1 List Paginated Post Comments (with Nested Replies)

* **Method:** `GET`
* **Endpoints:**
  * `/api/v1/posts/{post_id}/comments/`
  * `/api/v1/comments/?source_post_id={post_id}`
  * `/api/v1/comments/?source_comment_id={comment_id}` (returns paginated direct replies for `source_comment_id`)
* **Auth Required:** Optional (`AllowAny`)

#### Query Parameters (`PostCommentFilterSerializer`)

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `source_post_id` | string (UUID) | Conditional | `null` | Target post UUID (required on `/api/v1/comments/` unless `source_comment_id` is passed) |
| `source_comment_id` | string (UUID) | Conditional | `null` | Parent comment UUID to list direct replies via `/api/v1/comments/` |
| `sort` | string | No | `"newest"` (posts) / `"oldest"` (replies) | Top-level ordering: `"newest"`, `"oldest"`, `"most_replied"` |
| `reply_sort` | string | No | `"oldest"` | Ordering for embedded `replies`: `"oldest"`, `"newest"`, `"most_replied"` |
| `media_type` | string | No | `null` | Filter comments by `"photo"`, `"video"`, `"gif"`, or `"text"` |
| `include_replies` | boolean | No | `true` | Embed nested reply previews inside each returned comment |
| `replies_limit` | integer | No | `2` | Maximum embedded replies per parent node (`0` to `10`) |
| `reply_depth` | integer | No | `2` | Maximum nested reply levels embedded inline (`0` to `5`) |
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
      "id": "11111111-1111-4111-8111-111111111111",
      "user_id": "2c8d1f10-1234-4abc-8def-001122334455",
      "owner_type": "user",
      "gym_id": null,
      "gym_name": null,
      "gym_avatar_url": null,
      "author_name": "Alex Rivera",
      "author_avatar_url": "https://cdn.example.com/avatars/alex.jpg",
      "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
      "source_comment_id": null,
      "root_comment_id": null,
      "depth": 0,
      "reply_to_user_id": null,
      "reply_to_user_name": null,
      "comment_text": "Solid deadlift form!",
      "comment_photo": "https://api.example.com/media/posts/comments/photos/optimized/form.webp",
      "comment_video": null,
      "comment_gif": null,
      "media_type": "photo",
      "media_url": "https://api.example.com/media/posts/comments/photos/optimized/form.webp",
      "thumbnail_url": "https://api.example.com/media/posts/comments/photos/thumbnails/form_thumb.webp",
      "processing_status": "completed",
      "width": 1080,
      "height": 720,
      "file_size_bytes": 245120,
      "duration_seconds": null,
      "replies_count": 1,
      "total_replies_count": 2,
      "has_more_replies": false,
      "replies": [
        {
          "id": "22222222-2222-4222-8222-222222222222",
          "user_id": "8e44c210-7766-4321-8899-aabbccddeeff",
          "owner_type": "gym",
          "gym_id": "7b21a900-8899-4111-9222-334455667788",
          "gym_name": "Iron Peak Gym",
          "gym_avatar_url": "https://cdn.example.com/gyms/iron-peak.png",
          "author_name": "Coach Sam",
          "author_avatar_url": "https://cdn.example.com/avatars/sam.jpg",
          "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
          "source_comment_id": "11111111-1111-4111-8111-111111111111",
          "root_comment_id": "11111111-1111-4111-8111-111111111111",
          "depth": 1,
          "reply_to_user_id": "2c8d1f10-1234-4abc-8def-001122334455",
          "reply_to_user_name": "Alex Rivera",
          "comment_text": "Thanks! Keep that brace tight.",
          "comment_photo": null,
          "comment_video": null,
          "comment_gif": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
          "media_type": "gif",
          "media_url": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
          "thumbnail_url": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
          "processing_status": "completed",
          "width": null,
          "height": null,
          "file_size_bytes": 0,
          "duration_seconds": null,
          "replies_count": 1,
          "total_replies_count": 1,
          "has_more_replies": false,
          "replies": [
            {
              "id": "33333333-3333-4333-8333-333333333333",
              "user_id": "2c8d1f10-1234-4abc-8def-001122334455",
              "owner_type": "user",
              "gym_id": null,
              "gym_name": null,
              "gym_avatar_url": null,
              "author_name": "Alex Rivera",
              "author_avatar_url": "https://cdn.example.com/avatars/alex.jpg",
              "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
              "source_comment_id": "22222222-2222-4222-8222-222222222222",
              "root_comment_id": "11111111-1111-4111-8111-111111111111",
              "depth": 2,
              "reply_to_user_id": "8e44c210-7766-4321-8899-aabbccddeeff",
              "reply_to_user_name": "Coach Sam",
              "comment_text": "Will do, see you next session!",
              "comment_photo": null,
              "comment_video": null,
              "comment_gif": null,
              "media_type": null,
              "media_url": null,
              "thumbnail_url": null,
              "processing_status": "completed",
              "width": null,
              "height": null,
              "file_size_bytes": 0,
              "duration_seconds": null,
              "replies_count": 0,
              "total_replies_count": 0,
              "has_more_replies": false,
              "replies": [],
              "is_edited": false,
              "edited_at": null,
              "created_at": "2026-11-12T10:15:00Z",
              "updated_at": "2026-11-12T10:15:00Z"
            }
          ],
          "is_edited": false,
          "edited_at": null,
          "created_at": "2026-11-12T10:05:00Z",
          "updated_at": "2026-11-12T10:05:00Z"
        }
      ],
      "is_edited": false,
      "edited_at": null,
      "created_at": "2026-11-12T10:00:00Z",
      "updated_at": "2026-11-12T10:00:00Z"
    }
  ]
}
```

---

### 5.2 Create Comment or Reply on a Post

* **Method:** `POST`
* **Endpoints:**
  * `/api/v1/posts/{post_id}/comments/`
  * `/api/v1/comments/`
* **Auth Required:** Yes (`IsAuthenticated`)

#### Optional Query / Body Context Parameter

| Parameter | Location | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `gym_id` | Query or Body | string (UUID) | No | Optional explicit gym UUID to comment/reply as a Gym (requires active `posts:manage` role or gym ownership) |

#### Request Body Fields (`PostCommentCreateSerializer`)

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `source_post_id` | string (UUID) | Conditional | Target post UUID; required on `/api/v1/comments/` unless `source_comment_id` is supplied; optional on `/api/v1/posts/{post_id}/comments/` (must match URL `post_id` if sent) |
| `source_comment_id` | string (UUID) | No | Optional parent comment UUID when creating a reply |
| `comment_text` | string | Conditional | Optional text (`1`–`5000` non-whitespace chars; required if no media is attached) |
| `comment_photo` | File \| string (URI) | Conditional | Optional photo upload (`.jpg`, `.jpeg`, `.png`, `.webp`, max `10 MB`) or URI (`multipart` aliases: `photo`, `image`) |
| `comment_video` | File \| string (URI) | Conditional | Optional video upload (`.mp4`, `.mov`, max `200 MB`) or URI (`multipart` alias: `video`) |
| `comment_gif` | File \| string (URI) | Conditional | Optional GIF upload (`.gif`, max `10 MB`) or URI (`multipart` alias: `gif`) |
| `duration_seconds` | number (float) | No | Optional non-negative video playback duration in seconds |

#### Request JSON Payload (Top-Level Comment)

```json
{
  "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
  "comment_text": "Clean technique on the final set!",
  "comment_photo": "https://cdn.example.com/uploads/deadlift-snapshot.jpg",
  "comment_video": null,
  "comment_gif": null,
  "duration_seconds": null
}
```

#### Request JSON Payload (Nested Reply with Video URL)

```json
{
  "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_comment_id": "11111111-1111-4111-8111-111111111111",
  "comment_text": "Check this slow-motion angle:",
  "comment_video": "https://cdn.example.com/uploads/angle.mp4",
  "duration_seconds": 14.5
}
```

#### Response JSON (`201 Created`)

```json
{
  "id": "44444444-4444-4444-8444-444444444444",
  "user_id": "2c8d1f10-1234-4abc-8def-001122334455",
  "owner_type": "user",
  "gym_id": null,
  "gym_name": null,
  "gym_avatar_url": null,
  "author_name": "Alex Rivera",
  "author_avatar_url": "https://cdn.example.com/avatars/alex.jpg",
  "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_comment_id": null,
  "root_comment_id": null,
  "depth": 0,
  "reply_to_user_id": null,
  "reply_to_user_name": null,
  "comment_text": "Clean technique on the final set!",
  "comment_photo": "https://cdn.example.com/uploads/deadlift-snapshot.jpg",
  "comment_video": null,
  "comment_gif": null,
  "media_type": "photo",
  "media_url": "https://cdn.example.com/uploads/deadlift-snapshot.jpg",
  "thumbnail_url": "https://cdn.example.com/uploads/deadlift-snapshot.jpg",
  "processing_status": "completed",
  "width": null,
  "height": null,
  "file_size_bytes": 0,
  "duration_seconds": null,
  "replies_count": 0,
  "total_replies_count": 0,
  "has_more_replies": false,
  "replies": [],
  "is_edited": false,
  "edited_at": null,
  "created_at": "2026-11-12T11:00:00Z",
  "updated_at": "2026-11-12T11:00:00Z"
}
```

---

### 5.3 List Paginated Replies to a Comment

* **Method:** `GET`
* **Endpoints:**
  * `/api/v1/posts/{post_id}/comments/{comment_id}/replies/`
  * `/api/v1/comments/{comment_id}/replies/`
* **Auth Required:** Optional (`AllowAny`)

#### Query Parameters (`PostCommentFilterSerializer`)

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `sort` | string | No | `"oldest"` | Direct reply ordering: `"oldest"`, `"newest"`, `"most_replied"` |
| `reply_sort` | string | No | `"oldest"` | Ordering for embedded grandchild `replies`: `"oldest"`, `"newest"`, `"most_replied"` |
| `media_type` | string | No | `null` | Filter replies by `"photo"`, `"video"`, `"gif"`, or `"text"` |
| `include_replies` | boolean | No | `true` | Embed nested grandchild replies |
| `replies_limit` | integer | No | `2` | Maximum embedded child replies per node (`0` to `10`) |
| `reply_depth` | integer | No | `2` | Maximum nested grandchild levels embedded inline (`0` to `5`) |
| `page` | integer | No | `1` | 1-based page number (min `1`) |
| `page_size` | integer | No | `20` | Items per page (`1` to `100`) |

#### Response JSON (`200 OK`)

```json
{
  "count": 1,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "22222222-2222-4222-8222-222222222222",
      "user_id": "8e44c210-7766-4321-8899-aabbccddeeff",
      "owner_type": "gym",
      "gym_id": "7b21a900-8899-4111-9222-334455667788",
      "gym_name": "Iron Peak Gym",
      "gym_avatar_url": "https://cdn.example.com/gyms/iron-peak.png",
      "author_name": "Coach Sam",
      "author_avatar_url": "https://cdn.example.com/avatars/sam.jpg",
      "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
      "source_comment_id": "11111111-1111-4111-8111-111111111111",
      "root_comment_id": "11111111-1111-4111-8111-111111111111",
      "depth": 1,
      "reply_to_user_id": "2c8d1f10-1234-4abc-8def-001122334455",
      "reply_to_user_name": "Alex Rivera",
      "comment_text": "Thanks! Keep that brace tight.",
      "comment_photo": null,
      "comment_video": null,
      "comment_gif": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
      "media_type": "gif",
      "media_url": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
      "thumbnail_url": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
      "processing_status": "completed",
      "width": null,
      "height": null,
      "file_size_bytes": 0,
      "duration_seconds": null,
      "replies_count": 1,
      "total_replies_count": 1,
      "has_more_replies": false,
      "replies": [],
      "is_edited": false,
      "edited_at": null,
      "created_at": "2026-11-12T10:05:00Z",
      "updated_at": "2026-11-12T10:05:00Z"
    }
  ]
}
```

---

### 5.4 Reply Directly to a Comment

* **Method:** `POST`
* **Endpoints:**
  * `/api/v1/posts/{post_id}/comments/{comment_id}/replies/`
  * `/api/v1/comments/{comment_id}/replies/`
* **Auth Required:** Yes (`IsAuthenticated`)

#### Optional Query / Body Context Parameter

| Parameter | Location | Type | Required | Description |
| :--- | :--- | :--- | :--- | :--- |
| `gym_id` | Query or Body | string (UUID) | No | Optional explicit gym UUID to reply as a Gym |

#### Request Body Fields (`PostCommentCreateSerializer`)

| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `source_post_id` | string (UUID) | No | Optional; if sent, must match URL `post_id` and parent comment's post |
| `source_comment_id` | string (UUID) | No | Optional; if sent, must match URL `comment_id` |
| `comment_text` | string | Conditional | Optional text (`1`–`5000` chars; required if no media is attached) |
| `comment_photo` | File \| string (URI) | Conditional | Optional photo upload or URI (`multipart` aliases: `photo`, `image`) |
| `comment_video` | File \| string (URI) | Conditional | Optional video upload or URI (`multipart` alias: `video`) |
| `comment_gif` | File \| string (URI) | Conditional | Optional GIF upload or URI (`multipart` alias: `gif`) |
| `duration_seconds` | number (float) | No | Optional non-negative video duration in seconds |

#### Request JSON Payload

```json
{
  "comment_text": "Appreciated, coach!",
  "comment_gif": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif"
}
```

#### Response JSON (`201 Created`)

```json
{
  "id": "55555555-5555-4555-8555-555555555555",
  "user_id": "2c8d1f10-1234-4abc-8def-001122334455",
  "owner_type": "user",
  "gym_id": null,
  "gym_name": null,
  "gym_avatar_url": null,
  "author_name": "Alex Rivera",
  "author_avatar_url": "https://cdn.example.com/avatars/alex.jpg",
  "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_comment_id": "22222222-2222-4222-8222-222222222222",
  "root_comment_id": "11111111-1111-4111-8111-111111111111",
  "depth": 2,
  "reply_to_user_id": "8e44c210-7766-4321-8899-aabbccddeeff",
  "reply_to_user_name": "Coach Sam",
  "comment_text": "Appreciated, coach!",
  "comment_photo": null,
  "comment_video": null,
  "comment_gif": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
  "media_type": "gif",
  "media_url": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
  "thumbnail_url": "https://media.giphy.com/media/l0MYt5jPR6QX5pnqM/giphy.gif",
  "processing_status": "completed",
  "width": null,
  "height": null,
  "file_size_bytes": 0,
  "duration_seconds": null,
  "replies_count": 0,
  "total_replies_count": 0,
  "has_more_replies": false,
  "replies": [],
  "is_edited": false,
  "edited_at": null,
  "created_at": "2026-11-12T11:05:00Z",
  "updated_at": "2026-11-12T11:05:00Z"
}
```

---

### 5.5 Retrieve Single Comment or Reply

* **Method:** `GET`
* **Endpoints:**
  * `/api/v1/posts/{post_id}/comments/{comment_id}/`
  * `/api/v1/comments/{comment_id}/`
* **Auth Required:** Optional (`AllowAny`)

#### Query Parameters

| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `include_replies` | boolean | No | `true` | Embed nested reply previews inside `replies` |
| `replies_limit` | integer | No | `2` | Maximum embedded replies per parent node (`0` to `10`) |
| `reply_depth` | integer | No | `2` | Maximum nested reply levels embedded inline (`0` to `5`) |
| `reply_sort` | string | No | `"oldest"` | Ordering for embedded `replies`: `"oldest"`, `"newest"`, `"most_replied"` |

#### Response JSON (`200 OK`)

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "user_id": "2c8d1f10-1234-4abc-8def-001122334455",
  "owner_type": "user",
  "gym_id": null,
  "gym_name": null,
  "gym_avatar_url": null,
  "author_name": "Alex Rivera",
  "author_avatar_url": "https://cdn.example.com/avatars/alex.jpg",
  "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_comment_id": null,
  "root_comment_id": null,
  "depth": 0,
  "reply_to_user_id": null,
  "reply_to_user_name": null,
  "comment_text": "Solid deadlift form!",
  "comment_photo": "https://api.example.com/media/posts/comments/photos/optimized/form.webp",
  "comment_video": null,
  "comment_gif": null,
  "media_type": "photo",
  "media_url": "https://api.example.com/media/posts/comments/photos/optimized/form.webp",
  "thumbnail_url": "https://api.example.com/media/posts/comments/photos/thumbnails/form_thumb.webp",
  "processing_status": "completed",
  "width": 1080,
  "height": 720,
  "file_size_bytes": 245120,
  "duration_seconds": null,
  "replies_count": 1,
  "total_replies_count": 2,
  "has_more_replies": false,
  "replies": [],
  "is_edited": false,
  "edited_at": null,
  "created_at": "2026-11-12T10:00:00Z",
  "updated_at": "2026-11-12T10:00:00Z"
}
```

---

### 5.6 Update Comment or Reply

* **Method:** `PATCH`
* **Endpoints:**
  * `/api/v1/posts/{post_id}/comments/{comment_id}/`
  * `/api/v1/comments/{comment_id}/`
* **Auth Required:** Yes (`IsAuthenticated`)
* **Permission Rule:** Comment author (or active gym owner/superuser/staff with `posts:manage` for gym-authored comments). Omitted media fields preserve the existing attachment; clearing all content and media returns `400 Bad Request`.

#### Request Body Fields (`PostCommentUpdateSerializer`)

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `comment_text` | string \| null | No | Omitted | Updated text (`null` or blank clears text if media remains) |
| `comment_photo` | File \| string (URI) \| null | No | Omitted | New photo upload/URL (`multipart` aliases: `photo`, `image`), or `null` to clear existing photo |
| `comment_video` | File \| string (URI) \| null | No | Omitted | New video upload/URL (`multipart` alias: `video`), or `null` to clear existing video |
| `comment_gif` | File \| string (URI) \| null | No | Omitted | New GIF upload/URL (`multipart` alias: `gif`), or `null` to clear existing GIF |
| `remove_media` | boolean | No | `false` | When `true`, removes the active media attachment (`comment_text` must remain non-empty) |
| `duration_seconds` | number (float) \| null | No | Omitted | Updated non-negative video duration in seconds |

#### Request JSON Payload (Update Text Only)

```json
{
  "comment_text": "Solid deadlift form — updated cue!"
}
```

#### Request JSON Payload (Remove Media)

```json
{
  "comment_text": "Keeping text only after removing attachment.",
  "remove_media": true
}
```

#### Response JSON (`200 OK`)

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "user_id": "2c8d1f10-1234-4abc-8def-001122334455",
  "owner_type": "user",
  "gym_id": null,
  "gym_name": null,
  "gym_avatar_url": null,
  "author_name": "Alex Rivera",
  "author_avatar_url": "https://cdn.example.com/avatars/alex.jpg",
  "source_post_id": "550e8400-e29b-41d4-a716-446655440000",
  "source_comment_id": null,
  "root_comment_id": null,
  "depth": 0,
  "reply_to_user_id": null,
  "reply_to_user_name": null,
  "comment_text": "Keeping text only after removing attachment.",
  "comment_photo": null,
  "comment_video": null,
  "comment_gif": null,
  "media_type": null,
  "media_url": null,
  "thumbnail_url": null,
  "processing_status": "completed",
  "width": null,
  "height": null,
  "file_size_bytes": 0,
  "duration_seconds": null,
  "replies_count": 1,
  "total_replies_count": 2,
  "has_more_replies": true,
  "replies": [],
  "is_edited": true,
  "edited_at": "2026-11-12T11:20:00Z",
  "created_at": "2026-11-12T10:00:00Z",
  "updated_at": "2026-11-12T11:20:00Z"
}
```

---

### 5.7 Delete Comment or Reply (Cascade Subtree)

* **Method:** `DELETE`
* **Endpoints:**
  * `/api/v1/posts/{post_id}/comments/{comment_id}/`
  * `/api/v1/comments/{comment_id}/`
* **Auth Required:** Yes (`IsAuthenticated`)
* **Permission Rule:** Allowed for the comment author, parent post author, or gym owner/superuser/staff with `posts:manage` (for gym-authored comments or comments under a gym post). Deletes the target comment and all nested descendant replies and decrements `comments_count`, `replies_count`, and `total_replies_count`.

#### Response JSON (`200 OK`)

```json
{
  "message": "Comment deleted successfully.",
  "deleted_count": 3
}
```
