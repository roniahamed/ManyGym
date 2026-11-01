# Phase 10: Real-time End-to-End Encrypted (E2EE) Messaging Documentation

## Overview & Architecture
The Phase 10 module implements the high-performance, privacy-first **End-to-End Encrypted (E2EE) Real-time Messaging System** for Many Gym. The system supports three direct messaging channels:
1. **Manygym User to Manygym User (`user_to_user`)**
2. **Manygym User to Gym (`user_to_gym`)**
3. **Gym to Gym (`gym_to_gym`)**

### Cryptographic & Privacy Guarantee
- **Zero-Knowledge Ciphertext Persistence**: Plaintext messages **never** touch the Many Gym servers. All payloads are encrypted locally on the sender's client device and decrypted exclusively on the recipient's client device.
- **Hybrid Cryptography**:
  - **X25519 (Curve25519 Diffie-Hellman)** for asymmetric key exchange and ephemeral sessions.
  - **Ed25519** digital signatures for verifying Signed Pre-Keys ($SPK$).
  - **HKDF-SHA256** for deriving 256-bit symmetric session keys.
  - **ChaCha20-Poly1305 / AES-256-GCM** for authenticated symmetric ciphertext encryption.
- **Real-Time Multiplexing**: Powered by **Django Channels**, **ASGI ProtocolTypeRouter**, and **Redis Channel Layers**, enabling live ciphertext pushes, typing indicators (`typing_started`/`typing_stopped`), and read receipts.

---

## Architectural Components

```text
apps/messaging/
├── models.py         # UserDeviceKey, GymDeviceKey, Conversation, ConversationParticipant, EncryptedMessage, MessageDeliveryReceipt
├── crypto.py         # Asymmetric & symmetric E2EE cryptographic utilities (X25519, Ed25519, ChaCha20Poly1305, HKDF)
├── services.py       # Domain write logic: key bundles, conversation initiation, message dispatch & realtime broadcasting
├── selectors.py      # Optimized N+1 safe queries for conversations, message histories, and public key bundles
├── permissions.py    # Gym settings policy enforcement (EVERYONE, MEMBERS_ONLY), blocklists, and gym staff scopes
├── consumers.py      # AsyncJsonWebsocketConsumer handling live WebSockets, JWT authentication, and room multiplexing
├── routing.py        # WebSocket route patterns (/ws/chat/)
└── rest_api/v1/
    ├── serializers.py
    ├── views.py
    └── urls.py
```

---

## REST API Specification

### 1. Register User Device Public Keys
- **Endpoint**: `POST /api/v1/messaging/keys/register/`
- **Auth**: Bearer JWT (Personal context)
- **Request Body**:
  ```json
  {
    "device_id": "alice-iphone-15",
    "device_name": "Alice iPhone",
    "identity_key": "dGVzdF9pZGVudGl0eV9rZXk==",
    "signed_prekey": "dGVzdF9zaWduZWRfcHJla2V5==",
    "signed_prekey_signature": "dGVzdF9zaWduYXR1cmU==",
    "one_time_prekeys": ["b3BrMQ==", "b3BrMg=="]
  }
  ```
- **Response (200 OK)**:
  ```json
  {
    "message": "Device E2EE keys registered successfully.",
    "device_id": "alice-iphone-15",
    "algorithm": "x25519",
    "is_active": true
  }
  ```

---

### 2. Register Gym Public Keys
- **Endpoint**: `POST /api/v1/messaging/keys/gym/register/`
- **Auth**: Bearer JWT (Requires Gym Owner or Staff with `messaging:send` scope)
- **Request Body**:
  ```json
  {
    "gym_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "device_id": "gym-front-desk-01",
    "device_name": "Reception iPad",
    "identity_key": "Z3ltX2lkZW50aXR5X2tleQ==",
    "signed_prekey": "Z3ltX3NpZ25lZF9wcmVrZXk==",
    "signed_prekey_signature": "Z3ltX3NpZw=="
  }
  ```
- **Response (200 OK)**:
  ```json
  {
    "message": "Gym E2EE keys registered successfully.",
    "gym_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "device_id": "gym-front-desk-01",
    "is_active": true
  }
  ```

---

