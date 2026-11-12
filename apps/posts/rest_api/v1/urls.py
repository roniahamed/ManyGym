from django.urls import path
from apps.posts.rest_api.v1.views import (
    GymFeedView,
    MyPostsFeedView,
    PostRepostView,
    PostRepostsListView,
    GymPostDetailView,
    GymPostMediaThumbnailView,
    PostCommentsView,
    CommentRepliesView,
    CommentDetailView,
)

urlpatterns = [
    path("", GymFeedView.as_view(), name="gym-post-feed"),
    path("feed/", GymFeedView.as_view(), name="gym-post-feed-alias"),
    path("my/", MyPostsFeedView.as_view(), name="my-posts-feed"),
    path("repost/", PostRepostView.as_view(), name="post-repost-body"),
    path("<uuid:post_id>/", GymPostDetailView.as_view(), name="gym-post-detail"),
    path("<uuid:post_id>/repost/", PostRepostView.as_view(), name="post-repost"),
    path("<uuid:post_id>/reposts/", PostRepostsListView.as_view(), name="post-reposts-list"),
    path("<uuid:post_id>/comments/", PostCommentsView.as_view(), name="post-comments-list-create"),
    path("<uuid:post_id>/comments/<uuid:comment_id>/", CommentDetailView.as_view(), name="post-comment-detail"),
    path("<uuid:post_id>/comments/<uuid:comment_id>/replies/", CommentRepliesView.as_view(), name="post-comment-replies"),
    path(
        "<uuid:post_id>/media/<uuid:media_id>/thumbnail/",
        GymPostMediaThumbnailView.as_view(),
        name="gym-post-media-thumbnail",
    ),
]
