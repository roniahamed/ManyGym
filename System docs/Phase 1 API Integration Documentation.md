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
6. [User Profile APIs](#user-profile-apis)
   - [GET /api/v1/auth/me/](#11-get-apiv1authme)
   - [PATCH /api/v1/auth/me/](#12-patch-apiv1authme)
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
- `400 Bad Request`: Invalid or expired OTP.
- `404 Not Found`: User not found.

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
- **Summary**: Invalidates current access token.
- **Authentication**: Required (`Bearer <JWT>`).
- **Success (200)**: `{"message": "Logged out successfully."}`

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
