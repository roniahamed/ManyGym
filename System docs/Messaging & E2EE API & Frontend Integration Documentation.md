# Messaging & End-to-End Encryption (E2EE) API & Frontend Integration Documentation

## 1. General Configuration

- **Base URL:** `/api/v1/messaging/`
- **WebSocket URL:** `ws://<host>/ws/chat/?token=<ACCESS_TOKEN>&gym_id=<OPTIONAL_GYM_UUID>`
- **Authentication:** Bearer JWT Token (`Authorization: Bearer <access_token>`)
- **Accepted Request Format:** `application/json`
- **Response Format:** `application/json`
- **Standard Headers:**
  - `Authorization: Bearer <access_token>` (Required for all endpoints)
  - `Accept: application/json`
  - `Content-Type: application/json`
  - `X-Gym-Context: <gym_uuid>` (Optional gym context UUID when acting as a Gym)

### Global Error Envelope

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
| `200 OK` | - | Request succeeded. |
| `201 Created` | - | Resource created successfully. |
| `400 Bad Request` | `VALIDATION_ERROR` | Invalid field type, missing required field, invalid cursor, or domain rule violation. |
| `401 Unauthorized` | `AUTHENTICATION_REQUIRED` | Missing, expired, or invalid Bearer JWT token. |
| `403 Forbidden` | `PERMISSION_DENIED` | Blocked user, invalid recovery code, account locked after max failed attempts, or unauthorized gym/conversation access. |
| `404 Not Found` | `RESOURCE_NOT_FOUND` | User, gym, conversation, message, cursor, or backup not found. |
| `405 Method Not Allowed` | `METHOD_NOT_ALLOWED` | HTTP method not supported on endpoint. |

---

## 2. Frontend UI Integration Requirements

1. **Find People to Message (Offcanvas / Modal Only):**
   - Do not create a dedicated page.
   - Open an offcanvas or modal from the messaging inbox / "New Message" button and call `GET /api/v1/messaging/people/search/`.
   - Results are strictly scoped to the user's **Follows + Followers**.
2. **Messenger-Style 5-Digit Recovery Code Flow:**
   - **First Device / Setup:** Prompt the user to set a 5-digit numeric recovery code (`"pin_length": 5`) via `POST /api/v1/messaging/keys/backup/`.
   - **New Device Login:** Check `GET /api/v1/messaging/keys/backup/status/`. If `has_backup` is `true`, prompt for the 5-digit recovery code and call `POST /api/v1/messaging/keys/backup/restore/` (optionally passing new device key fields to register the device in the same request).
   - **Message History Sync:** Fetch conversations via `GET /api/v1/messaging/conversations/` and paginate stored messages via `GET /api/v1/messaging/conversations/{conversation_id}/messages/` using `order=desc` and `before`/`after` cursors, decrypting locally with the restored keys.
3. **WhatsApp-Style Chat History Search:**
   - Generate blinded HMAC-SHA256 keyword tokens client-side using the restored `search_key`.
   - Call `GET` or `POST /api/v1/messaging/messages/search/` to receive conversations grouped with `match_count`, `latest_match_at`, and matched encrypted messages, then decrypt and highlight matches locally.

---

## 3. E2EE Device & Public Key Registry Endpoints

### 3.1. Register User Device Public Keys

- **Endpoint:** `POST /api/v1/messaging/keys/register/`

#### Request Payload Fields

| Field | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `device_id` | `string` | Yes | Strict string, max `100` chars, non-blank | Unique client device identifier. |
| `device_name` | `string` | No | Strict string, max `150` chars, default `""` | Human-readable device label. |
| `identity_key` | `string` | Yes | Strict string, non-blank | Base64 public identity key. |
| `signed_prekey` | `string` | Yes | Strict string, non-blank | Base64 public signed pre-key. |
| `signed_prekey_signature` | `string` | No | Strict string, default `""` | Base64 Ed25519 signature of `signed_prekey`. |
| `one_time_prekeys` | `array<string>` | No | List of non-blank strings, default `[]` | Pool of Base64 one-time public pre-keys. |

#### Request Payload (JSON)

```json
{
  "device_id": "alice-iphone-15",
  "device_name": "Alice iPhone",
  "identity_key": "dGVzdF9pZGVudGl0eV9rZXk=",
  "signed_prekey": "dGVzdF9zaWduZWRfcHJla2V5",
  "signed_prekey_signature": "dGVzdF9zaWduYXR1cmU=",
  "one_time_prekeys": ["b3BrMQ==", "b3BrMg=="]
}
```

#### Response Payload (200 OK)

| Field | Type | Description |
| :--- | :--- | :--- |
| `message` | `string` | Confirmation message. |
| `device_id` | `string` | Registered device identifier. |
| `algorithm` | `string` | Cryptographic algorithm (`"x25519"`). |
| `is_active` | `boolean` | Active key status. |

```json
{
  "message": "Device E2EE keys registered successfully.",
  "device_id": "alice-iphone-15",
  "algorithm": "x25519",
  "is_active": true
}
```

---

### 3.2. Register Gym Device Public Keys

- **Endpoint:** `POST /api/v1/messaging/keys/gym/register/`
- **Authorization:** Gym Owner or Active Staff with `messaging:send` scope.

#### Request Payload Fields

| Field | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `gym_id` | `string (uuid)` | Yes | Strict UUID | Target Gym UUID. |
| `device_id` | `string` | Yes | Strict string, max `100` chars, non-blank | Unique gym device identifier. |
| `device_name` | `string` | No | Strict string, max `150` chars, default `""` | Human-readable device label. |
| `identity_key` | `string` | Yes | Strict string, non-blank | Base64 gym public identity key. |
| `signed_prekey` | `string` | Yes | Strict string, non-blank | Base64 gym public signed pre-key. |
| `signed_prekey_signature` | `string` | No | Strict string, default `""` | Base64 signature of `signed_prekey`. |
| `one_time_prekeys` | `array<string>` | No | List of non-blank strings, default `[]` | Pool of Base64 one-time public pre-keys. |

#### Request Payload (JSON)

```json
{
  "gym_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "device_id": "gym-front-desk-01",
  "device_name": "Reception iPad",
  "identity_key": "Z3ltX2lkZW50aXR5X2tleQ==",
  "signed_prekey": "Z3ltX3NpZ25lZF9wcmVrZXk=",
  "signed_prekey_signature": "Z3ltX3NpZw==",
  "one_time_prekeys": []
}
```

#### Response Payload (200 OK)

```json
{
  "message": "Gym E2EE keys registered successfully.",
  "gym_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "device_id": "gym-front-desk-01",
  "is_active": true
}
```

---

### 3.3. Get User Public Key Bundle (Devices + Backup Key)

