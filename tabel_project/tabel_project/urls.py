from django.contrib import admin
from django.urls import include, path, re_path

from tabel_app.views import frontend_app_view


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("tabel_app.urls")),
    re_path(r"^(?!api/|admin/).*$", frontend_app_view, name="frontend-app"),
]
