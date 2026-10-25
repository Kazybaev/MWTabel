from django.urls import include, path
from rest_framework import routers
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    AgrarianGradeRecordViewSet,
    ApiRootAPIView,
    AppMetaAPIView,
    BadgeViewSet,
    CurrentUserAPIView,
    CustomLoginView,
    CollegeGradebookAPIView,
    DashboardAPIView,
    GroupViewSet,
    CollegeGroupViewSet,
    ForceSendAllReportsAPIView,
    LessonViewSet,
    LogoutAPIView,
    MentorProfileViewSet,
    ReportDispatchAPIView,
    ReportDeliveryCallbackAPIView,
    ReportConversationDetailAPIView,
    ReportConversationListAPIView,
    ReportDispatchOptionsAPIView,
    ReportBatchDetailAPIView,
    ReportResendAPIView,
    WahaTestReportBatchAPIView,
    WahaTestReportConfigAPIView,
    WahaParentReportBatchAPIView,
    WahaParentReportBatchActionAPIView,
    WahaParentReportConfigAPIView,
    StudentProfileViewSet,
    StudentBadgeViewSet,
)


api_router = routers.DefaultRouter()
api_router.register(r"mentors", MentorProfileViewSet, basename="api-mentors")
api_router.register(r"grade-records", AgrarianGradeRecordViewSet, basename="api-grade-records")
api_router.register(r"badges", BadgeViewSet, basename="api-badges")
api_router.register(r"student-badges", StudentBadgeViewSet, basename="api-student-badges")
api_router.register(r"students", StudentProfileViewSet, basename="api-students")
api_router.register(r"college-groups", CollegeGroupViewSet, basename="api-college-groups")
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
    path("api/reports/resend/", ReportResendAPIView.as_view(), name="api-report-resend"),
    path("api/reports/send-all/", ForceSendAllReportsAPIView.as_view(), name="api-report-send-all"),
    path("api/reports/batches/<int:batch_id>/", ReportBatchDetailAPIView.as_view(), name="api-report-batch-detail"),
    path("api/reports/waha-test/config/", WahaTestReportConfigAPIView.as_view(), name="api-waha-test-report-config"),
    path("api/reports/waha-test/batches/", WahaTestReportBatchAPIView.as_view(), name="api-waha-test-report-batch-create"),
    path("api/reports/waha-test/batches/<int:batch_id>/", WahaTestReportBatchAPIView.as_view(), name="api-waha-test-report-batch-detail"),
    path("api/reports/waha-parent/config/", WahaParentReportConfigAPIView.as_view(), name="api-waha-parent-report-config"),
    path("api/reports/waha-parent/batches/", WahaParentReportBatchAPIView.as_view(), name="api-waha-parent-report-batch-list-create"),
    path("api/reports/waha-parent/batches/<int:batch_id>/", WahaParentReportBatchAPIView.as_view(), name="api-waha-parent-report-batch-detail"),
    path("api/reports/waha-parent/batches/<int:batch_id>/<str:action_name>/", WahaParentReportBatchActionAPIView.as_view(), name="api-waha-parent-report-batch-action"),
    path("api/report-logs/", ReportDeliveryCallbackAPIView.as_view(), name="api-report-delivery-callback"),
    path("api/reports/conversations/", ReportConversationListAPIView.as_view(), name="api-report-conversations"),
    path("api/reports/options/", ReportDispatchOptionsAPIView.as_view(), name="api-report-options"),
    path("api/reports/conversations/<int:student_id>/", ReportConversationDetailAPIView.as_view(), name="api-report-conversation-detail"),
    path("api/", include(api_router.urls)),
]