- **Endpoint:** `GET /api/v1/messaging/keys/user/{user_id}/`
- **Path Parameters:**
  - `user_id` (`string (uuid)`, required): Account `User.id` or `UserProfile.id`.

#### Response Payload Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `user_id` | `string` | Requested user identifier. |
| `devices` | `array<object>` | Active registered device public key bundles. |
| `devices[].device_id` | `string` | Device identifier. |
| `devices[].device_name` | `string` | Device display name. |
| `devices[].algorithm` | `string` | Key exchange algorithm (`"x25519"`). |
| `devices[].identity_key` | `string` | Base64 public identity key. |
| `devices[].signed_prekey` | `string` | Base64 signed pre-key. |
| `devices[].signed_prekey_signature` | `string` | Base64 signature. |
| `devices[].one_time_prekeys` | `array<string>` | Available one-time public pre-keys. |
| `backup_key` | `object \| null` | User's active E2EE backup public key metadata (`null` if not configured). |
| `backup_key.backup_public_key` | `string` | Base64 X25519 master/backup public key for cross-device history decryption. |
| `backup_key.backup_key_fingerprint` | `string` | SHA-256 fingerprint of `backup_public_key`. |
| `backup_key.key_version` | `integer` | Current backup key version. |

#### Response Payload (200 OK)

```json
{
  "user_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "devices": [
    {
      "device_id": "bob-android-pixel",
      "device_name": "Pixel 8",
      "algorithm": "x25519",
      "identity_key": "Ym9iX2lkZW50aXR5==",
      "signed_prekey": "Ym9iX3ByZWtleQ==",
      "signed_prekey_signature": "Ym9iX3NpZw==",
      "one_time_prekeys": ["b3BrXzE=", "b3BrXzI="]
    }
  ],
  "backup_key": {
    "backup_public_key": "Ym9iX2JhY2t1cF9wdWJsaWNfa2V5==",
    "backup_key_fingerprint": "f1a2b3c4d5e6f7a8",
    "key_version": 1
  }
}
```

---

### 3.4. Get Gym Public Key Bundle

- **Endpoint:** `GET /api/v1/messaging/keys/gym/{gym_id}/`
- **Path Parameters:**
  - `gym_id` (`string (uuid)`, required): Target Gym UUID.

#### Response Payload (200 OK)

```json
{
  "gym_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "devices": [
    {
      "device_id": "gym-front-desk-01",
      "device_name": "Reception iPad",
      "algorithm": "x25519",
      "identity_key": "Z3ltX2lkZW50aXR5X2tleQ==",
      "signed_prekey": "Z3ltX3NpZ25lZF9wcmVrZXk=",
      "signed_prekey_signature": "Z3ltX3NpZw==",
      "one_time_prekeys": []
    }
  ]
}
```

---

## 4. Messenger-Style 5-Digit Recovery Code Backup & New Device Restore

### 4.1. Get E2EE Backup Status

- **Endpoint:** `GET /api/v1/messaging/keys/backup/status/`

#### Response Payload Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `has_backup` | `boolean` | `true` if user has an active backup configured. |
| `secret_type` | `string \| null` | `"pin"` or `"passphrase"` (`null` if no backup). |
| `pin_length` | `integer` | Expected recovery code digit length (`5`). |
| `kdf_algorithm` | `string \| null` | `"pbkdf2_sha256"` or `"argon2id"` (`null` if no backup). |
| `kdf_iterations` | `integer \| null` | KDF iteration count (`null` if no backup). |
| `cipher_algorithm` | `string \| null` | `"chacha20_poly1305"` or `"aes_256_gcm"` (`null` if no backup). |
| `salt` | `string \| null` | Base64 KDF salt (`null` if no backup). |
| `backup_public_key` | `string \| null` | Base64 master/backup public key (`null` if no backup). |
| `backup_key_fingerprint` | `string \| null` | SHA-256 fingerprint of `backup_public_key`. |
| `key_version` | `integer` | Current backup version (`0` if no backup). |
| `failed_attempts` | `integer` | Current consecutive failed restore attempts. |
| `max_attempts` | `integer` | Maximum allowed failed attempts before lockout (default `10`). |
| `remaining_attempts` | `integer` | Remaining attempts before lockout. |
| `is_locked` | `boolean` | `true` if currently locked out. |
| `locked_until` | `string (datetime) \| null` | ISO-8601 unlock timestamp if locked. |
| `requires_auth_proof` | `boolean` | `true` if `auth_proof` / `recovery_code` verification is required on restore. |
| `has_recovery_bundle` | `boolean` | `true` if secondary recovery bundle is stored. |
| `last_restored_at` | `string (datetime) \| null` | ISO-8601 timestamp of last successful restore. |

#### Response Payload (200 OK — Configured)

```json
{
  "has_backup": true,
  "secret_type": "pin",
  "pin_length": 5,
  "kdf_algorithm": "pbkdf2_sha256",
  "kdf_iterations": 310000,
  "cipher_algorithm": "chacha20_poly1305",
  "salt": "cmFuZG9tX3NhbHRfMTZfYnl0ZXM=",
  "backup_public_key": "YmFja3VwX3B1YmxpY19rZXk=",
  "backup_key_fingerprint": "f1a2b3c4d5e6f7a8",
  "key_version": 1,
  "failed_attempts": 0,
  "max_attempts": 10,
  "remaining_attempts": 10,
  "is_locked": false,
  "locked_until": null,
  "requires_auth_proof": true,
  "has_recovery_bundle": false,
  "last_restored_at": null
}
```

#### Response Payload (200 OK — Not Configured)

```json
{
  "has_backup": false,
  "secret_type": null,
  "pin_length": 5,
  "kdf_algorithm": null,
  "kdf_iterations": null,
  "cipher_algorithm": null,
  "salt": null,
  "backup_public_key": null,
  "backup_key_fingerprint": null,
  "key_version": 0,
  "failed_attempts": 0,
  "max_attempts": 10,
  "remaining_attempts": 10,
  "is_locked": false,
  "locked_until": null,
  "requires_auth_proof": false,
  "has_recovery_bundle": false,
  "last_restored_at": null
}
```

---

### 4.2. Set or Update 5-Digit Recovery Code / E2EE Backup

- **Endpoint:** `POST /api/v1/messaging/keys/backup/` (or `PUT /api/v1/messaging/keys/backup/`)
- **Rule:** Provide either `recovery_code` (5-digit numeric string) **OR** all 4 client-encrypted bundle fields (`backup_public_key`, `encrypted_key_bundle`, `nonce`, `salt`).

#### Request Payload Fields

