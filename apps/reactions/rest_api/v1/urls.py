from django.urls import path
from apps.reactions.rest_api.v1.views import (
    CommentReactionsView,
    CommentReactionSummaryView,
    PostReactionsView,
    PostReactionSummaryView,
    ReactionItemListView,
    StoryReactionsView,
    StoryReactionSummaryView,
    UnifiedReactionDetailView,
    UnifiedReactionsView,
)

urlpatterns = [
    # Reaction Items Catalog
    path("items/", ReactionItemListView.as_view(), name="reaction-items-list"),
    # Unified Reactions Endpoints
    path("", UnifiedReactionsView.as_view(), name="reactions-unified"),
    path("<uuid:reaction_id>/", UnifiedReactionDetailView.as_view(), name="reaction-detail"),
    # Target-specific shortcuts available under reactions/
    path("posts/<uuid:post_id>/", PostReactionsView.as_view(), name="reaction-post"),
    path("posts/<uuid:post_id>/summary/", PostReactionSummaryView.as_view(), name="reaction-post-summary"),
    path("stories/<uuid:story_id>/", StoryReactionsView.as_view(), name="reaction-story"),
    path("stories/<uuid:story_id>/summary/", StoryReactionSummaryView.as_view(), name="reaction-story-summary"),
    path("moments/<uuid:story_id>/", StoryReactionsView.as_view(), name="reaction-moment"),
    path("moments/<uuid:story_id>/summary/", StoryReactionSummaryView.as_view(), name="reaction-moment-summary"),
    path("comments/<uuid:comment_id>/", CommentReactionsView.as_view(), name="reaction-comment"),
    path("comments/<uuid:comment_id>/summary/", CommentReactionSummaryView.as_view(), name="reaction-comment-summary"),
]

