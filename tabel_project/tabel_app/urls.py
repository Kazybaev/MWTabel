from django.urls import include, path
from rest_framework import routers
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    ApiRootAPIView,
    AppMetaAPIView,
    CurrentUserAPIView,
    CustomLoginView,
    DashboardAPIView,
    GroupViewSet,
    LessonViewSet,
    LogoutAPIView,
    MentorProfileViewSet,
    ReportDispatchAPIView,
    StudentProfileViewSet,
)


api_router = routers.DefaultRouter()
api_router.register(r"mentors", MentorProfileViewSet, basename="api-mentors")
api_router.register(r"students", StudentProfileViewSet, basename="api-students")
api_router.register(r"groups", GroupViewSet, basename="api-groups")
api_router.register(r"lessons", LessonViewSet, basename="api-lessons")


urlpatterns = [
    path("api-info/", ApiRootAPIView.as_view(), name="api-root"),
    path("api/auth/login/", CustomLoginView.as_view(), name="api-login"),
    path("api/auth/logout/", LogoutAPIView.as_view(), name="api-logout"),
    path("api/auth/refresh/", TokenRefreshView.as_view(), name="api-token-refresh"),
    path("api/me/", CurrentUserAPIView.as_view(), name="api-me"),
    path("api/dashboard/", DashboardAPIView.as_view(), name="api-dashboard"),
    path("api/meta/", AppMetaAPIView.as_view(), name="api-meta"),
    path("api/reports/send/", ReportDispatchAPIView.as_view(), name="api-report-dispatch"),
    path("api/", include(api_router.urls)),
]