| Field | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `recovery_code` | `string` | Conditional | Strict string, exactly `5` digits (`^\d{5}$`), default `""` | 5-digit numeric recovery code. |
| `backup_public_key` | `string` | Conditional | Strict string, default `""` | Base64 X25519 master/backup public key. |
| `encrypted_key_bundle` | `string` | Conditional | Strict string, default `""` | Base64 AEAD ciphertext of key bundle. |
| `nonce` | `string` | Conditional | Strict string, max `255` chars, default `""` | Base64 AEAD nonce/IV. |
| `salt` | `string` | Conditional | Strict string, max `255` chars, default `""` | Base64 KDF salt (min `16` bytes decoded). |
| `kdf_algorithm` | `string` | No | `"pbkdf2_sha256"` or `"argon2id"`, default `"pbkdf2_sha256"` | KDF algorithm identifier. |
| `kdf_iterations` | `integer` | No | Strict integer, `10000`–`5000000`, default `310000` | KDF iteration count. |
| `cipher_algorithm` | `string` | No | `"chacha20_poly1305"` or `"aes_256_gcm"`, default `"chacha20_poly1305"` | Symmetric AEAD cipher. |
| `secret_type` | `string` | No | `"pin"` or `"passphrase"`, default `"pin"` | Secret input type. |
| `pin_length` | `integer` | No | Strict integer, min `5`, max `5`, default `5` | Numeric PIN length. |
| `auth_proof` | `string` | No | Strict string, max `255` chars, default `""` | Base64 client-derived authentication proof. |
| `recovery_encrypted_bundle` | `string` | No | Strict string, default `""` | Optional secondary backup encrypted with a recovery key. |
| `recovery_nonce` | `string` | No | Strict string, max `255` chars, default `""` | Nonce for `recovery_encrypted_bundle`. |
| `recovery_salt` | `string` | No | Strict string, max `255` chars, default `""` | Salt for `recovery_encrypted_bundle`. |
| `max_attempts` | `integer` | No | Strict integer, `3`–`20`, default `10` | Failed attempts allowed before 30-min lockout. |

#### Request Payload (JSON — 5-Digit Recovery Code Mode)

```json
{
  "recovery_code": "58294"
}
```

#### Request Payload (JSON — Zero-Knowledge Client Bundle Mode)

```json
{
  "backup_public_key": "YmFja3VwX3B1YmxpY19rZXk=",
  "encrypted_key_bundle": "ZW5jcnlwdGVkX2J1bmRsZV9jaXBoZXI=",
  "nonce": "MTJfYnl0ZV9ub25jZQ==",
  "salt": "MTZfYnl0ZV9zYWx0",
  "kdf_algorithm": "pbkdf2_sha256",
  "kdf_iterations": 310000,
  "cipher_algorithm": "chacha20_poly1305",
  "secret_type": "pin",
  "pin_length": 5,
  "auth_proof": "YmFzZTY0X2F1dGhfcHJvb2Y=",
  "recovery_encrypted_bundle": "",
  "recovery_nonce": "",
  "recovery_salt": "",
  "max_attempts": 10
}
```

#### Response Payload (200 OK)

| Field | Type | Description |
| :--- | :--- | :--- |
| `message` | `string` | Confirmation message. |
| `backup_public_key` | `string` | Base64 X25519 master/backup public key. |
| `backup_key_fingerprint` | `string` | SHA-256 fingerprint of `backup_public_key`. |
| `secret_type` | `string` | `"pin"` or `"passphrase"`. |
| `pin_length` | `integer` | `5`. |
| `key_version` | `integer` | Version counter (`1` on creation, increments on update). |
| `requires_auth_proof` | `boolean` | Whether restore requires `recovery_code` / `auth_proof` verification. |
| `has_recovery_bundle` | `boolean` | Whether secondary recovery bundle is stored. |
| `is_active` | `boolean` | Active backup flag. |

```json
{
  "message": "E2EE key backup configured successfully.",
  "backup_public_key": "YmFja3VwX3B1YmxpY19rZXk=",
  "backup_key_fingerprint": "f1a2b3c4d5e6f7a8",
  "secret_type": "pin",
  "pin_length": 5,
  "key_version": 1,
  "requires_auth_proof": true,
  "has_recovery_bundle": false,
  "is_active": true
}
```

---

### 4.3. Fetch E2EE Backup Metadata

- **Endpoint:** `GET /api/v1/messaging/keys/backup/`
- **Note:** When `requires_auth_proof` is `true`, `encrypted_key_bundle` and `nonce` are withheld from `GET` and returned only after verification via `POST /api/v1/messaging/keys/backup/restore/`.

#### Response Payload Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `backup_public_key` | `string` | Base64 master/backup public key. |
| `backup_key_fingerprint` | `string` | Key fingerprint. |
| `salt` | `string` | Base64 KDF salt. |
| `kdf_algorithm` | `string` | KDF algorithm. |
| `kdf_iterations` | `integer` | KDF iteration count. |
| `cipher_algorithm` | `string` | AEAD cipher algorithm. |
| `secret_type` | `string` | `"pin"` or `"passphrase"`. |
| `pin_length` | `integer` | `5`. |
| `key_version` | `integer` | Backup version. |
| `requires_auth_proof` | `boolean` | Indicates whether verification is required before bundle download. |
| `has_recovery_bundle` | `boolean` | Indicates whether secondary recovery bundle exists. |
| `failed_attempts` | `integer` | Current failed attempt count. |
| `max_attempts` | `integer` | Max attempts before lockout. |
| `remaining_attempts` | `integer` | Remaining attempts. |
| `last_restored_at` | `string (datetime) \| null` | Last restore timestamp. |
| `encrypted_key_bundle` | `string` | Included **only** when `requires_auth_proof` is `false`. |
| `nonce` | `string` | Included **only** when `requires_auth_proof` is `false`. |

#### Response Payload (200 OK)

```json
{
  "backup_public_key": "YmFja3VwX3B1YmxpY19rZXk=",
  "backup_key_fingerprint": "f1a2b3c4d5e6f7a8",
  "salt": "MTZfYnl0ZV9zYWx0",
  "kdf_algorithm": "pbkdf2_sha256",
  "kdf_iterations": 310000,
  "cipher_algorithm": "chacha20_poly1305",
  "secret_type": "pin",
  "pin_length": 5,
  "key_version": 1,
  "requires_auth_proof": true,
  "has_recovery_bundle": false,
  "failed_attempts": 0,
  "max_attempts": 10,
  "remaining_attempts": 10,
  "last_restored_at": null
}
```

---

### 4.4. Restore E2EE Backup on a New Device

- **Endpoint:** `POST /api/v1/messaging/keys/backup/restore/`

#### Request Payload Fields

