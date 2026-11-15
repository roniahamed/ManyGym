from django.urls import path
from apps.posts.rest_api.v1.views import (
    PostCommentsView,
    CommentRepliesView,
    CommentDetailView,
)
from apps.reactions.rest_api.v1.views import (
    CommentReactionsView,
    CommentReactionSummaryView,
)

urlpatterns = [
    path("", PostCommentsView.as_view(), name="comments-list-create"),
    path("<uuid:comment_id>/", CommentDetailView.as_view(), name="comment-detail"),
    path("<uuid:comment_id>/replies/", CommentRepliesView.as_view(), name="comment-replies"),
    path("<uuid:comment_id>/reactions/", CommentReactionsView.as_view(), name="comment-reactions"),
    path("<uuid:comment_id>/reactions/summary/", CommentReactionSummaryView.as_view(), name="comment-reactions-summary"),
]

