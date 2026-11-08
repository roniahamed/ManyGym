# Personal User Settings API Integration Document

## 1. General Configuration

- **Base URL:** `/api/v1/users/`
- **Authentication:** Bearer Token
- **Headers:**
  ```http
  Authorization: Bearer <access_token>
  Content-Type: application/json
  Accept: application/json
  ```

---

## 2. Global Error Envelope

All error responses (`4xx`, `5xx`) use the following JSON structure:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Validation failed.",
  "details": {
    "field_name": [
      "Field error message."
    ]
  }
}
```

### Standard Status Codes
- `400 Bad Request`: Validation failure, type mismatch, self-block.
- `401 Unauthorized`: Missing or invalid token.
- `403 Forbidden`: Permission denied based on audience rules.
- `404 Not Found`: User or resource not found.
- `405 Method Not Allowed`: Unsupported HTTP method.

---

## 3. Section 1: Display Settings

### 3.1. Retrieve Settings
- **Method:** `GET`
- **Endpoint:** `/api/v1/users/settings/`
- **Request Body:** None

#### Response `200 OK`
```json
{
  "id": "76ea48fc-ef74-4b55-a4b5-120cae5fbd29",
  "user_id": "84c9826f-9988-4433-2211-123456789abc",
  "language": "en",
  "video_autoplay": true,
  "dark_mode": false,
  "is_private": false,
  "require_follow_approval": false,
  "who_can_follow": "everyone",
  "who_can_follow_me": "everyone",
  "who_can_message": "followers",
  "who_can_see_followers": "everyone",
  "who_can_see_following": "everyone",
  "is_deactivated": false,
  "deactivated_at": null,
  "is_deleted": false,
  "deleted_at": null,
  "created_at": "2026-11-01T10:00:00Z",
  "updated_at": "2026-11-08T18:00:00Z"
}
```

---

### 3.2. Update Display Settings
- **Method:** `PATCH`
- **Endpoint:** `/api/v1/users/settings/`

#### Request Fields
| Field | Type | Required | Default | Validation Rules / Values |
| :--- | :--- | :--- | :--- | :--- |
| `language` | `string` | No | `"en"` | Max length 20 chars, cannot be blank (e.g., `"en"`, `"bn"`). |
| `video_autoplay` | `boolean` | No | `true` | `true` (ON), `false` (OFF). |
| `dark_mode` | `boolean` | No | `false` | `true` (ON), `false` (OFF). |

#### Request Payload
```json
{
  "language": "en",
  "video_autoplay": true,
  "dark_mode": false
}
```

#### Response `200 OK`
```json
{
  "id": "76ea48fc-ef74-4b55-a4b5-120cae5fbd29",
  "user_id": "84c9826f-9988-4433-2211-123456789abc",
  "language": "en",
  "video_autoplay": true,
  "dark_mode": false,
  "is_private": false,
  "require_follow_approval": false,
  "who_can_follow": "everyone",
  "who_can_follow_me": "everyone",
  "who_can_message": "followers",
  "who_can_see_followers": "everyone",
  "who_can_see_following": "everyone",
  "is_deactivated": false,
  "deactivated_at": null,
  "is_deleted": false,
  "deleted_at": null,
  "created_at": "2026-11-01T10:00:00Z",
  "updated_at": "2026-11-08T18:15:00Z"
}
```

---

## 4. Section 2: Blocking Settings

### 4.1. List Blocked Users
- **Method:** `GET`
- **Endpoint:** `/api/v1/users/settings/blocked-users/`
- **Request Body:** None

#### Response `200 OK`
```json
[
  {
    "id": "e309fc7a-d7df-4573-8ca1-4f808726bc52",
    "user_id": "c1f76d41-ef12-4f3b-8910-abcdef012345",
    "email": "user@example.com",
    "first_name": "Alex",
    "last_name": "Morgan",
    "avatar_url": "https://cdn.manygym.com/avatars/user.jpg",
    "reason": "Inappropriate messages",
    "created_at": "2026-11-05T14:22:10Z"
  }
]
```

---

### 4.2. Search Users to Block
- **Method:** `GET`
- **Endpoint:** `/api/v1/users/settings/blocked-users/search/`
- **Query Parameters:**
  - `q` (string, optional): Matches `first_name`, `last_name`, or `email`. Excludes current user and already blocked users.

#### Response `200 OK`
```json
[
  {
    "id": "d2a67e89-9812-47ef-bc43-23456789abcd",
    "email": "alex.morgan@example.com",
    "first_name": "Alex",
    "last_name": "Morgan",
    "avatar_url": "https://cdn.manygym.com/avatars/alex.jpg"
  }
]
```

---

### 4.3. Block User
- **Method:** `POST`
- **Endpoint:** `/api/v1/users/settings/blocked-users/`

#### Request Fields
| Field | Type | Required | Default | Validation Rules / Values |
| :--- | :--- | :--- | :--- | :--- |
| `user_id` | `string (UUID)` | Yes | — | Valid UUID. Cannot be the current user. |
| `reason` | `string` | No | `""` | Max length 255 characters. |

#### Request Payload
```json
{
  "user_id": "d2a67e89-9812-47ef-bc43-23456789abcd",
  "reason": "Inappropriate behavior"
}
```

#### Response `201 Created`
```json
{
  "id": "f5b8c9d0-1234-5678-9abc-def012345678",
  "user_id": "d2a67e89-9812-47ef-bc43-23456789abcd",
  "email": "alex.morgan@example.com",
  "first_name": "Alex",
  "last_name": "Morgan",
  "avatar_url": "https://cdn.manygym.com/avatars/alex.jpg",
  "reason": "Inappropriate behavior",
  "created_at": "2026-11-08T18:30:00Z"
}
```

---

### 4.4. Unblock User
- **Method:** `DELETE`
- **Endpoint:** `/api/v1/users/settings/blocked-users/{user_id}/`
- **Path Parameter:**
  - `user_id` (string, UUID, required): UUID of the user to unblock.
- **Request Body:** None

#### Response `200 OK`
```json
{
  "message": "User unblocked successfully."
}
```

---

### 4.5. Block from Followers List
- **Method:** `POST`
- **Endpoint:** `/api/v1/users/followers/{user_id}/block/`
- **Aliases:**
  - `/api/v1/users/settings/followers/{user_id}/block/`
  - `/api/v1/users/settings/blocked-users/followers/{user_id}/`
- **Path Parameter:**
  - `user_id` (string, UUID, required): UUID of the follower to block and remove.

#### Request Fields
| Field | Type | Required | Default | Validation Rules / Values |
| :--- | :--- | :--- | :--- | :--- |
| `reason` | `string` | No | `"Blocked from followers list"` | Max length 255 characters. |

#### Request Payload
```json
{
  "reason": "Blocked from followers list"
}
```

#### Response `200 OK`
```json
{
  "message": "User successfully blocked and removed from followers."
}
```

---

## 5. Section 3: Audience Settings

### 5.1. Update Audience Settings
- **Method:** `PATCH`
- **Endpoint:** `/api/v1/users/settings/`

#### Request Fields
| Field | Type | Required | Default | Validation Rules / Values |
| :--- | :--- | :--- | :--- | :--- |
| `who_can_follow` | `string` | No | `"everyone"` | Allowed: `"everyone"`, `"friends_of_friends"` |
| `who_can_follow_me` | `string` | No | `"everyone"` | Alias for `who_can_follow`. Allowed: `"everyone"`, `"friends_of_friends"` |
| `who_can_see_followers` | `string` | No | `"everyone"` | Allowed: `"everyone"`, `"followers"`, `"private"` |
| `who_can_see_following` | `string` | No | `"everyone"` | Allowed: `"everyone"`, `"followers"`, `"private"` |
| `who_can_message` | `string` | No | `"followers"` | Allowed: `"everyone"`, `"followers"`, `"no_one"` |
| `is_private` | `boolean` | No | `false` | `true`, `false` |
| `require_follow_approval` | `boolean` | No | `false` | `true`, `false` |

#### Request Payload
```json
{
  "who_can_follow": "friends_of_friends",
  "who_can_see_followers": "followers",
  "who_can_see_following": "private",
  "who_can_message": "followers",
  "is_private": false,
  "require_follow_approval": false
}
```

#### Response `200 OK`
```json
{
  "id": "76ea48fc-ef74-4b55-a4b5-120cae5fbd29",
  "user_id": "84c9826f-9988-4433-2211-123456789abc",
  "language": "en",
  "video_autoplay": true,
  "dark_mode": false,
  "is_private": false,
  "require_follow_approval": false,
  "who_can_follow": "friends_of_friends",
  "who_can_follow_me": "friends_of_friends",
  "who_can_message": "followers",
  "who_can_see_followers": "followers",
  "who_can_see_following": "private",
  "is_deactivated": false,
  "deactivated_at": null,
  "is_deleted": false,
  "deleted_at": null,
  "created_at": "2026-11-01T10:00:00Z",
  "updated_at": "2026-11-08T18:40:00Z"
}
```

---

## 6. Section 4: Access & Control (Account Lifecycle)

### 6.1. Execute Lifecycle Action
- **Method:** `POST`
- **Endpoint:** `/api/v1/users/settings/access-control/`

#### Request Fields
| Field | Type | Required | Validation Rules / Values |
| :--- | :--- | :--- | :--- |
| `action` | `string` | Yes | Allowed: `"deactivate"`, `"reactivate"`, `"delete"`, `"restore"` |
| `password` | `string` | Conditional | Required when action is `"delete"` or `"restore"`. |
| `confirmation` | `string` | Conditional | Required when action is `"delete"`. Must be exact string `"delete"`. |

#### Request Payload: Deactivate Account
```json
{
  "action": "deactivate"
}
```

> [!NOTE]
> **Automatic Reactivation on Next Login:**
> If a user deactivates their account, their deactivate status is automatically removed upon their next login attempt with valid credentials. No manual reactivation request or toggle is required.

#### Request Payload: Delete Account
```json
{
  "action": "delete",
  "password": "AccountPassword123!",
  "confirmation": "delete"
}
```

> [!IMPORTANT]
> **24-Hour Wait Grace Period for Deletion:**
> When an account deletion is initiated, a 24-hour waiting window commences.
> - **Login within 24 hours:** If the user logs in again within this 24-hour period, the deletion request is automatically cancelled, soft-deletion flags are cleared, and the account is restored to `active`.
> - **Login after 24 hours:** If the user attempts to log in after 24 hours have elapsed, the account is permanently inaccessible and rejected with `"This account has been permanently deleted."`.

#### Response `200 OK`
```json
{
  "id": "76ea48fc-ef74-4b55-a4b5-120cae5fbd29",
  "user_id": "84c9826f-9988-4433-2211-123456789abc",
  "language": "en",
  "video_autoplay": true,
  "dark_mode": false,
  "two_factor_enabled": false,
  "is_private": false,
  "require_follow_approval": false,
  "who_can_follow": "everyone",
  "who_can_follow_me": "everyone",
  "who_can_message": "followers",
  "who_can_see_followers": "everyone",
  "who_can_see_following": "everyone",
  "is_deactivated": true,
  "deactivated_at": "2026-11-08T18:45:00Z",
  "is_deleted": false,
  "deleted_at": null,
  "created_at": "2026-11-01T10:00:00Z",
  "updated_at": "2026-11-08T18:45:00Z"
}
```

---

## 7. Section 5: Login and Security Settings

### 7.1. Retrieve Login & Security Overview
- **Method:** `GET`
- **Endpoint:** `/api/v1/users/settings/security/`
- **Request Body:** None

#### Response `200 OK`
```json
{
  "contact_info": {
    "primary_email": "alex.morgan@manygym.com",
    "secondary_email": "alex.backup@gmail.com",
    "phone": "+14155552671"
  },
  "two_factor_enabled": false,
  "logged_in_devices_count": 2,
  "max_devices": 5,
  "account_status": {
    "is_deactivated": false,
    "deactivated_at": null,
    "is_deleted": false,
    "deleted_at": null,
    "delete_pending": false
  }
}
```

---

### 7.2. Contact Information

#### Retrieve Contact Information
- **Method:** `GET`
- **Endpoint:** `/api/v1/users/settings/security/contact-info/`
- **Response `200 OK`:**
```json
{
  "primary_email": "alex.morgan@manygym.com",
  "secondary_email": "alex.backup@gmail.com",
  "phone": "+14155552671"
}
```

#### Update Contact Information
- **Method:** `PATCH`
- **Endpoint:** `/api/v1/users/settings/security/contact-info/`

#### Request Fields
| Field | Type | Required | Rules & Restrictions |
| :--- | :--- | :--- | :--- |
| `primary_email` / `email` | `string` | Forbidden | **Cannot be updated or deleted.** Attempting to submit either returns `400 Bad Request`. |
| `secondary_email` | `string (email) / null` | No | Optional backup email. Cannot match primary email. Set to `null` or `""` to remove. |
| `phone` | `string / null` | No | Optional phone number (max 50 chars). Set to `null` or `""` to remove. |

#### Request Payload
```json
{
  "secondary_email": "alex.recovery@example.com",
  "phone": "+14155559876"
}
```

#### Response `200 OK`
```json
{
  "primary_email": "alex.morgan@manygym.com",
  "secondary_email": "alex.recovery@example.com",
  "phone": "+14155559876"
}
```

---

### 7.3. Change Password
- **Method:** `POST`
- **Endpoints:**
  - `/api/v1/users/settings/security/change-password/`
  - `/api/v1/users/change-password/` (backward-compatible alias)

#### Request Fields
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `current_password` | `string` | Yes | Existing account password. |
| `new_password` | `string` | Yes | New password (minimum 8 characters). |
| `confirm_password` | `string` | No | Must match `new_password` if supplied. |

#### Request Payload
```json
{
  "current_password": "CurrentPassword123!",
  "new_password": "NewStrongPassword2026!",
  "confirm_password": "NewStrongPassword2026!"
}
```

#### Response `200 OK`
```json
{
  "message": "Password successfully changed."
}
```

---

### 7.4. Two-Factor Authentication (2FA)

#### 7.4.1. Retrieve 2FA Status
- **Method:** `GET`
- **Endpoint:** `/api/v1/users/settings/security/2fa/`
- **Response `200 OK`:**
```json
{
  "two_factor_enabled": false
}
```

#### 7.4.2. Toggle 2FA (ON/OFF)
- **Method:** `PATCH`
- **Endpoint:** `/api/v1/users/settings/security/2fa/`

#### Request Payload
```json
{
  "two_factor_enabled": true
}
```

#### Response `200 OK`
```json
{
  "two_factor_enabled": true
}
```

#### 7.4.3. 2FA Login Flow & Dispatch Fallback
When `two_factor_enabled` is `true`, standard login (`POST /api/v1/auth/login/`) initiates the 2FA verification sequence.

**Automated Fallback Sequence:**
1. **Primary Email:** OTP is sent to `user.email`.
2. **Secondary Email (Fallback 1):** If primary email delivery fails, system immediately dispatches OTP to `user.secondary_email`.
3. **Phone SMS (Fallback 2):** If secondary email fails or is absent, system dispatches OTP via SMS to `user.phone`.

#### Login Response `200 OK` (2FA Challenge Triggered)
```json
{
  "two_factor_required": true,
  "message": "Verification code sent via primary email.",
  "channel": "primary_email",
  "destination": "al***@manygym.com",
  "email": "alex.morgan@manygym.com"
}
```

#### 7.4.4. Verify 2FA Code
- **Method:** `POST`
- **Endpoint:** `/api/v1/auth/verify-2fa/`

#### Request Fields
| Field | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `email` | `string` | Yes | Account email address. |
| `otp_code` | `string` | Yes | 6-digit numeric verification code. |
| `device_id` | `string` | No | Client device identifier string. |
| `device_name` | `string` | No | Client friendly device name. |

#### Request Payload
```json
{
  "email": "alex.morgan@manygym.com",
  "otp_code": "481920",
  "device_id": "iphone_15_pro_abc",
  "device_name": "iPhone 15 Pro"
}
```

#### Response `200 OK`
```json
{
  "message": "Two-factor authentication verified successfully.",
  "user": {
    "id": "84c9826f-9988-4433-2211-123456789abc",
    "email": "alex.morgan@manygym.com",
    "first_name": "Alex",
    "last_name": "Morgan",
    "phone": "+14155552671",
    "status": "active",
    "is_verified": true
  },
  "tokens": {
    "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "context_type": "personal",
    "gym_id": null,
    "gym_name": null,
    "scopes": []
  }
}
```

#### 7.4.5. Resend 2FA Code
- **Method:** `POST`
- **Endpoint:** `/api/v1/auth/resend-2fa/`

#### Request Payload
```json
{
  "email": "alex.morgan@manygym.com",
  "channel": "secondary_email"
}
```

---

### 7.5. Logged-In Devices (Max 5)

Each user account can have a maximum of **5 concurrent logged-in devices**.
- **Automatic Oldest Eviction:** If a 6th device logs in, the oldest device session is automatically evicted.
- **Key & Session Cleanup on Deletion:** When a device is evicted or deleted by the user, its active authentication tokens (`AuthToken`) are revoked and its end-to-end cryptographic keys (`UserDeviceKey`) are completely purged.

#### 7.5.1. List Logged-In Devices
- **Method:** `GET`
- **Endpoint:** `/api/v1/users/settings/security/devices/`

#### Response `200 OK`
```json
[
  {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "device_id": "laptop_macbook_pro_1",
    "device_name": "MacBook Pro (Chrome)",
    "ip_address": "192.168.1.100",
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)...",
    "last_login": "2026-11-08T19:00:00Z",
    "created_at": "2026-11-01T10:00:00Z",
    "is_current_device": true
  },
  {
    "id": "7bc32f41-1234-4562-b3fc-2c963f66afa7",
    "device_id": "iphone_15_pro_abc",
    "device_name": "iPhone 15 Pro",
    "ip_address": "192.168.1.105",
    "user_agent": "ManyGymApp/1.0 iOS",
    "last_login": "2026-11-07T14:30:00Z",
    "created_at": "2026-11-03T12:00:00Z",
    "is_current_device": false
  }
]
```

#### 7.5.2. Delete Logged-In Device
- **Method:** `DELETE`
- **Endpoint:** `/api/v1/users/settings/security/devices/{device_id}/`
- **Path Parameter:**
  - `device_id` (string, required): Client device identifier or device UUID.

#### Response `200 OK`
```json
{
  "message": "Device removed and device key cleaned successfully."
}
```

---

## 8. Complete Field Dictionary

### Settings Object Fields
| Field Name | Type | Read-Only | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | Yes | Unique ID of settings record. |
| `user_id` | `UUID` | Yes | Owner user ID. |
| `language` | `string` | No | Selected interface language. |
| `video_autoplay` | `boolean` | No | Auto-play videos in feed. |
| `dark_mode` | `boolean` | No | Dark theme preference. |
| `two_factor_enabled` | `boolean` | No | Two-Factor Authentication toggle (ON/OFF). |
| `is_private` | `boolean` | No | Private account toggle. |
| `require_follow_approval`| `boolean` | No | Manual confirmation for follow requests. |
| `who_can_follow` | `enum` | No | Allowed: `"everyone"`, `"friends_of_friends"`. |
| `who_can_follow_me` | `enum` | Yes | Mirror alias of `who_can_follow`. |
| `who_can_message` | `enum` | No | Allowed: `"everyone"`, `"followers"`, `"no_one"`. |
| `who_can_see_followers` | `enum` | No | Allowed: `"everyone"`, `"followers"`, `"private"`. |
| `who_can_see_following` | `enum` | No | Allowed: `"everyone"`, `"followers"`, `"private"`. |
| `is_deactivated` | `boolean` | Yes (Via action) | Account suspension flag. Auto-removed upon next login. |
| `deactivated_at` | `datetime / null` | Yes | Timestamp of deactivation. |
| `is_deleted` | `boolean` | Yes (Via action) | Soft deletion flag (24-hour grace period). |
| `deleted_at` | `datetime / null` | Yes | Timestamp of deletion request. |
| `created_at` | `datetime` | Yes | Record creation timestamp. |
| `updated_at` | `datetime` | Yes | Last update timestamp. |

### Device Record Fields
| Field Name | Type | Read-Only | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | Yes | Unique ID of logged-in device record. |
| `device_id` | `string` | Yes | Client device unique identifier. |
| `device_name` | `string` | Yes | Friendly client device label (e.g. "MacBook Pro"). |
| `ip_address` | `string / null` | Yes | Client IP address at last session activity. |
| `user_agent` | `string` | Yes | Browser or mobile client user agent string. |
| `last_login` | `datetime` | Yes | Timestamp of most recent session authentication. |
| `created_at` | `datetime` | Yes | Timestamp when device was first registered. |
| `is_current_device`| `boolean` | Yes | Whether this record matches the current API client. |

### Blocked User Record Fields
| Field Name | Type | Read-Only | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | Yes | Unique ID of the block entry. |
| `user_id` | `UUID` | Yes | UUID of the blocked user. |
| `email` | `string` | Yes | Email of the blocked user. |
| `first_name` | `string` | Yes | First name of the blocked user. |
| `last_name` | `string` | Yes | Last name of the blocked user. |
| `avatar_url` | `string / null` | Yes | Avatar image URL of the blocked user. |
| `reason` | `string` | Yes | Recorded reason for the block. |
| `created_at` | `datetime` | Yes | Timestamp when the block occurred. |

### Search Users to Block Record Fields
| Field Name | Type | Read-Only | Description |
| :--- | :--- | :--- | :--- |
| `id` | `UUID` | Yes | UUID of the user. |
| `email` | `string` | Yes | Email of the user. |
| `first_name` | `string` | Yes | First name of the user. |
| `last_name` | `string` | Yes | Last name of the user. |
| `avatar_url` | `string / null` | Yes | Avatar image URL. |