| Field | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `recovery_code` | `string` | Conditional | Strict string, exactly `5` digits (`^\d{5}$`), default `""` | User's 5-digit recovery code. |
| `auth_proof` | `string` | Conditional | Strict string, max `255` chars, default `""` | Client-derived auth proof (if not sending `recovery_code`). |
| `success` | `boolean \| null` | No | Strict boolean or `null`, default `null` | Client-side decryption feedback when `requires_auth_proof` is `false`. |
| `use_recovery` | `boolean` | No | Strict boolean, default `false` | If `true`, fetches secondary `recovery_encrypted_bundle`. |
| `device_id` | `string` | No | Strict string, max `100` chars, default `""` | Optional new device ID to register atomically during restore. |
| `device_name` | `string` | No | Strict string, max `150` chars, default `""` | Optional new device name. |
| `identity_key` | `string` | No | Strict string, default `""` | Required if `device_id` is supplied for registration. |
| `signed_prekey` | `string` | No | Strict string, default `""` | Required if `device_id` is supplied for registration. |
| `signed_prekey_signature` | `string` | No | Strict string, default `""` | Optional signature for `signed_prekey`. |
| `one_time_prekeys` | `array<string>` | No | List of non-blank strings, default `[]` | Optional one-time pre-keys for the new device. |

#### Request Payload (JSON — New Device Restore + Device Registration)

```json
{
  "recovery_code": "58294",
  "device_id": "bob-pixel-9",
  "device_name": "Bob Pixel 9",
  "identity_key": "bmV3X2RldmljZV9pZGVudGl0eQ==",
  "signed_prekey": "bmV3X2RldmljZV9wcmVrZXk=",
  "signed_prekey_signature": "bmV3X3NpZw==",
  "one_time_prekeys": ["b3BrMQ=="]
}
```

#### Response Payload (200 OK — Standard Restore)

| Field | Type | Description |
| :--- | :--- | :--- |
| `message` | `string` | Confirmation message. |
| `mode` | `string` | `"secret"`. |
| `encrypted_key_bundle` | `string` | Base64 AEAD ciphertext of key bundle. |
| `nonce` | `string` | Base64 nonce/IV. |
| `salt` | `string` | Base64 KDF salt. |
| `kdf_algorithm` | `string` | KDF algorithm. |
| `kdf_iterations` | `integer` | KDF iteration count. |
| `cipher_algorithm` | `string` | Symmetric cipher algorithm. |
| `secret_type` | `string` | `"pin"` or `"passphrase"`. |
| `pin_length` | `integer` | `5`. |
| `backup_public_key` | `string` | Base64 master/backup public key. |
| `backup_key_fingerprint` | `string` | Key fingerprint. |
| `key_version` | `integer` | Backup version. |
| `last_restored_at` | `string (datetime)` | Timestamp of restore. |
| `registered_device` | `object \| null` | Registered new device summary (`null` if device fields omitted). |
| `registered_device.device_id` | `string` | Registered device ID. |
| `registered_device.device_name` | `string` | Device name. |
| `registered_device.algorithm` | `string` | `"x25519"`. |
| `registered_device.is_active` | `boolean` | `true`. |
| `restored_keys` | `object` | Included when `recovery_code` was supplied (`master_private_key`, `master_public_key`, `search_key`). |

```json
{
  "message": "E2EE key backup restored successfully.",
  "mode": "secret",
  "encrypted_key_bundle": "ZW5jcnlwdGVkX2J1bmRsZV9jaXBoZXI=",
  "nonce": "MTJfYnl0ZV9ub25jZQ==",
  "salt": "MTZfYnl0ZV9zYWx0",
  "kdf_algorithm": "pbkdf2_sha256",
  "kdf_iterations": 310000,
  "cipher_algorithm": "chacha20_poly1305",
  "secret_type": "pin",
  "pin_length": 5,
  "backup_public_key": "YmFja3VwX3B1YmxpY19rZXk=",
  "backup_key_fingerprint": "f1a2b3c4d5e6f7a8",
  "key_version": 1,
  "last_restored_at": "2026-11-25T14:00:00Z",
  "registered_device": {
    "device_id": "bob-pixel-9",
    "device_name": "Bob Pixel 9",
    "algorithm": "x25519",
    "is_active": true
  },
  "restored_keys": {
    "master_private_key": "bWFzdGVyX3ByaXZhdGVfa2V5==",
    "master_public_key": "YmFja3VwX3B1YmxpY19rZXk=",
    "search_key": "c2VhcmNoX2tleV8zMl9ieXRlcw=="
  }
}
```

#### Response Payload (200 OK — `use_recovery: true`)

```json
{
  "message": "Recovery key bundle fetched successfully.",
  "mode": "recovery",
  "recovery_encrypted_bundle": "cmVjb3ZlcnlfY2lwaGVydGV4dA==",
  "recovery_nonce": "cmVjb3Zlcnlfbm9uY2U=",
  "recovery_salt": "cmVjb3Zlcnlfc2FsdA==",
  "kdf_algorithm": "pbkdf2_sha256",
  "kdf_iterations": 310000,
  "cipher_algorithm": "chacha20_poly1305",
  "backup_public_key": "YmFja3VwX3B1YmxpY19rZXk=",
  "backup_key_fingerprint": "f1a2b3c4d5e6f7a8",
  "key_version": 1
}
```

#### Error Payload (403 Forbidden — Wrong Code / Lockout)

```json
{
  "code": "PERMISSION_DENIED",
  "message": "Invalid 5-digit recovery code / E2EE backup secret.",
  "details": {
    "failed_attempts": 1,
    "max_attempts": 10,
    "remaining_attempts": 9,
    "is_locked": false,
    "locked_until": null
  }
}
```

---

### 4.5. Change 5-Digit Recovery Code

- **Endpoint:** `POST /api/v1/messaging/keys/backup/change-code/`
- **Rule:** Provide either (`current_recovery_code` + `new_recovery_code`) **OR** (`encrypted_key_bundle` + `nonce` + `salt` with `current_auth_proof` / `new_auth_proof`). Preserves the underlying Master Keypair and Search Key so old message history remains decryptable.

#### Request Payload Fields

