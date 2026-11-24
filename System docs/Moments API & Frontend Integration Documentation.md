# Moments (Stories) API & Frontend Integration Documentation

## 1. General Configuration

- **Primary Base URL:** `/api/v1/moments/`
- **Legacy Backward-Compatible Base URL:** `/api/v1/stories/`
- **Authentication:** Bearer JWT Token (`Authorization: Bearer <access_token>`)
- **Accepted Request Formats:** `multipart/form-data`, `application/x-www-form-urlencoded`, `application/json`
- **Response Format:** `application/json`
- **Standard Headers:**
  - `Authorization: Bearer <access_token>` (Required for create, reply, update, delete, `my`, `view`, `viewers`; optional for `list`, `tray`, `detail`)
  - `Accept: application/json`
  - `Content-Type: application/json` (or `multipart/form-data` for file upload)
  - `X-Gym-Context: <gym_uuid>` (Optional fallback header when the JWT token does not carry `gym_id`)

### Automatic Token Context & Read-Only Fields

| Field | Source | Behavior |
| :--- | :--- | :--- |
| `owner_type` | Bearer JWT (`context_type`) or `X-Gym-Context` | Read-only. Automatically set to `"user"` (personal context) or `"gym"` (gym context). Cannot be overridden in request payload. |
| `user_id` | Bearer JWT (`user_id`) | Read-only. Always taken from the authenticated user (author for user moments, uploader/staff for gym moments). |
| `gym_id` | Bearer JWT (`gym_id`) or `X-Gym-Context` | Read-only. Populated when `owner_type` is `"gym"`; `null` when `owner_type` is `"user"`. |
| `media_type` | Uploaded file / `media_url` / `source_post_id` | Read-only. Auto-detected as `"picture"` or `"video"` from file extension, MIME type, URL path extension, or source post attachment. |

---

## 2. Frontend UI Architecture & UX Guidelines

### 2.1. Why There Is "No Need for a 'My Moments' Button"

In modern social apps (such as Instagram or Snapchat), active ephemeral content is seamlessly unified within the **Moment Tray**:
- The **Moment Tray** (`GET /api/v1/moments/tray/`) evaluates the authenticated requesting user's identity and places the user's own active moments as the **very first item (index `0`)** in the array.
- The user's bucket contains `"is_self": true`.
- Other creators' buckets contain `"is_self": false`.
- **Frontend Recommendation:** Display the user's profile avatar with a distinct outline (or a `+` badge if they have no active moments) at the start of the horizontal scroll tray. When tapped, open the user's active moment playback or creation screen. **Do NOT add a separate "My Moments" button** in headers, navigation tabs, or sidebars.

### 2.2. Moment Reply & Comment Message Interaction (Messenger/WhatsApp-style Chat Integration)

When an authenticated user watches an active Moment, display a bottom interaction bar containing:
1. **Quick Emoji Reactions:** Allows instant one-tap reactions (`POST /api/v1/reactions/moments/{moment_id}/`).
2. **Reply Input Field ("Send Message..." or "Reply to [User]"):**
   - Entering text and sending dispatches `POST /api/v1/moments/{moment_id}/reply/` (or `/comments/`, `/message/`).
   - **Direct 1-on-1 Chat Thread Linking:** The backend finds or initiates the 1-on-1 direct conversation (`conversation_id`) between the replier and the moment author.
   - **Inbox List (`GET /api/v1/messaging/conversations/`):** The conversation is bumped to the top of both users' inboxes, updating `last_message_preview = "Replied to moment: <text>"`, `last_message_at`, and unread count badge for the recipient.
   - **Chat Message History (`GET /api/v1/messaging/conversations/{id}/messages/`):** When opened, the moment reply is rendered directly in the chat message stream with a moment preview quote card (containing thumbnail/media link, caption, and moment ID) alongside the user's text message.
   - **Real-time & Push Delivery:** The moment owner receives an immediate push notification and real-time WebSocket events broadcast over `chat_conversation_{id}` and `chat_user_{id}` channels.
   - The backend atomically increments `replies_count` (`comments_count`) on the Moment.

---

