from django.urls import path
from apps.messaging.rest_api.v1.views import (
    UserDeviceKeyRegisterView,
    GymDeviceKeyRegisterView,
    UserPublicKeyBundleView,
    GymPublicKeyBundleView,
    UserE2EEBackupStatusView,
    UserE2EEBackupView,
    UserE2EEBackupRestoreView,
    UserE2EEBackupChangeCodeView,
    ConversationListCreateView,
    ConversationDetailView,
    FindPeopleToMessageView,
    ConversationMessagesView,
    ConversationMarkReadView,
    ChatHistorySearchView,
    ChatSearchIndexView,
)

urlpatterns = [
    # E2EE Public Key Registry & Messenger-style Password/PIN Backup
    path("keys/register/", UserDeviceKeyRegisterView.as_view(), name="user-key-register"),
    path("keys/gym/register/", GymDeviceKeyRegisterView.as_view(), name="gym-key-register"),
    path("keys/user/<uuid:user_id>/", UserPublicKeyBundleView.as_view(), name="user-key-bundle"),
    path("keys/gym/<uuid:gym_id>/", GymPublicKeyBundleView.as_view(), name="gym-key-bundle"),
    path("keys/backup/status/", UserE2EEBackupStatusView.as_view(), name="user-e2ee-backup-status"),
    path("keys/backup/", UserE2EEBackupView.as_view(), name="user-e2ee-backup"),
    path("keys/backup/restore/", UserE2EEBackupRestoreView.as_view(), name="user-e2ee-backup-restore"),
    path("keys/backup/change-code/", UserE2EEBackupChangeCodeView.as_view(), name="user-e2ee-backup-change-code"),

    # Find People to Message (Follows + Followers only, for offcanvas/modal)
    path("people/search/", FindPeopleToMessageView.as_view(), name="messaging-people-search"),

    # Conversations & Message History
    path("conversations/", ConversationListCreateView.as_view(), name="conversation-list-create"),
    path("conversations/<uuid:conversation_id>/", ConversationDetailView.as_view(), name="conversation-detail"),
    path("conversations/<uuid:conversation_id>/messages/", ConversationMessagesView.as_view(), name="conversation-messages"),
    path("conversations/<uuid:conversation_id>/read/", ConversationMarkReadView.as_view(), name="conversation-mark-read"),

    # WhatsApp-style E2EE Chat History Search
    path("messages/search/", ChatHistorySearchView.as_view(), name="messaging-chat-search"),
    path("search/index/", ChatSearchIndexView.as_view(), name="messaging-chat-search-index"),
]
