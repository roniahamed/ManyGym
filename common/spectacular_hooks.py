from typing import List, Tuple, Any


def deduplicate_schema_endpoints(
    endpoints: List[Tuple[str, str, str, Any]]
) -> List[Tuple[str, str, str, Any]]:
    """
    drf-spectacular preprocessing hook that filters out redundant alias paths
    from the published OpenAPI specification schema, ensuring canonical endpoints
    are documented cleanly without breaking runtime URL routing backward compatibility.
    """
    excluded_exact_paths = {
        # Redundant follow aliases (canonical is /api/v1/follows/ and /api/v1/follows/{target_id}/)
        "/api/v1/follow/",
        "/api/v1/follow/{target_id}/",
        "/api/v1/auth/follow/",
        "/api/v1/users/follow/",
        # Redundant user auth aliases under /users/ (canonical is /api/v1/auth/*)
        "/api/v1/users/register/",
        "/api/v1/users/verify-signup-otp/",
        "/api/v1/users/resend-otp/",
        "/api/v1/users/forgot-password/",
        "/api/v1/users/verify-reset-otp/",
        "/api/v1/users/reset-password/",
        "/api/v1/users/change-password/",
        # Redundant user profile/settings under /auth/ (canonical is /api/v1/users/*)
        "/api/v1/auth/{user_id}/follow/",
        "/api/v1/auth/{user_id}/followers/",
        "/api/v1/auth/{user_id}/following/",
        "/api/v1/auth/followers/{user_id}/block/",
        "/api/v1/auth/settings/",
        "/api/v1/auth/settings/access-control/",
        "/api/v1/auth/settings/blocked-users/",
        "/api/v1/auth/settings/blocked-users/search/",
        "/api/v1/auth/settings/blocked-users/{user_id}/",
        "/api/v1/auth/profile/about/",
        "/api/v1/auth/me/about/",
        "/api/v1/auth/profile/about/educations/",
        "/api/v1/auth/profile/about/educations/{education_id}/",
        "/api/v1/auth/profile/about/social-links/",
        "/api/v1/auth/profile/about/social-links/{link_id}/",
        "/api/v1/auth/{user_id}/profile/about/",
        "/api/v1/auth/{user_id}/about/",
        # Redundant aliases for about
        "/api/v1/users/me/about/",
        "/api/v1/users/{user_id}/about/",
    }

    filtered = []
    for (path, path_regex, method, callback) in endpoints:
        clean_path = path.rstrip("/") + "/"
        if clean_path in excluded_exact_paths or path in excluded_exact_paths:
            continue
        filtered.append((path, path_regex, method, callback))
    return filtered

