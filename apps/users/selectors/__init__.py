from apps.users.selectors.user_selectors import (
    get_user_by_email,
    get_user_by_id,
    get_user_profile,
    get_user_about_profile,
    list_user_educations,
    get_user_education_by_id,
    list_user_social_links,
    get_user_social_link_by_id,
    iter_users,
)
from apps.users.selectors.social_selectors import (
    list_user_followers,
    list_user_following,
    is_following_user,
    resolve_target_entity,
    ResolvedTarget,
)
from apps.users.selectors.settings_selectors import (
    get_user_settings,
    list_blocked_users_for_user,
    search_users_to_block_for_user,
    is_user_blocked_by,
)

# Alias for backward compatibility if ever called
get_user_with_profile = get_user_by_id

__all__ = [
    "get_user_by_email",
    "get_user_by_id",
    "get_user_profile",
    "get_user_about_profile",
    "list_user_educations",
    "get_user_education_by_id",
    "list_user_social_links",
    "get_user_social_link_by_id",
    "iter_users",
    "get_user_with_profile",
    "list_user_followers",
    "list_user_following",
    "is_following_user",
    "resolve_target_entity",
    "ResolvedTarget",
    "get_user_settings",
    "list_blocked_users_for_user",
    "search_users_to_block_for_user",
    "is_user_blocked_by",
]
