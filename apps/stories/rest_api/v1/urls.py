from django.urls import path
from apps.stories.rest_api.v1.views import (
    StoryListCreateView,
    StoryTrayView,
    MyStoriesView,
    StoryDetailView,
    StoryRecordViewView,
    StoryViewersListView,
)

urlpatterns = [
    path("", StoryListCreateView.as_view(), name="story-list-create"),
    path("tray/", StoryTrayView.as_view(), name="story-tray"),
    path("my/", MyStoriesView.as_view(), name="story-my-list"),
    path("<uuid:story_id>/", StoryDetailView.as_view(), name="story-detail"),
    path("<uuid:story_id>/view/", StoryRecordViewView.as_view(), name="story-record-view"),
    path("<uuid:story_id>/viewers/", StoryViewersListView.as_view(), name="story-viewers"),
]

