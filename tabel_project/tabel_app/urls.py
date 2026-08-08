from django.urls import include, path
from rest_framework import routers
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    ApiRootAPIView,
    AppMetaAPIView,
    CurrentUserAPIView,
    CustomLoginView,
    CollegeGradebookAPIView,
    DashboardAPIView,
    GroupViewSet,
    ForceSendAllReportsAPIView,
    LessonViewSet,
    LogoutAPIView,
    MentorProfileViewSet,
    ReportDispatchAPIView,
    ReportDeliveryCallbackAPIView,
    ReportConversationDetailAPIView,
    ReportConversationListAPIView,
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
    path("api/college-gradebook/", CollegeGradebookAPIView.as_view(), name="api-college-gradebook"),
    path("api/dashboard/", DashboardAPIView.as_view(), name="api-dashboard"),
    path("api/meta/", AppMetaAPIView.as_view(), name="api-meta"),
    path("api/reports/send/", ReportDispatchAPIView.as_view(), name="api-report-dispatch"),
    path("api/reports/send-all/", ForceSendAllReportsAPIView.as_view(), name="api-report-send-all"),
    path("api/report-logs/", ReportDeliveryCallbackAPIView.as_view(), name="api-report-delivery-callback"),
    path("api/reports/conversations/", ReportConversationListAPIView.as_view(), name="api-report-conversations"),
    path("api/reports/conversations/<int:student_id>/", ReportConversationDetailAPIView.as_view(), name="api-report-conversation-detail"),
    path("api/", include(api_router.urls)),
]
