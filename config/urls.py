from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from apps.users.rest_api.v1.views import UnifiedFollowView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Infrastructure & Common Endpoints
    path("api/v1/", include("common.urls")),
    # Identity, Authentication & Profile Endpoints
    path("api/v1/auth/", include("apps.authentication.rest_api.v1.urls")),
    path("api/v1/auth/", include("apps.users.rest_api.v1.urls")),
    path("api/v1/users/", include("apps.users.rest_api.v1.urls")),
    # Dynamic Roles & Topic-Based RBAC Endpoints
    path("api/v1/access-control/", include("apps.access_control.rest_api.v1.urls")),
    # Phase 2: Gym Profile & Amenities Endpoints
    path("api/v1/gyms/", include("apps.gyms.rest_api.v1.urls")),
    path("api/v1/amenities/", include("apps.amenities.rest_api.v1.urls")),
    # Phase 3: Membership Plans & Dynamic Pricing Engine
    path("api/v1/plans/", include("apps.memberships.rest_api.v1.urls")),
    # Phase 4: Member Lifecycle, Subscriptions & Payment Transactions
    path("api/v1/members/", include("apps.members.rest_api.v1.urls")),
    # Phase 5: Leads CRM, Pipeline Tracking & Conversion Funnel
    path("api/v1/leads/", include("apps.leads.rest_api.v1.urls")),
    # Phase 6: Routine Templates & Workout Prescription Engine
    path("api/v1/", include("apps.routines.rest_api.v1.urls")),
    # Phase 7: Community Feed, Social Posts & Asynchronous Media Pipeline
    path("api/v1/posts/", include("apps.posts.rest_api.v1.urls")),
    # Phase 8: Gym Studio Reports, Analytics & Executive Dashboard
    path("api/v1/dashboard/", include("apps.reports.rest_api.v1.dashboard_urls")),
    path("api/v1/reports/", include("apps.reports.rest_api.v1.reports_urls")),
    # Phase 9: Real-time End-to-End Encrypted Messaging (User-to-User, User-to-Gym, Gym-to-Gym)
    path("api/v1/messaging/", include("apps.messaging.rest_api.v1.urls")),
    # Unified Social Follow Endpoint (User & Gym Follow/Unfollow)
    path("api/v1/follows/", UnifiedFollowView.as_view(), name="unified-follow"),
    path("api/v1/follows/<uuid:target_id>/", UnifiedFollowView.as_view(), name="unified-follow-detail"),
    path("api/v1/follow/", UnifiedFollowView.as_view(), name="unified-follow-alias"),
    path("api/v1/follow/<uuid:target_id>/", UnifiedFollowView.as_view(), name="unified-follow-alias-detail"),
    # OpenAPI Schema & API Documentation

    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/v1/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