## 3. Global Error Envelope & Status Codes

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
| `400 Bad Request` | `VALIDATION_ERROR` | Empty reply message, invalid field type, unsupported media format, oversized files, expired moment reply, or invalid privacy for `owner_type`. |
| `401 Unauthorized` | `UNAUTHORIZED` / `UNAUTHORIZED_CONTEXT` | Missing, expired, or invalid Bearer token. |
| `403 Forbidden` | `PERMISSION_DENIED` | Insufficient gym RBAC permission (`stories:manage` / `posts:manage`), non-owner delete access, blocked user, age restriction, or restricted audience. |
| `404 Not Found` | `RESOURCE_NOT_FOUND` | Moment or reply does not exist, or moment is expired/deleted for non-owners. |
| `405 Method Not Allowed` | `METHOD_NOT_ALLOWED` | HTTP method not supported on endpoint. |

---

## 4. Enums & Validation Reference

### `owner_type`

| Value | Description |
| :--- | :--- |
| `"user"` | Personal / Public User moment |
| `"gym"` | Gym moment |

### `media_type` (Read-Only, Auto-Detected)

| Value | Supported Extensions | Size Limit (Multipart File) |
| :--- | :--- | :--- |
| `"picture"` | `.jpg`, `.jpeg`, `.png`, `.webp` | Max `10 MB` (`10485760` bytes) |
| `"video"` | `.mp4`, `.mov` | Max `200 MB` (`209715200` bytes) |

### `lifetime_hours` / `lifetime`

| Value | `lifetime_label` | Notes |
| :--- | :--- | :--- |
| `6` | `"6 hours"` | Accepts `6`, `"6"`, `"6h"`, `"6 hours"` |
| `12` | `"12 hours"` | Accepts `12`, `"12"`, `"12h"`, `"12 hours"` |
| `18` | `"18 hours"` | **Default** when omitted or null |
| `24` | `"24 hours"` | Accepts `24`, `"24"`, `"24h"`, `"24 hours"` |
| `48` | `"48 hours"` | Accepts `48`, `"48"`, `"48h"`, `"48 hours"` |

### `privacy`

| Value | Public User (`owner_type: "user"`) | Gym (`owner_type: "gym"`) | Visibility Rule |
| :--- | :--- | :--- | :--- |
| `"public"` | Allowed (**Default**) | Allowed (**Default**) | Visible to everyone (respecting private account / gym status / blocks / age restriction) |
| `"followers"` | Allowed | Allowed | Visible to followers of the user or gym |
| `"members_only"` | Rejected (`400`) | Allowed (alias: `"gym_members_only"`) | Visible only to gym members and authorized gym staff/owner |
| `"private"` | Allowed | Allowed | Visible only to the moment owner (or authorized gym staff/owner) |

---

## 5. Schema Models

