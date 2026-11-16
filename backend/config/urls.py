from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.common.views import HealthCheckView

api_v1 = [
    path("auth/", include("apps.accounts.urls")),
    path("workspaces/", include("apps.workspaces.urls")),
]

urlpatterns = [
    path("api/health/", HealthCheckView.as_view(), name="health"),
    path("api/v1/", include(api_v1)),
    path("admin/", admin.site.urls),
]

if settings.API_DOCS_ENABLED:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    ]
