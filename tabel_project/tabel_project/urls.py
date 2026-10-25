import os

from django.contrib import admin
from django.conf import settings
from django.urls import include, path, re_path
from django.views.static import serve
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from tabel_app.views import frontend_app_view


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="api-schema"), name="api-redoc"),
    path("", include("tabel_app.urls")),
    re_path(r"^(?!api/|admin/)(?P<path>.*)$", frontend_app_view, name="frontend-app"),
]

if os.getenv("SERVE_STATIC_FILES", "").lower() == "true":
    urlpatterns.insert(
        1,
        re_path(
            r"^static/(?P<path>.*)$",
            serve,
            {"document_root": settings.STATIC_ROOT},
        ),
    )