| Field | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `current_recovery_code` | `string` | Conditional | Strict string, exactly `5` digits (`^\d{5}$`), default `""` | Existing 5-digit recovery code. |
| `new_recovery_code` | `string` | Conditional | Strict string, exactly `5` digits (`^\d{5}$`), default `""` | New 5-digit recovery code. |
| `current_auth_proof` | `string` | Conditional | Strict string, max `255` chars, default `""` | Current client-derived auth proof. |
| `new_auth_proof` | `string` | Conditional | Strict string, max `255` chars, default `""` | New client-derived auth proof. |
| `encrypted_key_bundle` | `string` | Conditional | Strict string, default `""` | Re-encrypted bundle ciphertext. |
| `nonce` | `string` | Conditional | Strict string, max `255` chars, default `""` | New AEAD nonce. |
| `salt` | `string` | Conditional | Strict string, max `255` chars, default `""` | New KDF salt. |
| `kdf_algorithm` | `string` | No | `"pbkdf2_sha256"` or `"argon2id"`, default `"pbkdf2_sha256"` | KDF algorithm. |
| `kdf_iterations` | `integer` | No | Strict integer, `10000`–`5000000`, default `310000` | KDF iterations. |
| `cipher_algorithm` | `string` | No | `"chacha20_poly1305"` or `"aes_256_gcm"`, default `"chacha20_poly1305"` | Symmetric cipher. |
| `secret_type` | `string \| null` | No | `"pin"` or `"passphrase"` or `null`, default `null` | Optional secret type update. |
| `backup_public_key` | `string` | No | Strict string, default `""` | Optional rotated public key. |

#### Request Payload (JSON)

```json
{
  "current_recovery_code": "58294",
  "new_recovery_code": "73915"
}
```

#### Response Payload (200 OK)

| Field | Type | Description |
| :--- | :--- | :--- |
| `message` | `string` | Confirmation message. |
| `key_version` | `integer` | Incremented backup key version. |
| `secret_type` | `string` | `"pin"` or `"passphrase"`. |
| `pin_length` | `integer` | `5`. |
| `backup_key_fingerprint` | `string` | SHA-256 fingerprint of `backup_public_key`. |

```json
{
  "message": "E2EE backup PIN/password updated successfully.",
  "key_version": 2,
  "secret_type": "pin",
  "pin_length": 5,
  "backup_key_fingerprint": "f1a2b3c4d5e6f7a8"
}
```

---

### 4.6. Delete E2EE Backup

- **Endpoint:** `DELETE /api/v1/messaging/keys/backup/`

#### Response Payload (200 OK)

```json
{
  "message": "E2EE key backup deleted successfully."
}
```

---

## 5. Find People to Message (Follows + Followers Search)

- **Endpoint:** `GET /api/v1/messaging/people/search/`

#### Query Parameters

| Parameter | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `q` | `string` | No | Optional keyword | Case-insensitive filter on `first_name`, `last_name`, full name, or `email`. |
| `search` | `string` | No | Optional alias for `q` | Used if `q` is omitted. |
| `limit` | `integer` | No | Min `1`, max `50`, default `20` | Maximum number of people returned. |

#### Response Payload Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `count` | `integer` | Number of returned people. |
| `results` | `array<object>` | Deduplicated list of people from Follows + Followers. |
| `results[].user_id` | `string (uuid)` | User account UUID. |
| `results[].profile_id` | `string (uuid) \| null` | UserProfile UUID. |
| `results[].email` | `string` | User email address. |
| `results[].first_name` | `string` | First name. |
| `results[].last_name` | `string` | Last name. |
| `results[].full_name` | `string` | Full display name. |
| `results[].avatar_url` | `string \| null` | Profile avatar URL. |
| `results[].is_private` | `boolean` | Private profile flag. |
| `results[].is_following` | `boolean` | `true` if authenticated user follows this person. |
| `results[].is_follower` | `boolean` | `true` if this person follows authenticated user. |
| `results[].relationship` | `string` | `"mutual"`, `"following"`, or `"follower"`. |
| `results[].can_message` | `boolean` | Whether direct messaging is permitted by recipient's `who_can_message` setting. |
| `results[].conversation_id` | `string (uuid) \| null` | Existing `user_to_user` conversation UUID if already started, else `null`. |
| `results[].has_e2ee_keys` | `boolean` | `true` if user has active device or backup E2EE public keys. |

#### Response Payload (200 OK)

```json
{
  "count": 2,
  "results": [
    {
      "user_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "profile_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
      "email": "bob@example.com",
      "first_name": "Bob",
      "last_name": "Builder",
      "full_name": "Bob Builder",
      "avatar_url": "https://cdn.manygym.com/avatars/bob.jpg",
      "is_private": false,
      "is_following": true,
      "is_follower": true,
      "relationship": "mutual",
      "can_message": true,
      "conversation_id": "d4e5f6a7-b8c9-0123-def0-123456789012",
      "has_e2ee_keys": true
    },
    {
      "user_id": "e5f6a7b8-c9d0-1234-ef01-234567890123",
      "profile_id": "f6a7b8c9-d0e1-2345-f012-345678901234",
      "email": "charlie@example.com",
      "first_name": "Charlie",
      "last_name": "Brown",
      "full_name": "Charlie Brown",
      "avatar_url": null,
      "is_private": false,
      "is_following": false,
      "is_follower": true,
      "relationship": "follower",
      "can_message": false,
      "conversation_id": null,
      "has_e2ee_keys": false
    }
  ]
}
```

---

## 6. Conversations Endpoints

### 6.1. List Conversations

- **Endpoint:** `GET /api/v1/messaging/conversations/`

#### Query Parameters

| Parameter | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `gym_id` | `string (uuid)` | No | Valid Gym UUID | Lists conversations for the specified Gym context instead of personal user. |
| `limit` | `integer` | No | `1`–`100` | Optional max conversations to return. |

#### Response Payload Fields (Array of Conversation Objects)

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `string (uuid)` | Conversation UUID. |
| `conversation_type` | `string` | `"user_to_user"`, `"user_to_gym"`, or `"gym_to_gym"`. |
| `user_a` | `string (uuid) \| null` | User A UUID. |
| `user_b` | `string (uuid) \| null` | User B UUID. |
| `gym_a` | `string (uuid) \| null` | Gym A UUID. |
| `gym_b` | `string (uuid) \| null` | Gym B UUID. |
| `participants` | `array<object>` | Participant state list. |
| `participants[].id` | `string (uuid)` | Participant record UUID. |
| `participants[].participant_type` | `string` | `"user"` or `"gym"`. |
| `participants[].user` | `string (uuid) \| null` | User UUID. |
| `participants[].user_id` | `string (uuid) \| null` | User UUID. |
| `participants[].profile_id` | `string (uuid) \| null` | UserProfile UUID. |
| `participants[].user_email` | `string \| null` | User email. |
| `participants[].user_full_name` | `string \| null` | User full name. |
| `participants[].avatar_url` | `string \| null` | User avatar URL. |
| `participants[].gym` | `string (uuid) \| null` | Gym UUID. |
| `participants[].gym_name` | `string \| null` | Gym name. |
| `participants[].unread_count` | `integer` | Unread message count for this participant. |
| `participants[].last_read_at` | `string (datetime) \| null` | Last read timestamp. |
| `participants[].is_muted` | `boolean` | Mute state. |
| `other_party` | `object \| null` | UI helper for the other party (`type: "user"` has `id`, `user_id`, `profile_id`, `avatar_url`, `name`, `email`; `type: "gym"` has `id`, `name`, `profile_picture_url`). |
| `last_message_at` | `string (datetime) \| null` | Timestamp of most recent message. |
| `last_message_preview` | `string` | Default `"🔒 Encrypted Message"` (or moment reply preview). |
| `created_at` | `string (datetime)` | Creation timestamp. |

