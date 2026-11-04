# Many Gym - Phase 1 API Integration Documentation

This document provides complete, production-grade documentation for the **Phase 1** APIs of Many Gym (User Identity, Multi-Tenant Context-Driven Authentication, and Dynamic RBAC). It aligns strictly with the standards defined in `api documentations.md`.

---

## Table of Contents
1. [Core Principles & Architectural Conventions](#core-principles--architectural-conventions)
2. [Global Error Envelope](#global-error-envelope)
3. [User Identity & Onboarding APIs](#user-identity--onboarding-apis)
   - [POST /api/v1/auth/register/](#1-post-apiv1authregister)
   - [POST /api/v1/auth/verify-signup-otp/](#2-post-apiv1authverify-signup-otp)
   - [POST /api/v1/auth/resend-otp/](#3-post-apiv1authresend-otp)
4. [Password Management APIs](#password-management-apis)
   - [POST /api/v1/auth/forgot-password/](#4-post-apiv1authforgot-password)
   - [POST /api/v1/auth/verify-reset-otp/](#5-post-apiv1authverify-reset-otp)
   - [POST /api/v1/auth/reset-password/](#6-post-apiv1authreset-password)
   - [POST /api/v1/auth/change-password/](#7-post-apiv1authchange-password)
5. [Authentication & Context Switching APIs](#authentication--context-switching-apis)
   - [POST /api/v1/auth/login/](#8-post-apiv1authlogin)
   - [POST /api/v1/auth/switch-context/](#9-post-apiv1authswitch-context)
   - [POST /api/v1/auth/logout/](#10-post-apiv1authlogout)
   - [POST /api/v1/auth/refresh/](#10b-post-apiv1authrefresh)
6. [User Profile APIs](#user-profile-apis)
   - [GET /api/v1/auth/me/](#11-get-apiv1authme)
   - [PATCH /api/v1/auth/me/](#12-patch-apiv1authme)
   - [GET /api/v1/users/profile/about/](#13-get-apiv1usersprofileabout)
   - [PATCH /api/v1/users/profile/about/](#14-patch-apiv1usersprofileabout)
   - [GET /api/v1/users/{user_id}/profile/about/](#15-get-apiv1usersuser_idprofileabout)
   - [GET & POST /api/v1/users/profile/about/educations/](#16-get--post-apiv1usersprofileabouteducations)
   - [PATCH & DELETE /api/v1/users/profile/about/educations/{id}/](#17-patch--delete-apiv1usersprofileabouteducationsid)
   - [GET & POST /api/v1/users/profile/about/social-links/](#18-get--post-apiv1usersprofileaboutsocial-links)
   - [PATCH & DELETE /api/v1/users/profile/about/social-links/{id}/](#19-patch--delete-apiv1usersprofileaboutsocial-linksid)
7. [Dynamic RBAC & Access Control APIs](#dynamic-rbac--access-control-apis)
   - [GET /api/v1/access-control/permissions/](#13-get-apiv1access-controlpermissions)
   - [GET /api/v1/access-control/roles/](#14-get-apiv1access-controlroles)
   - [POST /api/v1/access-control/roles/](#15-post-apiv1access-controlroles)
   - [GET /api/v1/access-control/roles/{id}/](#16-get-apiv1access-controlrolesid)
   - [PATCH /api/v1/access-control/roles/{id}/](#17-patch-apiv1access-controlrolesid)
   - [DELETE /api/v1/access-control/roles/{id}/](#18-delete-apiv1access-controlrolesid)
   - [GET /api/v1/access-control/staff/](#19-get-apiv1access-controlstaff)
   - [POST /api/v1/access-control/staff/invite/](#20-post-apiv1access-controlstaffinvite)
   - [PATCH /api/v1/access-control/staff/{id}/](#21-patch-apiv1access-controlstaffid)
   - [DELETE /api/v1/access-control/staff/{id}/](#22-delete-apiv1access-controlstaffid)

---

## Core Principles & Architectural Conventions

### Single Account, Multiple Profiles & Context-Driven Tokens
- **One User Account**: A single email and password represent the user's primary credentials.
- **Context Types**:
  - `personal`: The user acts on their own behalf.
  - `gym`: The user acts on behalf of a specific gym (`gym_id`).
- **Contextual JWT**: When switching contexts via `/api/v1/auth/switch-context/`, the returned JWT includes:
  ```json
  {
    "context_type": "gym",
    "gym_id": "84c9826f-9988-4433-2211-123456789abc",
    "gym_name": "Apex Fitness Club",
    "scopes": [
      "members:read",
      "members:edit",
      "routines:assign"
    ]
  }
  ```
- Operations targeting a specific gym require an active Gym Context token matching that gym.

---

## Global Error Envelope

All 4xx and 5xx responses strictly adhere to the unified JSON error format:

```json
{
  "code": "VALIDATION_ERROR",
  "message": "Specific explanation of what went wrong.",
  "details": {}
}
```

Standard codes:
- `VALIDATION_ERROR` (HTTP 400)
- `AUTHENTICATION_REQUIRED` (HTTP 401)
- `UNAUTHORIZED_CONTEXT` (HTTP 401)
- `PERMISSION_DENIED` (HTTP 403)
- `NOT_FOUND` / `RESOURCE_NOT_FOUND` (HTTP 404)
- `RESOURCE_CONFLICT` (HTTP 409)

---

## User Identity & Onboarding APIs

### 1. POST `/api/v1/auth/register/`

#### 1. Summary
Registers a new user account and triggers an asynchronous email verification OTP.

#### 2. Authentication
None (Public).

#### 3. Authorization
Public.

#### 4. Request
- Content-Type: `application/json`

#### 5. Parameters
None.

#### 6. Request Body
| Field | Type | Required | Description |
|---|---|---|---|
| `email` | String | Yes | Unique email address. |
| `password` | String | Yes | Password (minimum 8 characters). |
| `first_name` | String | Yes | First name. |
| `last_name` | String | Yes | Last name. |
| `phone` | String | No | Mobile phone number. |

#### 7. Request Example
```json
{
  "email": "alex.morgan@manygym.com",
  "password": "SecurePassword2026!",
  "first_name": "Alex",
  "last_name": "Morgan",
  "phone": "+14155552671"
}
```

#### 8. Success Response
- **HTTP Status**: `201 Created`

#### 9. Success Example
```json
{
  "message": "Registration successful. A 6-digit verification code has been dispatched to your email.",
  "email": "alex.morgan@manygym.com"
}
```

#### 10. Error Responses
- `400 Bad Request`: Field validation error (e.g. short password).
- `409 Conflict`: Email already exists.

#### 11. Error Examples
```json
{
  "code": "RESOURCE_CONFLICT",
  "message": "An account with this email address already exists.",
  "details": {}
}
```

#### 12. Workflow / State Rules
- User is created with `is_verified = False` and status `active`.
- Generates a 6-digit OTP code valid for 15 minutes.

#### 13. Side Effects
- Asynchronously sends verification email via Celery and SMTP.

---

### 2. POST `/api/v1/auth/verify-signup-otp/`

#### 1. Summary
Verifies the signup OTP code, activates user verification status, and returns initial session JWT tokens.

#### 2. Authentication
None.

#### 3. Authorization
Public.

#### 4. Request Body
| Field | Type | Required | Description |
|---|---|---|---|
| `email` | String | Yes | Registered email. |
| `otp_code` | String | Yes | 6-digit numeric OTP. |

#### 7. Request Example
```json
{
  "email": "alex.morgan@manygym.com",
  "otp_code": "849201"
}
```

#### 8. Success Response
- **HTTP Status**: `200 OK`

#### 9. Success Example
```json
{
  "message": "Account successfully verified.",
  "user": {
    "id": "b3e0c0fa-2384-48f8-b3d5-e357e62a0a20",
    "email": "alex.morgan@manygym.com",
    "first_name": "Alex",
    "last_name": "Morgan",
    "phone": "+14155552671",
    "status": "active",
    "is_verified": true,
    "created_at": "2026-10-12T12:00:00Z",
    "updated_at": "2026-10-12T12:05:00Z",
    "profile": {
      "avatar_url": null,
      "address": null,
      "city": null,
      "country": null,
      "date_of_birth": null,
      "sex": null,
      "nationality": null
    }
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

#### 10. Error Responses
- `400 Bad Request`: Invalid or expired OTP, or maximum 5 attempts reached (code invalidated to prevent brute force).
- `404 Not Found`: User not found.
- `429 Too Many Requests`: Verification rate limit throttled (`code: "THROTTLED"`).

---

### 3. POST `/api/v1/auth/resend-otp/`

#### 1. Summary
Invalidates previous unused OTPs and dispatches a fresh 6-digit signup verification OTP.

#### 7. Request Example
```json
{
  "email": "alex.morgan@manygym.com"
}
```

#### 8. Success Response
- **HTTP Status**: `200 OK`
```json
{
  "message": "A new verification code has been dispatched to your email."
}
```

---

## Password Management APIs

### 4. POST `/api/v1/auth/forgot-password/`
- **Summary**: Sends a 6-digit OTP code to the provided email address for password reset.
- **Request Example**: `{"email": "alex.morgan@manygym.com"}`
- **Success (200)**: `{"message": "If an account exists with this email, a password reset code has been dispatched."}`

### 5. POST `/api/v1/auth/verify-reset-otp/`
- **Summary**: Validates that the reset OTP is unexpired and active.
- **Request Example**: `{"email": "alex.morgan@manygym.com", "otp_code": "592104"}`
- **Success (200)**: `{"message": "OTP verification successful. You may now submit your new password."}`

### 6. POST `/api/v1/auth/reset-password/`
- **Summary**: Updates account password to `new_password` using the verified OTP.
- **Request Example**:
```json
{
  "email": "alex.morgan@manygym.com",
  "otp_code": "592104",
  "new_password": "NewStrongPassword2026!"
}
```
- **Success (200)**: `{"message": "Password reset successful. Please login with your new credentials."}`

### 7. POST `/api/v1/auth/change-password/`
- **Summary**: Authenticated user password update.
- **Authentication**: Required (`Bearer <JWT>`).
- **Request Example**:
```json
{
  "current_password": "CurrentPassword2026!",
  "new_password": "NewSecretPassword2026!"
}
```
- **Success (200)**: `{"message": "Password changed successfully."}`

---

## Authentication & Context Switching APIs

### 8. POST `/api/v1/auth/login/`

#### 1. Summary
Authenticates user credentials and issues a contextual JWT token pair.

#### 6. Request Body
| Field | Type | Required | Description |
|---|---|---|---|
| `email` | String | Yes | User email. |
| `password` | String | Yes | User password. |

#### 7. Request Example
```json
{
  "email": "alex.morgan@manygym.com",
  "password": "SecurePassword2026!"
}
```

#### 8. Success Response (200 OK)
```json
{
  "message": "Login successful.",
  "user": {
    "id": "b3e0c0fa-2384-48f8-b3d5-e357e62a0a20",
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

#### 10. Error Responses
- `400 Bad Request`: Invalid credentials or unverified account (`"Your account has not been verified yet. Please verify your OTP."`).
- `429 Too Many Requests`: Account locked after 5 consecutive failed login attempts or rate limit exceeded (`code: "THROTTLED"`, returns `Retry-After` header).

---

### 9. POST `/api/v1/auth/switch-context/`

#### 1. Summary
Switches session context to Personal Profile or a specific Gym. Re-issues contextual access & refresh tokens carrying context claims and computed permission scopes.

#### 2. Authentication
Required (`Bearer <JWT>`).

#### 3. Authorization
To switch to a gym context, user must be:
- The **Gym Owner**, OR
- An **Active Staff Member** assigned to that gym.

#### 6. Request Body
| Field | Type | Required | Description |
|---|---|---|---|
| `context_type` | String | Yes | `"personal"` or `"gym"`. |
| `gym_id` | UUID | Conditional | Required if `context_type` is `"gym"`. |

#### 7. Request Examples
**Switching to Gym Context:**
```json
{
  "context_type": "gym",
  "gym_id": "31d57929-e58f-49b0-9bf7-fa5d07c08285"
}
```

**Switching to Personal Context:**
```json
{
  "context_type": "personal"
}
```

#### 8. Success Response (200 OK)
```json
{
  "message": "Successfully switched to gym context.",
  "tokens": {
    "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "context_type": "gym",
    "gym_id": "31d57929-e58f-49b0-9bf7-fa5d07c08285",
    "gym_name": "Apex Fitness Club",
    "scopes": [
      "members:read",
      "members:edit",
      "routines:assign",
      "studio:read"
    ]
  }
}
```

#### 10. Error Responses
- `401 Unauthorized`: User has no access rights to the target gym (`code: "UNAUTHORIZED_CONTEXT"`).
- `404 Not Found`: Target gym ID does not exist.

---

### 10. POST `/api/v1/auth/logout/`
- **Summary**: Invalidates current access token and optional refresh token by registering them in the server-side Redis denylist and removing them from the `auth_tokens` registry.
- **Authentication**: Required (`Bearer <JWT>`).
- **Request Body**:
| Field | Type | Required | Description |
|---|---|---|---|
| `refresh` | String | No | Refresh token to also revoke from the active session. |
- **Request Example**:
```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```
- **Success (200)**: `{"message": "Logged out successfully."}`
- **Error Responses**:
  - `401 Unauthorized`: Token is missing, expired, or already revoked (replays rejected).

---

### 10b. POST `/api/v1/auth/refresh/`
- **Aliases**: `POST /api/v1/auth/token/refresh/`, `POST /api/v1/token/refresh/`
- **Summary**: Exchanges an active refresh token for a fresh access & refresh token pair while preserving all tenant context claims (`context_type`, `gym_id`, and `scopes`). Rotates the refresh token (the previous refresh token is revoked).
- **Authentication**: None (refresh token passed in request body).
- **Rate Limiting**: Throttled via `TokenRefreshRateThrottle`.
- **Request Body**:
| Field | Type | Required | Description |
|---|---|---|---|
| `refresh` | String | Yes | Valid JWT refresh token. |
- **Request Example**:
```json
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```
- **Success (200 OK)**:
```json
{
  "message": "Token refreshed successfully.",
  "tokens": {
    "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "context_type": "gym",
    "gym_id": "31d57929-e58f-49b0-9bf7-fa5d07c08285",
    "gym_name": "Apex Fitness Club",
    "scopes": [
      "members:read",
      "members:edit"
    ]
  }
}
```
- **Error Responses**:
  - `400 Bad Request`: Missing or invalid refresh token payload (`code: "VALIDATION_ERROR"`).
  - `401 Unauthorized`: Token expired, malformed, or previously revoked (`code: "AUTHENTICATION_FAILED"`).
  - `429 Too Many Requests`: Refresh request rate limit exceeded (`code: "THROTTLED"`).

---

## User Profile APIs

### 11. GET `/api/v1/auth/me/`
- **Summary**: Retrieves user profile, active context status, and list of accessible gyms.
- **Authentication**: Required (`Bearer <JWT>`).
- **Success Response (200 OK)**:
```json
{
  "user": {
    "id": "b3e0c0fa-2384-48f8-b3d5-e357e62a0a20",
    "email": "alex.morgan@manygym.com",
    "first_name": "Alex",
    "last_name": "Morgan",
    "phone": "+14155552671",
    "status": "active",
    "is_verified": true,
    "profile": {
      "avatar_url": "https://cdn.manygym.com/avatars/alex.jpg",
      "address": "123 Market Street",
      "city": "San Francisco",
      "country": "United States",
      "date_of_birth": "1994-06-15",
      "sex": "male",
      "nationality": "American"
    }
  },
  "current_context": {
    "type": "personal",
    "gym_id": null,
    "gym_name": null,
    "profile_picture_url": null,
    "scopes": []
  },
  "accessible_gyms": [
    {
      "gym_id": "31d57929-e58f-49b0-9bf7-fa5d07c08285",
      "name": "Apex Fitness Club",
      "role": "Owner",
      "is_owner": true,
      "primary_type": "general_fitness_gym",
      "profile_picture_url": "https://cdn.manygym.com/gyms/apex.jpg"
    }
  ]
}
```

### 12. PATCH `/api/v1/auth/me/`
- **Summary**: Updates profile attributes.
- **Request Example**:
```json
{
  "first_name": "Alexandra",
  "phone": "+14155559988",
  "city": "San Francisco",
  "country": "United States"
}
```
- **Success (200)**: Returns updated user profile structure.

---

## Public Profile → About APIs

### 13. GET `/api/v1/users/profile/about/`
*(Convenient alias: `GET /api/v1/users/me/about/`)*

#### 1. Summary
Retrieves the complete Public Profile → About section for the authenticated user across all 5 structured categories:
1. **Personal Details**: `current_address`, `home_town`, `date_of_birth`, `gender`.
2. **Education**: list of education entries (`university_name`, `from_year`, `till_year`, `subject`, `graduated`).
3. **Hobbies**: list of user hobbies (free text strings).
4. **Contact info**: list of social links (`platform`, `link`), `phone_number`, and registered account `email` (read-only).
5. **Details about you**: `about_you` (bio up to 320 chars) and `favourite_quote` (quote up to 160 chars).

#### 2. Authentication & Authorization
- **Authentication**: Required (`Bearer <JWT>`).
- **Authorization**: Accessible to the authenticated user.

#### 3. Success Response (200 OK)
```json
{
  "user_id": "b3e0c0fa-2384-48f8-b3d5-e357e62a0a20",
  "first_name": "Alex",
  "last_name": "Morgan",
  "avatar_url": "https://cdn.manygym.com/avatars/alex.webp",
  "is_private": false,
  "personal_details": {
    "current_address": "House 12, Road 5, Dhanmondi, Dhaka",
    "home_town": "Chittagong",
    "date_of_birth": "1994-06-15",
    "gender": "male"
  },
  "education_list": [
    {
      "id": "18c2f1ab-2233-4455-6677-8899aabbccdd",
      "university_name": "Stanford University",
      "from_year": "2012-09-01",
      "till_year": "2016-06-15",
      "subject": "Kinesiology and Sports Science",
      "graduated": true,
      "created_at": "2026-10-12T12:00:00Z",
      "updated_at": "2026-10-12T12:00:00Z"
    }
  ],
  "hobbies": [
    "Weightlifting",
    "Trail Running",
    "Chess"
  ],
  "contact_info": {
    "social_links": [
      {
        "id": "29d4e2bc-3344-5566-7788-99aabbccddee",
        "platform": "instagram",
        "link": "https://instagram.com/alex_fitness",
        "created_at": "2026-10-12T12:00:00Z",
        "updated_at": "2026-10-12T12:00:00Z"
      },
      {
        "id": "30e5f3cd-4455-6677-8899-aabbccddeeff",
        "platform": "github",
        "link": "https://github.com/alexmorgan",
        "created_at": "2026-10-12T12:00:00Z",
        "updated_at": "2026-10-12T12:00:00Z"
      }
    ],
    "phone_number": "+14155552671",
    "email": "alex.morgan@manygym.com"
  },
  "details_about_you": {
    "about_you": "Dedicated strength athlete and fitness coach helping members transform their physical capacity and mental endurance.",
    "favourite_quote": "Discipline is choosing between what you want now and what you want most."
  }
}
```

#### 4. Error Responses
- `401 Unauthorized`: Invalid or missing authentication credentials.

---

### 14. PATCH / PUT `/api/v1/users/profile/about/`

#### 1. Summary
Atomic update of the authenticated user's Public Profile -> About details.
Accepts either structured nested sections (`personal_details`, `education_list`, `hobbies`, `contact_info`, `details_about_you`) or direct flat fields.

#### 2. Business Invariants & Rules Enforced
1. **Registered Email Immutability**: The email registered when creating an account **cannot be changed** via this or any profile update. Any `email` field passed in the request is safely discarded and the original email is preserved.
2. **Text Length Constraints**:
   - `about_you`: Maximum 320 characters.
   - `favourite_quote`: Maximum 160 characters.
3. **Education Validation**:
   - `university_name`, `from_year`, and `subject` are mandatory for each item.
   - `till_year` is optional (nullable if currently continuing).
   - When provided, `till_year >= from_year` is strictly enforced.
   - Accepts both standard ISO date (`YYYY-MM-DD`) and 4-digit year format (e.g. `"2018"` -> `2018-01-01`).
4. **Gender Selection**:
   - Restricted to standard choices: `male`, `female`, `other`, `prefer_not_to_say`.
5. **Social Platform Selection**:
   - Restricted to standard choices: `facebook`, `instagram`, `twitter_x`, `linkedin`, `youtube`, `tiktok`, `github`, `website`, `other`.

#### 3. Request Example (Nested Payload)
```json
{
  "personal_details": {
    "current_address": "450 Broadway, Apt 12B, New York, NY",
    "home_town": "Austin, Texas",
    "date_of_birth": "1993-08-20",
    "gender": "male"
  },
  "education_list": [
    {
      "university_name": "University of Texas at Austin",
      "from_year": "2011-09-01",
      "till_year": "2015-05-20",
      "subject": "Exercise Physiology",
      "graduated": true
    }
  ],
  "hobbies": ["Powerlifting", "Hiking", "Reading"],
  "contact_info": {
    "phone_number": "+15125550198",
    "social_links": [
      {
        "platform": "instagram",
        "link": "https://instagram.com/alex_lifts"
      },
      {
        "platform": "linkedin",
        "link": "https://linkedin.com/in/alex-morgan"
      }
    ]
  },
  "details_about_you": {
    "about_you": "Competitive powerlifter and strength conditioning coach passionate about progressive overload.",
    "favourite_quote": "Consistency over intensity."
  }
}
```

#### 4. Request Example (Flat Payload)
```json
{
  "current_address": "450 Broadway, Apt 12B, New York, NY",
  "home_town": "Austin, Texas",
  "date_of_birth": "1993-08-20",
  "gender": "male",
  "phone_number": "+15125550198",
  "hobbies": ["Powerlifting", "Hiking"],
  "about_you": "Competitive powerlifter and coach.",
  "favourite_quote": "Consistency over intensity."
}
```

#### 5. Success Response (200 OK)
Returns the complete preloaded `UserAboutResponseSerializer` object.

#### 6. Error Responses
- `400 Bad Request`: Validation failure (e.g. `about_you` > 320 chars, `favourite_quote` > 160 chars, invalid gender/platform choice, or `till_year < from_year`).
- `401 Unauthorized`: Missing or invalid Bearer JWT.

---

### 15. GET `/api/v1/users/{user_id}/profile/about/`
*(Convenient alias: `GET /api/v1/users/{user_id}/about/`)*

#### 1. Summary
Retrieves the public "About" profile of another user by their UUID.

#### 2. Privacy & Access Rules
- **Non-existent / Soft-Deleted**: Returns `404 Not Found`.
- **Deactivated**: Returns `400 Bad Request` ("This user account is deactivated.") unless viewed by the account owner.
- **Blocked Users**: Returns `403 Forbidden` ("You have been blocked by this user.") if the target user has blocked the requester.
- **Private Profiles**: Returns `403 Forbidden` ("This user account is private.") if `is_private=True` and the requester is not an approved follower.

#### 3. Success Response (200 OK)
Returns `UserAboutResponseSerializer` object.

---

### 16. GET & POST `/api/v1/users/profile/about/educations/`

#### 1. Summary
- `GET`: Lists all education records for the authenticated user, ordered by `from_year` descending.
- `POST`: Adds a single education record to the user's profile.

#### 2. POST Request Body
```json
{
  "university_name": "Massachusetts Institute of Technology",
  "from_year": "2016-09-01",
  "till_year": "2020-05-30",
  "subject": "Electrical Engineering & Computer Science",
  "graduated": true
}
```

#### 3. Success Response (201 Created)
```json
{
  "id": "e93f3456-789a-bcde-f012-3456789abcde",
  "university_name": "Massachusetts Institute of Technology",
  "from_year": "2016-09-01",
  "till_year": "2020-05-30",
  "subject": "Electrical Engineering & Computer Science",
  "graduated": true,
  "created_at": "2026-11-04T12:00:00Z",
  "updated_at": "2026-11-04T12:00:00Z"
}
```

---

### 17. PATCH & DELETE `/api/v1/users/profile/about/educations/{education_id}/`

#### 1. Summary
- `PATCH`: Partially updates an education record owned by the authenticated user.
- `DELETE`: Deletes an education record owned by the authenticated user.

#### 2. Success Response
- `PATCH`: `200 OK` with updated education record.
- `DELETE`: `200 OK` with `{"message": "Education record deleted successfully."}`.

---

### 18. GET & POST `/api/v1/users/profile/about/social-links/`

#### 1. Summary
- `GET`: Lists all social links for the authenticated user.
- `POST`: Adds a single social link to the user's profile.

#### 2. POST Request Body
```json
{
  "platform": "linkedin",
  "link": "https://linkedin.com/in/alexmorgan"
}
```

#### 3. Success Response (201 Created)
```json
{
  "id": "a1b2c3d4-e5f6-7890-1234-56789abcdef0",
  "platform": "linkedin",
  "link": "https://linkedin.com/in/alexmorgan",
  "created_at": "2026-11-04T12:00:00Z",
  "updated_at": "2026-11-04T12:00:00Z"
}
```

---

### 19. PATCH & DELETE `/api/v1/users/profile/about/social-links/{link_id}/`

#### 1. Summary
- `PATCH`: Partially updates a social link owned by the authenticated user.
- `DELETE`: Deletes a social link owned by the authenticated user.

#### 2. Success Response
- `PATCH`: `200 OK` with updated social link record.
- `DELETE`: `200 OK` with `{"message": "Social link deleted successfully."}`.

---

## Dynamic RBAC & Access Control APIs

### 13. GET `/api/v1/access-control/permissions/`
- **Summary**: Returns all system permissions grouped across the 9 core topics.
- **Authentication**: Required (`Bearer <JWT>`).
- **Success Response (200 OK)**:
```json
{
  "Studio": [
    {
      "id": "0c8af7e7-5adc-4bda-8636-aae0c3ee9c8f",
      "scope_code": "studio:manage",
      "name": "Manage Studio",
      "description": "Ability to create, edit, or cancel studio classes."
    },
    {
      "id": "f109815d-d313-4850-8f56-c146ce3eff38",
      "scope_code": "studio:read",
      "name": "View Studio",
      "description": "Access to view studio classes and schedules."
    }
  ],
  "Members": [
    {
      "id": "4f7cf80f-d154-436f-89c3-2d7b58fe8b00",
      "scope_code": "members:read",
      "name": "View Members",
      "description": "Read member directory and member details."
    },
    {
      "id": "850ed65e-7f29-4342-b770-3ec7bf7a7f39",
      "scope_code": "members:edit",
      "name": "Edit Members",
      "description": "Edit member profile, status, or subscription."
    },
    {
      "id": "6190cfd4-05b2-4aee-bf73-a2744d1c6607",
      "scope_code": "members:delete",
      "name": "Delete Members",
      "description": "Remove or cancel gym members."
    }
  ]
}
```

### 14. GET `/api/v1/access-control/roles/`
- **Summary**: Lists standard global roles (`Administrator`, `Staff`, `Trainer`) and gym-specific custom roles.
- **Query Parameter**: `?gym_id=<uuid>` (optional if already using Gym context token).

### 15. POST `/api/v1/access-control/roles/`
- **Summary**: Creates a custom role within the active gym with selected permission IDs.
- **Authorization**: Requires `people_roles:manage` scope or Gym Ownership.
- **Request Example**:
```json
{
  "name": "Front Desk Receptionist",
  "description": "Handles member check-ins and basic directory viewing.",
  "permission_ids": [
    "4f7cf80f-d154-436f-89c3-2d7b58fe8b00",
    "d28bfae7-3c5a-4ba4-8887-535c822195d2"
  ]
}
```
- **Success (201 Created)**: Returns created role with assigned permissions.

### 16. GET / PATCH / DELETE `/api/v1/access-control/roles/{id}/`
- **PATCH**: Updates custom role name, description, or assigned scopes.
- **DELETE**: Deletes an unused custom role (cannot delete roles currently assigned to staff).

### 17. GET `/api/v1/access-control/staff/`
- **Summary**: Lists all staff members assigned to the active gym.
- **Success Response (200 OK)**:
```json
[
  {
    "id": "771e843b-3321-4d1a-94f8-112233445566",
    "user": {
      "id": "41d08ffb-fe08-4b7f-a2cb-8af67424962a",
      "email": "sarah.trainer@manygym.com",
      "first_name": "Sarah",
      "last_name": "Connor",
      "phone": "+14155557766"
    },
    "gym_id": "31d57929-e58f-49b0-9bf7-fa5d07c08285",
    "role": {
      "id": "99aabbcc-1122-3344-5566-778899aabbcc",
      "name": "Trainer",
      "slug": "trainer",
      "is_custom": false
    },
    "status": "active",
    "invited_at": "2026-10-12T12:00:00Z",
    "joined_at": null
  }
]
```

### 18. POST `/api/v1/access-control/staff/invite/`
- **Summary**: Invites an existing registered user to join the gym under a specified role.
- **Request Example**:
```json
{
  "email": "sarah.trainer@manygym.com",
  "role_id": "99aabbcc-1122-3344-5566-778899aabbcc"
}
```
- **Success (201 Created)**: Returns staff assignment object.

### 19. PATCH `/api/v1/access-control/staff/{id}/`
- **Summary**: Toggles staff status (`active` / `inactive`).
- **Request Example**: `{"status": "inactive"}`

### 20. DELETE `/api/v1/access-control/staff/{id}/`
- **Summary**: Revokes gym staff assignment.
- **Success (200)**: `{"message": "Staff member access revoked."}`

---

## Interactive Swagger & ReDoc Documentation
- **Interactive Swagger UI**: [http://localhost:8090/api/v1/docs/](http://localhost:8090/api/v1/docs/)
- **ReDoc Documentation**: [http://localhost:8090/api/v1/redoc/](http://localhost:8090/api/v1/redoc/)
- **OpenAPI Schema (JSON)**: [http://localhost:8090/api/v1/schema/](http://localhost:8090/api/v1/schema/)
