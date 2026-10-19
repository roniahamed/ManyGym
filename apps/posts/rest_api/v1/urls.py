from django.urls import path
from apps.posts.rest_api.v1.views import (
    GymFeedView,
    GymPostDetailView,
    GymPostMediaThumbnailView,
)

urlpatterns = [
    path("", GymFeedView.as_view(), name="gym-post-feed"),
    path("<uuid:post_id>/", GymPostDetailView.as_view(), name="gym-post-detail"),
    path(
        "<uuid:post_id>/media/<uuid:media_id>/thumbnail/",
        GymPostMediaThumbnailView.as_view(),
        name="gym-post-media-thumbnail",
    ),
]
