from django.urls import path
from apps.posts.rest_api.v1.views import (
    PostCommentsView,
    CommentRepliesView,
    CommentDetailView,
)

urlpatterns = [
    path("", PostCommentsView.as_view(), name="comments-list-create"),
    path("<uuid:comment_id>/", CommentDetailView.as_view(), name="comment-detail"),
    path("<uuid:comment_id>/replies/", CommentRepliesView.as_view(), name="comment-replies"),
]