#### Response Payload (200 OK)

```json
[
  {
    "id": "c1d2e3f4-a5b6-7890-1234-567890abcdef",
    "conversation_type": "user_to_user",
    "user_a": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "user_b": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
    "gym_a": null,
    "gym_b": null,
    "participants": [
      {
        "id": "11111111-2222-3333-4444-555555555555",
        "participant_type": "user",
        "user": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "profile_id": "22222222-3333-4444-5555-666666666666",
        "user_email": "alice@example.com",
        "user_full_name": "Alice Smith",
        "avatar_url": "https://cdn.manygym.com/avatars/alice.jpg",
        "gym": null,
        "gym_name": null,
        "unread_count": 0,
        "last_read_at": "2026-11-25T10:00:00Z",
        "is_muted": false
      },
      {
        "id": "33333333-4444-5555-6666-777777777777",
        "participant_type": "user",
        "user": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "user_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "profile_id": "44444444-5555-6666-7777-888888888888",
        "user_email": "bob@example.com",
        "user_full_name": "Bob Builder",
        "avatar_url": "https://cdn.manygym.com/avatars/bob.jpg",
        "gym": null,
        "gym_name": null,
        "unread_count": 1,
        "last_read_at": null,
        "is_muted": false
      }
    ],
    "other_party": {
      "type": "user",
      "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "user_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "profile_id": "44444444-5555-6666-7777-888888888888",
      "avatar_url": "https://cdn.manygym.com/avatars/bob.jpg",
      "name": "Bob Builder",
      "email": "bob@example.com"
    },
    "last_message_at": "2026-11-25T10:15:00Z",
    "last_message_preview": "🔒 Encrypted Message",
    "created_at": "2026-11-25T09:00:00Z"
  }
]
```

---

### 6.2. Create or Retrieve Conversation

- **Endpoint:** `POST /api/v1/messaging/conversations/`

#### Request Payload Fields

| Field | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `conversation_type` | `string` | No | `"user_to_user"`, `"user_to_gym"`, `"gym_to_user"`, `"gym_to_gym"`, or `""` | Auto-detected if omitted. |
| `target_user_id` | `string (uuid) \| null` | Conditional | Strict UUID | Recipient `User.id` or `UserProfile.id`. |
| `target_gym_id` | `string (uuid) \| null` | Conditional | Strict UUID | Recipient Gym UUID. |
| `source_gym_id` | `string (uuid) \| null` | Conditional | Strict UUID | Initiating Gym UUID (for `gym_to_user` or `gym_to_gym`). |

#### Request Payload (JSON)

```json
{
  "conversation_type": "user_to_user",
  "target_user_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901"
}
```

#### Response Payload (201 Created)

Returns the same single Conversation object structure as `GET /api/v1/messaging/conversations/`.

---

### 6.3. Get Conversation Detail

- **Endpoint:** `GET /api/v1/messaging/conversations/{conversation_id}/`
- **Path Parameters:**
  - `conversation_id` (`string (uuid)`, required): Conversation UUID.
- **Query Parameters:**
  - `gym_id` (`string (uuid)`, optional): Optional Gym context UUID.
- **Response (200 OK):** Returns the single Conversation object structure as `GET /api/v1/messaging/conversations/`.

---

## 7. Encrypted Message History, Sending & Read Receipts

### 7.1. Get Encrypted Message History (With New-Device Cursor Pagination)

- **Endpoint:** `GET /api/v1/messaging/conversations/{conversation_id}/messages/`
- **Path Parameters:**
  - `conversation_id` (`string (uuid)`, required): Conversation UUID.

#### Query Parameters

| Parameter | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `limit` | `integer` | No | Min `1`, max `100`, default `50` | Page size. |
| `before` | `string` | No | Message UUID or ISO-8601 datetime | Fetch messages strictly older than cursor. |
| `after` | `string` | No | Message UUID or ISO-8601 datetime | Fetch messages strictly newer than cursor. |
| `order` | `string` | No | `"asc"` or `"desc"`, default `"asc"` | Sort direction (`"desc"` returns newest first). |
| `gym_id` | `string (uuid)` | No | Valid Gym UUID | Optional Gym context UUID. |

#### Response Payload Fields (Array of EncryptedMessage Objects)

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `string (uuid)` | Message UUID. |
| `conversation_id` | `string (uuid)` | Parent conversation UUID. |
| `sender_type` | `string` | `"user"` or `"gym"`. |
| `sender_user_id` | `string (uuid) \| null` | Sender user UUID. |
| `sender_user_full_name` | `string \| null` | Sender user full name. |
| `sender_gym_id` | `string (uuid) \| null` | Sender gym UUID. |
| `sender_gym_name` | `string \| null` | Sender gym name. |
| `sender_device_id` | `string` | Originating device identifier. |
| `ciphertext` | `string` | Base64 encrypted message payload. |
| `nonce` | `string` | Base64 nonce/IV. |
| `ephemeral_public_key` | `string` | Base64 ephemeral X25519 public key. |
| `recipient_key_fingerprint` | `string` | Public key fingerprint used. |
| `encrypted_keys` | `object` | Map of wrapped session keys (per device ID, `backup:<user_id>`, or gym staff). |
| `delivery_status` | `string` | `"sent"`, `"delivered"`, or `"read"`. |
| `sent_at` | `string (datetime)` | Sent timestamp. |
| `delivered_at` | `string (datetime) \| null` | Delivered timestamp. |
| `read_at` | `string (datetime) \| null` | Read timestamp. |

#### Response Payload (200 OK)

```json
[
  {
    "id": "e4f5a6b7-c8d9-0123-ef01-234567890123",
    "conversation_id": "c1d2e3f4-a5b6-7890-1234-567890abcdef",
    "sender_type": "user",
    "sender_user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "sender_user_full_name": "Alice Smith",
    "sender_gym_id": null,
    "sender_gym_name": null,
    "sender_device_id": "alice-iphone-15",
    "ciphertext": "aGVsbG8gd29ybGQgZW5jcnlwdGVkIQ==",
    "nonce": "bm9uY2V2YWx1ZQ==",
    "ephemeral_public_key": "ZXBoZW1lcmFsX2tleQ==",
    "recipient_key_fingerprint": "f1a2b3c4d5e6f7a8",
    "encrypted_keys": {
      "backup:b2c3d4e5-f6a7-8901-bcde-f12345678901": {
        "ciphertext": "d3JhcHBlZF9mb3JfYm9iX2JhY2t1cA==",
        "nonce": "bm9uY2VfYm9i",
        "ephemeral_public_key": "ZXBoX2JvYg=="
      }
    },
    "delivery_status": "sent",
    "sent_at": "2026-11-25T10:15:00Z",
    "delivered_at": null,
    "read_at": null
  }
]
```

