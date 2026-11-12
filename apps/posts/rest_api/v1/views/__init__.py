from apps.posts.rest_api.v1.views.base_views import (
    resolve_post_gym,
    resolve_post_owner_context,
    check_user_is_member_or_staff,
    check_post_management_permission,
    check_post_owner_manage_permission,
)
from apps.posts.rest_api.v1.views.feed_views import (
    GymFeedView,
    MyPostsFeedView,
    PostRepostView,
    PostRepostsListView,
    GymPostDetailView,
)
from apps.posts.rest_api.v1.views.media_views import (
    GymPostMediaThumbnailView,
)

GymPostFeedListCreateView = GymFeedView

__all__ = [
    "resolve_post_gym",
    "resolve_post_owner_context",
    "check_user_is_member_or_staff",
    "check_post_management_permission",
    "check_post_owner_manage_permission",
    "GymFeedView",
    "MyPostsFeedView",
    "PostRepostView",
    "PostRepostsListView",
    "GymPostDetailView",
    "GymPostFeedListCreateView",
    "GymPostMediaThumbnailView",
]