### 5.1. Moment Object (`StorySerializer`)

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `string (uuid)` | No | Unique moment ID. |
| `owner_type` | `string (enum)` | No | Uploader type: `"user"` or `"gym"`. |
| `user_id` | `string (uuid)` | No | Uploader user UUID. |
| `user_name` | `string` | No | Uploader full name. |
| `user_avatar_url` | `string (uri)` | Yes | Absolute URL of uploader avatar. |
| `gym_id` | `string (uuid)` | Yes | Gym UUID when `owner_type="gym"`; `null` otherwise. |
| `gym_name` | `string` | Yes | Gym name when `owner_type="gym"`; `null` otherwise. |
| `gym_avatar_url` | `string (uri)` | Yes | Absolute URL of gym logo when `owner_type="gym"`. |
| `source_post_id` | `string (uuid)` | Yes | Shared post UUID, if shared from a post. |
| `source_post` | `object` | Yes | Summary object of the shared post. |
| `media_url` | `string (uri)` | No | Resolved playback media URL. |
| `original_url` | `string (uri)` | Yes | Original uploaded/provided media URL. |
| `optimized_url` | `string (uri)` | Yes | Optimized WebP/MP4 media URL once processed. |
| `thumbnail_url` | `string (uri)` | Yes | Thumbnail / poster URL. |
| `media_type` | `string (enum)` | No | `"picture"` or `"video"`. |
| `processing_status` | `string (enum)` | No | `"pending"`, `"processing"`, `"completed"`, or `"failed"`. |
| `file_size_bytes` | `integer` | No | File size in bytes. |
| `width` | `integer` | Yes | Width in pixels. |
| `height` | `integer` | Yes | Height in pixels. |
| `duration_seconds` | `number` | Yes | Video playback duration in seconds. |
| `caption` | `string` | Yes | Overlay caption (max 500 chars). |
| `background_color` | `string` | Yes | Hex color code (e.g. `#111827`). |
| `lifetime_hours` | `integer` | No | `6`, `12`, `18`, `24`, or `48`. |
| `lifetime_label` | `string` | No | Human-readable label (`"18 hours"`). |
| `privacy` | `string (enum)` | No | `"public"`, `"followers"`, `"members_only"`, `"private"`. |
| `published_at` | `string (datetime)`| No | ISO 8601 publish timestamp. |
| `expires_at` | `string (datetime)`| No | ISO 8601 expiration timestamp. |
| `is_expired` | `boolean` | No | Whether current time >= `expires_at`. |
| `is_archived` | `boolean` | No | Whether the moment is archived. |
| `views_count` | `integer` | No | Total unique views. |
| `reactions_count` | `integer` | No | Total reactions received. |
| `replies_count` | `integer` | No | Total replies/comments received. |
| `comments_count` | `integer` | No | Alias for `replies_count`. |
| `has_viewed` | `boolean` | No | `true` if current user has viewed this moment. |
| `created_at` | `string (datetime)`| No | Record creation timestamp. |
| `updated_at` | `string (datetime)`| No | Record update timestamp. |

### 5.2. Moment Tray Bucket Object (`StoryTrayBucketSerializer`)

| Field | Type | Description |
| :--- | :--- | :--- |
| `owner_type` | `string` | `"user"` or `"gym"`. |
| `owner_id` | `string (uuid)` | `user_id` or `gym_id`. |
| `owner_name` | `string` | Display name of user or gym. |
| `owner_avatar_url` | `string (uri)` | Avatar / logo URL. |
| `latest_story_at` | `string (datetime)`| Timestamp of newest moment in bucket. |
| `has_unviewed` | `boolean` | `true` if any moment has not been viewed. |
| `stories_count` | `integer` | Number of active moments in this bucket. |
| `is_self` | `boolean` | **`true` for the authenticated requesting user's own bucket** (always ordered at index `0`). |
| `stories` | `array<Moment>` | Active moments sorted chronologically. |

### 5.3. Moment Reply Object (`StoryReplySerializer`)

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `string (uuid)` | Unique reply record UUID. |
| `story_id` | `string (uuid)` | Target moment UUID. |
| `user_id` | `string (uuid)` | Author user UUID. |
| `user_name` | `string` | Author display name. |
| `user_avatar_url` | `string (uri)` | Author avatar URI. |
| `owner_type` | `string` | `"user"` or `"gym"`. |
| `gym_id` | `string (uuid)` | Gym UUID if replied on behalf of a gym. |
| `gym_name` | `string` | Gym name if gym reply. |
| `gym_avatar_url` | `string (uri)` | Gym avatar if gym reply. |
| `message` | `string` | Reply/comment text content. |
| `media_url` | `string (uri)` | Optional attached photo/media URL. |
| `conversation_id` | `string (uuid)` | Linked direct messaging conversation UUID (if available). |
| `created_at` | `string (datetime)`| Timestamp when reply was created. |
| `updated_at` | `string (datetime)`| Timestamp when reply was last updated. |

---

## 6. Endpoints Reference

### 6.1. Upload Moment
- **POST** `/api/v1/moments/`
- **Auth:** Required
- **Body:** Multipart or JSON (`file`, `media_url`, `caption`, `lifetime_hours`, `privacy`, `background_color`)
- **Response:** `201 Created` (`Moment` object)

### 6.2. Get Moment Tray (Grouped by Owner)
- **GET** `/api/v1/moments/tray/`
- **Auth:** Optional (Recommended for personalized `is_self` and `has_viewed`)
- **Ordering:** The authenticated user's own bucket (`is_self: true`) appears at **index `0`**, followed by unviewed moments, then viewed moments ordered by recency.
- **Response:** `200 OK` (`Array<MomentTrayBucket>`)

