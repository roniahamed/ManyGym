from django.contrib import admin
from apps.messaging.models import (
    UserDeviceKey,
    GymDeviceKey,
    Conversation,
    ConversationParticipant,
    EncryptedMessage,
    MessageDeliveryReceipt,
)


@admin.register(UserDeviceKey)
class UserDeviceKeyAdmin(admin.ModelAdmin):
    list_display = ("user", "device_id", "algorithm", "is_active", "created_at")
    search_fields = ("user__email", "device_id")
    list_filter = ("algorithm", "is_active")


@admin.register(GymDeviceKey)
class GymDeviceKeyAdmin(admin.ModelAdmin):
    list_display = ("gym", "device_id", "algorithm", "is_active", "created_at")
    search_fields = ("gym__name", "device_id")
    list_filter = ("algorithm", "is_active")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation_type", "user_a", "user_b", "gym_a", "gym_b", "last_message_at")
    list_filter = ("conversation_type",)
    search_fields = ("id", "user_a__email", "user_b__email", "gym_a__name", "gym_b__name")


@admin.register(ConversationParticipant)
class ConversationParticipantAdmin(admin.ModelAdmin):
    list_display = ("conversation", "participant_type", "user", "gym", "unread_count", "last_read_at")
    list_filter = ("participant_type",)


@admin.register(EncryptedMessage)
class EncryptedMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender_type", "sender_user", "sender_gym", "delivery_status", "sent_at")
    list_filter = ("sender_type", "delivery_status")
    search_fields = ("id", "sender_user__email", "sender_gym__name")


@admin.register(MessageDeliveryReceipt)
class MessageDeliveryReceiptAdmin(admin.ModelAdmin):
    list_display = ("message", "user", "gym", "status", "timestamp")
    list_filter = ("status",)
