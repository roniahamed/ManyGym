from django.urls import path
from apps.messaging.rest_api.v1.views import (
    UserDeviceKeyRegisterView,
    GymDeviceKeyRegisterView,
    UserPublicKeyBundleView,
    GymPublicKeyBundleView,
    ConversationListCreateView,
    ConversationDetailView,
    ConversationMessagesView,
    ConversationMarkReadView,
)

urlpatterns = [
    # E2EE Public Key Registry
    path("keys/register/", UserDeviceKeyRegisterView.as_view(), name="user-key-register"),
    path("keys/gym/register/", GymDeviceKeyRegisterView.as_view(), name="gym-key-register"),
    path("keys/user/<uuid:user_id>/", UserPublicKeyBundleView.as_view(), name="user-key-bundle"),
    path("keys/gym/<uuid:gym_id>/", GymPublicKeyBundleView.as_view(), name="gym-key-bundle"),

    # Conversations Management
    path("conversations/", ConversationListCreateView.as_view(), name="conversation-list-create"),
    path("conversations/<uuid:conversation_id>/", ConversationDetailView.as_view(), name="conversation-detail"),
    path("conversations/<uuid:conversation_id>/messages/", ConversationMessagesView.as_view(), name="conversation-messages"),
    path("conversations/<uuid:conversation_id>/read/", ConversationMarkReadView.as_view(), name="conversation-mark-read"),
]