---

### 7.2. Send Encrypted Message

- **Endpoint:** `POST /api/v1/messaging/conversations/{conversation_id}/messages/`
- **Path Parameters:**
  - `conversation_id` (`string (uuid)`, required): Conversation UUID.
- **Query Parameters:**
  - `gym_id` (`string (uuid)`, optional): Optional Gym context UUID.

#### Request Payload Fields

| Field | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `ciphertext` | `string` | Yes | Strict string, non-blank | Base64 encrypted message payload. |
| `nonce` | `string` | Yes | Strict string, max `255` chars, non-blank | Base64 nonce/IV. |
| `ephemeral_public_key` | `string` | No | Strict string, default `""` | Base64 ephemeral X25519 public key. |
| `recipient_key_fingerprint` | `string` | No | Strict string, default `""` | Target key fingerprint. |
| `sender_device_id` | `string` | No | Strict string, max `100` chars, default `""` | Sender device ID. |
| `encrypted_keys` | `object` | No | Dict, default `{}` | Per-device and `backup:<user_id>` wrapped keys. |
| `sender_type` | `string` | No | `"user"` or `"gym"`, default `"user"` | Sender entity type. |
| `sender_gym_id` | `string (uuid) \| null` | Conditional | Strict UUID | Required when `sender_type` is `"gym"` (if not in query/header). |
| `search_tokens` | `array<string>` | No | Max `200` items, each `1`–`128` chars, default `[]` | Blinded HMAC-SHA256 keyword tokens for sender search. |
| `shared_search_tokens` | `array<string>` | No | Max `200` items, each `1`–`128` chars, default `[]` | Blinded HMAC-SHA256 tokens from a shared conversation search key. |

#### Request Payload (JSON)

```json
{
  "ciphertext": "aGVsbG8gd29ybGQgZW5jcnlwdGVkIQ==",
  "nonce": "bm9uY2V2YWx1ZQ==",
  "ephemeral_public_key": "ZXBoZW1lcmFsX2tleQ==",
  "recipient_key_fingerprint": "f1a2b3c4d5e6f7a8",
  "sender_device_id": "alice-iphone-15",
  "encrypted_keys": {
    "backup:b2c3d4e5-f6a7-8901-bcde-f12345678901": {
      "ciphertext": "d3JhcHBlZF9mb3JfYm9iX2JhY2t1cA==",
      "nonce": "bm9uY2VfYm9i",
      "ephemeral_public_key": "ZXBoX2JvYg=="
    }
  },
  "sender_type": "user",
  "sender_gym_id": null,
  "search_tokens": [
    "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
  ],
  "shared_search_tokens": []
}
```

#### Response Payload (201 Created)

Returns the created EncryptedMessage object structure shown in Section 7.1.

---

### 7.3. Mark Conversation as Read

- **Endpoint:** `POST /api/v1/messaging/conversations/{conversation_id}/read/`
- **Path Parameters:**
  - `conversation_id` (`string (uuid)`, required): Conversation UUID.

#### Request Payload Fields

| Field | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `gym_id` | `string (uuid) \| null` | No | Strict UUID | Optional Gym context UUID. |
| `up_to_message_id` | `string (uuid) \| null` | No | Strict UUID | Latest message UUID read by user. |

#### Request Payload (JSON)

```json
{
  "gym_id": null,
  "up_to_message_id": "e4f5a6b7-c8d9-0123-ef01-234567890123"
}
```

#### Response Payload (200 OK)

```json
{
  "message": "Conversation marked as read.",
  "read_count": 3
}
```

---

## 8. WhatsApp-Style Chat History Search & Token Indexing

### 8.1. Search Chat History (GET)

- **Endpoint:** `GET /api/v1/messaging/messages/search/`

#### Query Parameters

| Parameter | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `token` | `string` | Conditional | `1`–`128` chars | Single blinded HMAC-SHA256 keyword token. |
| `tokens` | `string` | Conditional | Comma-separated or repeated params, `1`–`20` tokens | Multiple blinded keyword tokens. |
| `match_mode` | `string` | No | `"all"` or `"any"`, default `"all"` | `"all"` matches messages with every token; `"any"` matches any token. |
| `conversation_id` | `string (uuid)` | No | Valid Conversation UUID | Restrict search to one conversation. |
| `gym_id` | `string (uuid)` | No | Valid Gym UUID | Optional Gym context UUID. |
| `limit` | `integer` | No | `1`–`50`, default `20` | Max matching conversations returned. |
| `matches_per_chat` | `integer` | No | `1`–`20`, default `5` | Max matched messages returned per conversation. |

---

### 8.2. Search Chat History (POST)

- **Endpoint:** `POST /api/v1/messaging/messages/search/`

#### Request Payload Fields

| Field | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `tokens` | `array<string>` | Yes | `1`–`20` items, each `1`–`128` chars | Blinded HMAC-SHA256 keyword tokens. |
| `match_mode` | `string` | No | `"all"` or `"any"`, default `"all"` | Token matching mode. |
| `conversation_id` | `string (uuid) \| null` | No | Strict UUID, default `null` | Optional single-conversation filter. |
| `gym_id` | `string (uuid) \| null` | No | Strict UUID, default `null` | Optional Gym context UUID. |
| `limit` | `integer` | No | Strict integer, `1`–`50`, default `20` | Max conversations returned. |
| `matches_per_chat` | `integer` | No | Strict integer, `1`–`20`, default `5` | Max matched messages per conversation. |

#### Request Payload (JSON)

```json
{
  "tokens": [
    "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a"
  ],
  "match_mode": "all",
  "conversation_id": null,
  "gym_id": null,
  "limit": 20,
  "matches_per_chat": 5
}
```

#### Response Payload Fields (GET & POST — 200 OK)

| Field | Type | Description |
| :--- | :--- | :--- |
| `total_conversations` | `integer` | Number of matching conversations returned. |
| `total_matches` | `integer` | Total matched messages across returned conversations. |
| `results` | `array<object>` | Grouped conversation matches ordered by `latest_match_at` descending. |
| `results[].conversation` | `object` | Full Conversation object (same shape as Section 6.1). |
| `results[].match_count` | `integer` | Total matched messages inside this conversation. |
| `results[].latest_match_at` | `string (datetime)` | Timestamp of most recent matched message in this conversation. |
| `results[].matches` | `array<object>` | Array of matched EncryptedMessage objects (same shape as Section 7.1). |

