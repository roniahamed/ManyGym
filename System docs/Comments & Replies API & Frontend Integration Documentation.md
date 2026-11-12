# Comments & Replies API & Frontend Integration Documentation

## 1. General Configuration

- **Base URLs:**
  - Post-scoped: `/api/v1/posts/{post_id}/comments/`
  - Top-level alias: `/api/v1/comments/`
- **Authentication:** JWT Bearer Token (`Authorization: Bearer <token>`)
- **Accepted Request Formats:**
  - `application/json` (for text comments, URL-backed photo/video/GIF comments, updates, and reads)
  - `multipart/form-data` (for direct file uploads of `comment_photo`, `comment_video`, or `comment_gif`)
- **Standard Headers:**
  - `Authorization: Bearer <token>` (Required for `POST`, `PATCH`, `DELETE`; optional for public `GET` endpoints)
  - `X-Gym-Context: <gym_uuid>` (Optional fallback gym context header when commenting/moderating as a Gym)

### 1.1 Automatic Actor Context & Read-Only Fields

| Field | Source | Behavior |
| :--- | :--- | :--- |
| `id` | Server-generated UUID | Comment primary key (`Comment id`). |
| `user_id` | Authenticated Bearer JWT | Always recorded (`User id`) regardless of whether `owner_type` is `"user"` or `"gym"`. |
| `owner_type` | Bearer JWT (`context_type`) / `X-Gym-Context` / `gym_id` | `"user"` (default) or `"gym"` (requires `posts:manage` scope on the gym). |
| `gym_id` | Resolved gym context | Populated when `owner_type` is `"gym"`; `null` otherwise. |
| `root_comment_id` | Server-derived | `null` for top-level comments; top-level ancestor UUID for all nested replies. |
| `depth` | Server-derived | `0` for top-level comments on a post; `parent.depth + 1` (up to `10`) for nested replies. |
| `reply_to_user_id` | Server-derived | `null` for top-level comments; `source_comment.user_id` for replies. |
| `replies_count` | Server-maintained | Direct child replies count. |
| `total_replies_count` | Server-maintained | Total nested descendant replies count across all depths under this comment. |

---

## 2. Media Constraints & Validation

A comment must contain **either** `comment_text` **or** a media attachment (`comment_photo`, `comment_video`, or `comment_gif`). Text and one media attachment may also be combined.

- **Single Media Attachment Rule:** At most **one** of `comment_photo`, `comment_video`, or `comment_gif` can be attached per comment.
- **Max `comment_text` Length:** `5000` characters.

| Field | Accepted Multipart File Formats | Accepted URL Formats | Max File Size | Processing Behavior |
| :--- | :--- | :--- | :--- | :--- |
| `comment_photo` (aliases: `photo`, `image`) | `.jpg`, `.jpeg`, `.png`, `.webp` | `http(s)://...` or `/media/...` | `10 MB` | Async Celery task converts uploaded photos to WebP + thumbnail. |
| `comment_video` (alias: `video`) | `.mp4`, `.mov` | `http(s)://...` or `/media/...` | `200 MB` | Async Celery task extracts poster `thumbnail_url` & optimizes H.264 MP4. |
| `comment_gif` (alias: `gif`) | `.gif` | `http(s)://...` or `/media/...` (e.g. Giphy/Tenor) | `10 MB` | Preserves `.gif` animation frames directly (not flattened to static WebP). |

---

## 3. Comment Schema (`PostCommentSerializer`)

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | string (UUID) | No | Comment ID |
| `user_id` | string (UUID) | No | Author user ID |
| `owner_type` | string (`"user"` \| `"gym"`) | No | Actor context |
| `gym_id` | string (UUID) | Yes | Acting gym ID when `owner_type: "gym"` |
| `gym_name` | string | Yes | Acting gym name |
| `gym_avatar_url` | string (URI) | Yes | Acting gym logo URI |
| `author_name` | string | No | Author display name |
| `author_avatar_url` | string (URI) | Yes | Author avatar URI |
| `source_post_id` | string (UUID) | No | Target post ID |
| `source_comment_id` | string (UUID) | Yes | Immediate parent comment ID (`null` for top-level comments) |
| `root_comment_id` | string (UUID) | Yes | Root top-level thread comment ID (`null` for top-level comments) |
| `depth` | integer | No | Nesting level (`0` = top-level, `1..10` = nested replies) |
| `reply_to_user_id` | string (UUID) | Yes | User ID being replied to |
| `reply_to_user_name` | string | Yes | Display name of user being replied to |
| `comment_text` | string | Yes | Optional comment text |
| `comment_photo` | string (URI) | Yes | Photo URI if attached |
| `comment_video` | string (URI) | Yes | Video URI if attached |
| `comment_gif` | string (URI) | Yes | GIF URI if attached |
| `media_type` | string (`"photo"` \| `"video"` \| `"gif"`) | Yes | Active media type |
| `media_url` | string (URI) | Yes | Best resolved media URI |
| `thumbnail_url` | string (URI) | Yes | Thumbnail / video poster URI |
| `processing_status` | string | No | `"pending"`, `"processing"`, `"completed"`, or `"failed"` |
| `width` | integer | Yes | Media width in pixels |
| `height` | integer | Yes | Media height in pixels |
| `file_size_bytes` | integer | No | Uploaded file size in bytes |
| `duration_seconds` | float | Yes | Optional video duration |
| `replies_count` | integer | No | Direct replies count |
| `total_replies_count` | integer | No | Total nested replies count in subtree |
| `has_more_replies` | boolean | No | `true` if additional visible replies can be loaded via the replies endpoint |
| `replies` | array\<object\> | No | Embedded nested reply objects (up to `replies_limit` and `reply_depth`) |
| `is_edited` | boolean | No | `true` if comment was updated via `PATCH` |
| `edited_at` | string (ISO 8601) | Yes | Last edit timestamp |
| `created_at` | string (ISO 8601) | No | Creation timestamp |
| `updated_at` | string (ISO 8601) | No | Last update timestamp |

