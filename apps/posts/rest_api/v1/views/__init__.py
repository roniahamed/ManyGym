from apps.posts.rest_api.v1.views.base_views import (
    resolve_post_gym,
    check_user_is_member_or_staff,
    check_post_management_permission,
)
from apps.posts.rest_api.v1.views.feed_views import (
    GymFeedView,
    GymPostDetailView,
)
from apps.posts.rest_api.v1.views.media_views import (
    GymPostMediaThumbnailView,
)

GymPostFeedListCreateView = GymFeedView

__all__ = [
    "resolve_post_gym",
    "check_user_is_member_or_staff",
    "check_post_management_permission",
    "GymFeedView",
    "GymPostDetailView",
    "GymPostFeedListCreateView",
    "GymPostMediaThumbnailView",
]