### 3. Fetch Recipient Public Key Bundle
- **Endpoint**: `GET /api/v1/messaging/keys/user/{user_id}/` or `GET /api/v1/messaging/keys/gym/{gym_id}/`
- **Response (200 OK)**:
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
    ]
  }
  ```

---

### 4. Create or Retrieve Conversation
- **Endpoint**: `POST /api/v1/messaging/conversations/`
- **Channels**:
  - **User to User**:
    ```json
    {
      "conversation_type": "user_to_user",
      "target_user_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901"
    }
    ```
  - **User to Gym**:
    ```json
    {
      "conversation_type": "user_to_gym",
      "target_gym_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    }
    ```
  - **Gym to User**:
    ```json
    {
      "conversation_type": "gym_to_user",
      "source_gym_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "target_user_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901"
    }
    ```
  - **Gym to Gym**:
    ```json
    {
      "conversation_type": "gym_to_gym",
      "source_gym_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "target_gym_id": "c3d4e5f6-a7b8-9012-cdef-123456789012"
    }
    ```
- **Policy Checks**:
  - Blocks rejected users (`GymBlockedUser` -> `403 Forbidden`).
  - Validates `who_can_message` (`MEMBERS_ONLY` requires active gym membership).

---

### 5. Send Encrypted Message
- **Endpoint**: `POST /api/v1/messaging/conversations/{conversation_id}/messages/`
- **Request Body**:
  ```json
  {
    "ciphertext": "aGVsbG8gd29ybGQgZW5jcnlwdGVkIQ==",
    "nonce": "bm9uY2V2YWx1ZQ==",
    "ephemeral_public_key": "ZXBoZW1lcmFsX2tleQ==",
    "recipient_key_fingerprint": "f1a2b3c4d5e6f7a8",
    "sender_device_id": "alice-device-1",
    "sender_type": "user"
  }
  ```
- **Response (201 Created)**:
  ```json
  {
    "id": "e4f5a6b7-c8d9-0123-ef01-234567890123",
    "conversation_id": "c1d2e3f4-a5b6-7890-1234-567890abcdef",
    "sender_type": "user",
    "sender_user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "sender_user_full_name": "Alice Smith",
    "sender_gym_id": null,
    "sender_gym_name": null,
    "ciphertext": "aGVsbG8gd29ybGQgZW5jcnlwdGVkIQ==",
    "nonce": "bm9uY2V2YWx1ZQ==",
    "delivery_status": "sent",
    "sent_at": "2026-11-01T16:30:00Z"
  }
  ```

---

### 6. Mark Conversation Read
- **Endpoint**: `POST /api/v1/messaging/conversations/{conversation_id}/read/`
- **Request Body**: `{ "up_to_message_id": "<uuid>" }`
- **Effect**: Updates participant `unread_count = 0`, sets message `delivery_status = "read"`, and emits real-time WebSocket read receipt.

---

## Real-Time WebSocket Protocol

### Connection URL
```text
ws://localhost:8000/ws/chat/?token=<ACCESS_TOKEN>&gym_id=<OPTIONAL_GYM_ID>
```

### Supported Client Actions
1. **Join Conversation Room**:
   ```json
   { "action": "join_conversation", "conversation_id": "<uuid>" }
   ```
2. **Send Encrypted Message Live**:
   ```json
   {
     "action": "send_message",
     "conversation_id": "<uuid>",
     "ciphertext": "<base64>",
     "nonce": "<base64>",
     "ephemeral_public_key": "<base64>",
     "sender_type": "user"
   }
   ```
3. **Typing Indicator**:
   ```json
   { "action": "typing", "conversation_id": "<uuid>", "is_typing": true }
   ```
4. **Mark Read**:
   ```json
   { "action": "mark_read", "conversation_id": "<uuid>" }
   ```
5. **Heartbeat**:
   ```json
   { "action": "ping" }
   ```

### Server Events Dispatched
- `connection_established`: Confirms connection and current user/gym context.
- `new_message`: Live broadcast of newly received ciphertext to conversation room.
- `incoming_notification`: Dispatched to user or gym personal channel to increment unread counter or trigger push notification.
- `typing_indicator`: Dispatched when an active chatter is typing.
- `read_receipt`: Dispatched when messages have been marked as read.
