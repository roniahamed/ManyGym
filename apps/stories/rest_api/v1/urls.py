from django.urls import path
from apps.stories.rest_api.v1.views import (
    StoryListCreateView,
    StoryTrayView,
    MyStoriesView,
    StoryDetailView,
    StoryRecordViewView,
    StoryViewersListView,
    StoryReplyListCreateView,
    StoryReplyDetailView,
)
from apps.reactions.rest_api.v1.views import (
    StoryReactionsView,
    StoryReactionSummaryView,
)

urlpatterns = [
    path("", StoryListCreateView.as_view(), name="story-list-create"),
    path("tray/", StoryTrayView.as_view(), name="story-tray"),
    path("my/", MyStoriesView.as_view(), name="story-my-list"),
    path("<uuid:story_id>/", StoryDetailView.as_view(), name="story-detail"),
    path("<uuid:story_id>/view/", StoryRecordViewView.as_view(), name="story-record-view"),
    path("<uuid:story_id>/viewers/", StoryViewersListView.as_view(), name="story-viewers"),
    path("<uuid:story_id>/reactions/", StoryReactionsView.as_view(), name="story-reactions"),
    path("<uuid:story_id>/reactions/summary/", StoryReactionSummaryView.as_view(), name="story-reactions-summary"),
    # Reply & Comment Message endpoints
    path("<uuid:story_id>/reply/", StoryReplyListCreateView.as_view(), name="story-reply-create"),
    path("<uuid:story_id>/replies/", StoryReplyListCreateView.as_view(), name="story-replies-list"),
    path("<uuid:story_id>/replies/<uuid:reply_id>/", StoryReplyDetailView.as_view(), name="story-reply-detail"),
    path("<uuid:story_id>/comments/", StoryReplyListCreateView.as_view(), name="story-comments-list-create"),
    path("<uuid:story_id>/comments/<uuid:reply_id>/", StoryReplyDetailView.as_view(), name="story-comments-detail"),
    path("<uuid:story_id>/message/", StoryReplyListCreateView.as_view(), name="story-message-create"),
]

