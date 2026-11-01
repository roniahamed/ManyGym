"""
Django Channels WebSocket Consumer for Real-time End-to-End Encrypted Messaging.
Supports JWT authentication, room multiplexing, typing indicators, read receipts, and live ciphertext delivery.
"""

import json
from urllib.parse import parse_qs
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken

from apps.users.models import User
from apps.gyms.models import Gym
from apps.messaging.services import (
    send_encrypted_message,
    mark_conversation_as_read,
)
from apps.messaging.selectors import get_conversation_by_id
from apps.messaging.permissions import is_user_authorized_for_gym
from common.enums import MessageSenderTypeEnum


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """
    WebSocket consumer handling real-time encrypted messaging, delivery receipts, and typing indicators.
    """

    async def connect(self):
        # 1. Parse JWT Token from query string or headers
        query_string = self.scope.get("query_string", b"").decode("utf-8")
        query_params = parse_qs(query_string)
        token_list = query_params.get("token", [])

        if not token_list:
            # Also check headers for Sec-WebSocket-Protocol or authorization
            headers = dict(self.scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode("utf-8")
            if auth_header.startswith("Bearer "):
                token_list = [auth_header.split(" ")[1]]

        if not token_list:
            await self.close(code=4001)
            return

        token_str = token_list[0]
        user = await self.authenticate_token(token_str)
        if not user:
            await self.close(code=4003)
            return

        self.user = user
        self.scope["user"] = user

        # 2. Check gym context if requested
        gym_id_list = query_params.get("gym_id", [])
        self.active_gym = None
        if gym_id_list:
            gym = await self.resolve_gym(gym_id_list[0], self.user)
            if gym:
                self.active_gym = gym

        await self.accept()

        # 3. Add to user's personal push group
        self.user_group_name = f"chat_user_{self.user.id}"
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)

        # 4. If gym context, add to gym's group
        if self.active_gym:
            self.gym_group_name = f"chat_gym_{self.active_gym.id}"
            await self.channel_layer.group_add(self.gym_group_name, self.channel_name)

        self.active_conversations = set()

        # Send connection established event
        await self.send_json({
            "type": "connection_established",
            "user_id": str(self.user.id),
            "email": self.user.email,
            "gym_id": str(self.active_gym.id) if self.active_gym else None,
        })

    async def disconnect(self, close_code):
        # Leave personal and gym groups
        if hasattr(self, "user_group_name"):
            await self.channel_layer.group_discard(self.user_group_name, self.channel_name)
        if hasattr(self, "gym_group_name"):
            await self.channel_layer.group_discard(self.gym_group_name, self.channel_name)

        # Leave all joined conversation rooms
        if hasattr(self, "active_conversations"):
            for conv_id in list(self.active_conversations):
                await self.channel_layer.group_discard(f"chat_conversation_{conv_id}", self.channel_name)

    async def receive_json(self, content, **kwargs):
        action = content.get("action")

        if action == "join_conversation":
            conv_id = content.get("conversation_id")
            if conv_id:
                has_access = await self.verify_conversation_access(conv_id)
                if has_access:
                    group = f"chat_conversation_{conv_id}"
                    await self.channel_layer.group_add(group, self.channel_name)
                    self.active_conversations.add(conv_id)
                    await self.send_json({"type": "joined_conversation", "conversation_id": conv_id})
                else:
                    await self.send_json({"type": "error", "message": "Unauthorized conversation access."})

        elif action == "leave_conversation":
            conv_id = content.get("conversation_id")
            if conv_id in self.active_conversations:
                group = f"chat_conversation_{conv_id}"
                await self.channel_layer.group_discard(group, self.channel_name)
                self.active_conversations.remove(conv_id)
                await self.send_json({"type": "left_conversation", "conversation_id": conv_id})

        elif action == "send_message":
            await self.handle_send_message(content)

        elif action == "typing":
            conv_id = content.get("conversation_id")
            is_typing = bool(content.get("is_typing", True))
            if conv_id and conv_id in self.active_conversations:
                await self.channel_layer.group_send(
                    f"chat_conversation_{conv_id}",
                    {
                        "type": "chat_typing",
                        "data": {
                            "conversation_id": conv_id,
                            "user_id": str(self.user.id),
                            "sender_name": f"{self.user.first_name} {self.user.last_name}",
                            "gym_id": str(self.active_gym.id) if self.active_gym else None,
                            "is_typing": is_typing,
                        },
                    },
                )

        elif action == "mark_read":
            conv_id = content.get("conversation_id")
            if conv_id:
                await self.handle_mark_read(conv_id)

        elif action == "ping":
            await self.send_json({"type": "pong"})

    # --- Async Handlers ---

    async def handle_send_message(self, content):
        conv_id = content.get("conversation_id")
        ciphertext = content.get("ciphertext")
        nonce = content.get("nonce")
        ephemeral_public_key = content.get("ephemeral_public_key", "")
        recipient_key_fingerprint = content.get("recipient_key_fingerprint", "")
        sender_device_id = content.get("sender_device_id", "")
        encrypted_keys = content.get("encrypted_keys", {})
        sender_type = content.get("sender_type", MessageSenderTypeEnum.USER)

        if not conv_id or not ciphertext or not nonce:
            await self.send_json({"type": "error", "message": "conversation_id, ciphertext, and nonce are required."})
            return

        try:
            msg = await self.save_message_async(
                conv_id=conv_id,
                ciphertext=ciphertext,
                nonce=nonce,
                ephemeral_public_key=ephemeral_public_key,
                recipient_key_fingerprint=recipient_key_fingerprint,
                sender_device_id=sender_device_id,
                encrypted_keys=encrypted_keys,
                sender_type=sender_type,
            )
            await self.send_json({
                "type": "message_sent_ack",
                "message_id": str(msg.id),
                "conversation_id": conv_id,
                "sent_at": msg.sent_at.isoformat(),
            })
        except Exception as exc:
            await self.send_json({"type": "error", "message": str(exc)})

    async def handle_mark_read(self, conv_id):
        try:
            await self.mark_read_async(conv_id)
        except Exception as exc:
            await self.send_json({"type": "error", "message": str(exc)})

    # --- Group Message Receivers ---

    async def chat_message(self, event):
        """Dispatched when a new encrypted message is posted in the conversation room."""
        await self.send_json({
            "type": "new_message",
            "message": event["data"],
        })

    async def chat_incoming(self, event):
        """Dispatched to personal or gym room to notify of an incoming message."""
        await self.send_json({
            "type": "incoming_notification",
            "message": event["data"],
        })

    async def chat_typing(self, event):
        """Dispatched when another participant is typing."""
        # Don't echo typing back to the authoring user
        if event["data"].get("user_id") != str(self.user.id):
            await self.send_json({
                "type": "typing_indicator",
                "data": event["data"],
            })

    async def chat_read_receipt(self, event):
        """Dispatched when messages are marked as read."""
        await self.send_json({
            "type": "read_receipt",
            "data": event["data"],
        })

    # --- Database Sync to Async Bridges ---

    @database_sync_to_async
    def authenticate_token(self, token_str: str):
        try:
            token = AccessToken(token_str)
            user_id = token.get("user_id")
            return User.objects.filter(id=user_id, is_active=True).first()
        except Exception:
            return None

    @database_sync_to_async
    def resolve_gym(self, gym_id: str, user: User):
        try:
            gym = Gym.objects.get(id=gym_id)
            if is_user_authorized_for_gym(user, gym, "messaging:read"):
                return gym
        except Exception:
            pass
        return None

    @database_sync_to_async
    def verify_conversation_access(self, conv_id: str) -> bool:
        try:
            get_conversation_by_id(conv_id, self.user, gym=self.active_gym)
            return True
        except Exception:
            return False

    @database_sync_to_async
    def save_message_async(self, conv_id, ciphertext, nonce, ephemeral_public_key, recipient_key_fingerprint, sender_device_id, encrypted_keys, sender_type):
        conv = get_conversation_by_id(conv_id, self.user, gym=self.active_gym)
        sender_gym = self.active_gym if sender_type == MessageSenderTypeEnum.GYM else None
        return send_encrypted_message(
            conversation=conv,
            sender_user=self.user,
            sender_type=sender_type,
            ciphertext=ciphertext,
            nonce=nonce,
            ephemeral_public_key=ephemeral_public_key,
            recipient_key_fingerprint=recipient_key_fingerprint,
            sender_device_id=sender_device_id,
            encrypted_keys=encrypted_keys,
            sender_gym=sender_gym,
        )

    @database_sync_to_async
    def mark_read_async(self, conv_id: str):
        conv = get_conversation_by_id(conv_id, self.user, gym=self.active_gym)
        return mark_conversation_as_read(
            conversation=conv,
            user=self.user,
            gym=self.active_gym,
        )
