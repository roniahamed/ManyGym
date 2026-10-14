from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

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