#### Response Payload (200 OK)

```json
{
  "total_conversations": 1,
  "total_matches": 2,
  "results": [
    {
      "conversation": {
        "id": "c1d2e3f4-a5b6-7890-1234-567890abcdef",
        "conversation_type": "user_to_user",
        "user_a": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        "user_b": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
        "gym_a": null,
        "gym_b": null,
        "participants": [],
        "other_party": {
          "type": "user",
          "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
          "user_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
          "profile_id": "44444444-5555-6666-7777-888888888888",
          "avatar_url": "https://cdn.manygym.com/avatars/bob.jpg",
          "name": "Bob Builder",
          "email": "bob@example.com"
        },
        "last_message_at": "2026-11-25T10:15:00Z",
        "last_message_preview": "🔒 Encrypted Message",
        "created_at": "2026-11-25T09:00:00Z"
      },
      "match_count": 2,
      "latest_match_at": "2026-11-25T10:15:00Z",
      "matches": [
        {
          "id": "e4f5a6b7-c8d9-0123-ef01-234567890123",
          "conversation_id": "c1d2e3f4-a5b6-7890-1234-567890abcdef",
          "sender_type": "user",
          "sender_user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
          "sender_user_full_name": "Alice Smith",
          "sender_gym_id": null,
          "sender_gym_name": null,
          "sender_device_id": "alice-iphone-15",
          "ciphertext": "aGVsbG8gd29ybGQgZW5jcnlwdGVkIQ==",
          "nonce": "bm9uY2V2YWx1ZQ==",
          "ephemeral_public_key": "ZXBoZW1lcmFsX2tleQ==",
          "recipient_key_fingerprint": "f1a2b3c4d5e6f7a8",
          "encrypted_keys": {},
          "delivery_status": "sent",
          "sent_at": "2026-11-25T10:15:00Z",
          "delivered_at": null,
          "read_at": null
        }
      ]
    }
  ]
}
```

---

### 8.3. Batch Index Search Tokens for Received / Restored Messages

- **Endpoint:** `POST /api/v1/messaging/search/index/`

#### Request Payload Fields

| Field | Type | Required | Constraints / Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `gym_id` | `string (uuid) \| null` | No | Strict UUID, default `null` | Optional Gym context UUID. |
| `items` | `array<object>` | Yes | `1`–`100` items | Messages and their blinded tokens. |
| `items[].message_id` | `string (uuid)` | Yes | Strict UUID | Message UUID accessible to the user/gym. |
| `items[].tokens` | `array<string>` | Yes | `1`–`200` items, each `1`–`128` chars | Blinded HMAC-SHA256 tokens for this message. |

#### Request Payload (JSON)

```json
{
  "gym_id": null,
  "items": [
    {
      "message_id": "e4f5a6b7-c8d9-0123-ef01-234567890123",
      "tokens": [
        "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
      ]
    }
  ]
}
```

#### Response Payload (200 OK)

```json
{
  "message": "Search tokens indexed successfully.",
  "indexed_count": 1
}
```

---

## 9. Real-Time WebSocket Protocol

- **URL:** `ws://<host>/ws/chat/?token=<ACCESS_TOKEN>&gym_id=<OPTIONAL_GYM_UUID>`
- **Alternative Auth Header:** `Authorization: Bearer <ACCESS_TOKEN>`

### 9.1. Client-to-Server Actions (JSON)

| Action | Fields |
| :--- | :--- |
| `join_conversation` | `action`, `conversation_id` |
| `leave_conversation` | `action`, `conversation_id` |
| `send_message` | `action`, `conversation_id`, `ciphertext`, `nonce`, `ephemeral_public_key`, `recipient_key_fingerprint`, `sender_device_id`, `encrypted_keys`, `sender_type`, `search_tokens`, `shared_search_tokens` |
| `typing` | `action`, `conversation_id`, `is_typing` |
| `mark_read` | `action`, `conversation_id` |
| `ping` | `action` |

```json
{
  "action": "send_message",
  "conversation_id": "c1d2e3f4-a5b6-7890-1234-567890abcdef",
  "ciphertext": "aGVsbG8gd29ybGQgZW5jcnlwdGVkIQ==",
  "nonce": "bm9uY2V2YWx1ZQ==",
  "ephemeral_public_key": "ZXBoZW1lcmFsX2tleQ==",
  "recipient_key_fingerprint": "f1a2b3c4d5e6f7a8",
  "sender_device_id": "alice-iphone-15",
  "encrypted_keys": {},
  "sender_type": "user",
  "search_tokens": [
    "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
  ],
  "shared_search_tokens": []
}
```

### 9.2. Server-to-Client Events (JSON)

| Event `type` | Payload Fields |
| :--- | :--- |
| `connection_established` | `type`, `user_id`, `email`, `gym_id` |
| `joined_conversation` | `type`, `conversation_id` |
| `left_conversation` | `type`, `conversation_id` |
| `message_sent_ack` | `type`, `message_id`, `conversation_id`, `sent_at` |
| `new_message` | `type`, `message` (`id`, `conversation_id`, `sender_type`, `sender_user_id`, `sender_gym_id`, `sender_gym_name`, `sender_device_id`, `ciphertext`, `nonce`, `ephemeral_public_key`, `recipient_key_fingerprint`, `encrypted_keys`, `delivery_status`, `sent_at`) |
| `incoming_notification` | `type`, `message` (same object as `new_message.message`) |
| `typing_indicator` | `type`, `data` (`conversation_id`, `user_id`, `sender_name`, `gym_id`, `is_typing`) |
| `read_receipt` | `type`, `data` (`conversation_id`, `read_by_user_id`, `read_by_gym_id`, `timestamp`, `read_count`) |
| `pong` | `type` |
| `error` | `type`, `message` |

```json
{
  "type": "new_message",
  "message": {
    "id": "e4f5a6b7-c8d9-0123-ef01-234567890123",
    "conversation_id": "c1d2e3f4-a5b6-7890-1234-567890abcdef",
    "sender_type": "user",
    "sender_user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "sender_gym_id": null,
    "sender_gym_name": null,
    "sender_device_id": "alice-iphone-15",
    "ciphertext": "aGVsbG8gd29ybGQgZW5jcnlwdGVkIQ==",
    "nonce": "bm9uY2V2YWx1ZQ==",
    "ephemeral_public_key": "ZXBoZW1lcmFsX2tleQ==",
    "recipient_key_fingerprint": "f1a2b3c4d5e6f7a8",
    "encrypted_keys": {},
    "delivery_status": "sent",
    "sent_at": "2026-11-25T10:15:00Z"
  }
}
```