### 6.3. Reply / Comment Message on Moment
- **POST** `/api/v1/moments/{moment_id}/reply/` (Aliases: `/comments/`, `/message/`)
- **Auth:** Required
- **Request JSON:**
```json
{
  "message": "Incredible squat set! What brand belt is that?"
}
```
*(Also accepts `"comment"`, `"comment_text"`, or `"text"` as aliases for `"message"`).*
- **Response `201 Created`:**
```json
{
  "id": "e8d2c140-5a7b-48c9-94b1-8899aabbccdd",
  "story_id": "9f8c2a1b-3d4e-4f5a-9b1c-7e6d5c4b3a21",
  "user_id": "22222222-3333-4444-5555-666666666666",
  "user_name": "Jordan Lee",
  "user_avatar_url": "https://api.manygym.com/media/users/avatars/jordan.webp",
  "owner_type": "user",
  "gym_id": null,
  "gym_name": null,
  "gym_avatar_url": null,
  "message": "Incredible squat set! What brand belt is that?",
  "media_url": null,
  "conversation_id": "77777777-8888-9999-aaaa-bbbbccccdddd",
  "created_at": "2026-11-24T14:10:00Z",
  "updated_at": "2026-11-24T14:10:00Z"
}
```

> [!TIP]
> **Messaging / Chat Appearance (Messenger & WhatsApp Style):**
> When this endpoint succeeds:
> 1. The returned `conversation_id` is updated in the chat inbox (`GET /api/v1/messaging/conversations/`) with `last_message_preview = "Replied to moment: <message>"`.
> 2. Inside the chat history (`GET /api/v1/messaging/conversations/{conversation_id}/messages/`), a message entry is created with `nonce: "moment_reply"` whose encrypted payload contains:
> ```json
> {
>   "type": "moment_reply",
>   "moment_id": "9f8c2a1b-3d4e-4f5a-9b1c-7e6d5c4b3a21",
>   "moment_media_url": "https://api.manygym.com/media/...",
>   "moment_thumbnail_url": "https://api.manygym.com/media/...",
>   "moment_caption": "Heavy leg day 💪",
>   "text": "Incredible squat set! What brand belt is that?"
> }
> ```
> Frontend chat clients can render this as a quoted Moment card with playback thumbnail above the reply message.

### 6.4. List Moment Replies
- **GET** `/api/v1/moments/{moment_id}/replies/` (Alias: `/comments/`)
- **Auth:** Required
- **Access Rule:** Moment owners see all replies. Non-owners see their own replies sent to this moment.
- **Response:** `200 OK` (Standard Paginated List of `MomentReply` objects)

### 6.5. Delete Moment Reply
- **DELETE** `/api/v1/moments/{moment_id}/replies/{reply_id}/` (Alias: `/comments/{reply_id}/`)
- **Auth:** Required (Reply author, Moment owner, or gym staff manager)
- **Response `200 OK`:**
```json
{
  "message": "Reply deleted successfully."
}
```

### 6.6. React to Moment
- **POST** `/api/v1/reactions/moments/{moment_id}/`
- **Auth:** Required
- **Request JSON:**
```json
{
  "reaction_code": "fire"
}
```
- **Response:** `200 OK` / `201 Created`

### 6.7. Moment Reaction Summary
- **GET** `/api/v1/reactions/moments/{moment_id}/summary/`
- **Auth:** Optional
- **Response `200 OK`:** Reaction count, emoji breakdown, and viewer reaction state.

### 6.8. Record Moment View
- **POST** `/api/v1/moments/{moment_id}/view/`
- **Auth:** Required
- **Response `200 OK`:** `{"message": "Story view recorded.", "views_count": 12, "newly_viewed": true}`

### 6.9. List Moment Viewers
- **GET** `/api/v1/moments/{moment_id}/viewers/`
- **Auth:** Required (Moment owner or authorized gym manager only)
- **Response `200 OK`:** Paginated viewer users.