---

## 4. Endpoints

### 4.1 List Paginated Post Comments (with Nested Replies)

- **Endpoint:** `GET /api/v1/posts/{post_id}/comments/` (alias: `GET /api/v1/comments/?source_post_id={post_id}`)
- **Auth:** Optional (`AllowAny`, enforces post privacy, blocklists, and gym age restrictions)
- **Query Parameters:**
  - `page` (int, default `1`), `page_size` (int, default `20`, max `100`)
  - `sort`: `"newest"` (default), `"oldest"`, `"most_replied"`
  - `media_type`: `"photo"`, `"video"`, `"gif"`, `"text"`
  - `include_replies`: `true` (default) or `false`
  - `replies_limit`: int (`0`-`10`, default `2`) — max preview replies per node
  - `reply_depth`: int (`0`-`5`, default `2`) — max nesting depth to embed inline
  - `reply_sort`: `"oldest"` (default), `"newest"`, `"most_replied"`
- **Response (`200 OK`):** Standard paginated envelope (`count`, `total_pages`, `current_page`, `next`, `previous`, `results`).

### 4.2 Create Comment or Reply on a Post

- **Endpoints:**
  - `POST /api/v1/posts/{post_id}/comments/`
  - `POST /api/v1/comments/` (requires `source_post_id` or `source_comment_id` in body)
- **Auth:** Required (`IsAuthenticated`)
- **Body Fields:** `source_post_id` (optional if in URL), `source_comment_id` (optional, for replying to a comment), `comment_text`, `comment_photo`, `comment_video`, `comment_gif`, `duration_seconds`.
- **Response (`201 Created`):** `PostCommentSerializer` object; atomically increments `GymPost.comments_count` (and ancestor reply counters if `source_comment_id` is set).

### 4.3 List Paginated Replies to Any Comment

- **Endpoints:**
  - `GET /api/v1/posts/{post_id}/comments/{comment_id}/replies/`
  - `GET /api/v1/comments/{comment_id}/replies/`
  - `GET /api/v1/comments/?source_comment_id={comment_id}`
- **Auth:** Optional (`AllowAny`, enforces post & comment visibility)
- **Query Parameters:** Same pagination, sorting (default `oldest`), and nested preview controls as `4.1`.

### 4.4 Reply Directly to a Comment

- **Endpoints:**
  - `POST /api/v1/posts/{post_id}/comments/{comment_id}/replies/`
  - `POST /api/v1/comments/{comment_id}/replies/`
- **Auth:** Required (`IsAuthenticated`)
- **Response (`201 Created`):** `PostCommentSerializer` object with `depth = parent.depth + 1` (max `10`).

### 4.5 Retrieve, Update, or Delete a Comment

- **Endpoints:**
  - `GET /api/v1/posts/{post_id}/comments/{comment_id}/` or `GET /api/v1/comments/{comment_id}/`
  - `PATCH /api/v1/posts/{post_id}/comments/{comment_id}/` or `PATCH /api/v1/comments/{comment_id}/`
    - Allowed for comment author (or active gym staff with `posts:manage` for gym-authored comments).
    - Supports `comment_text`, `comment_photo`, `comment_video`, `comment_gif`, `remove_media` (`true`/`false`), `duration_seconds`. Sets `is_edited: true` and `edited_at`.
  - `DELETE /api/v1/posts/{post_id}/comments/{comment_id}/` or `DELETE /api/v1/comments/{comment_id}/`
    - Allowed for comment author, parent post owner, or gym staff with `posts:manage`.
    - Cascades to nested replies, atomically decrements `GymPost.comments_count` and ancestor reply counters, and removes local media files.

