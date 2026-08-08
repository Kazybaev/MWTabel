from unittest.mock import patch

from django.test import TestCase

from tabel_app.college_reports import (
    force_send_all_college_monthly_reports,
    send_college_student_month_report,
    send_due_college_monthly_reports,
)
from tabel_app.models import (
    Group,
    MentorProfile,
    ORGANIZATION_ACADEMY,
    ORGANIZATION_COLLEGE,
    StudentProfile,
    User,
)


class CollegeMonthlyReportServiceTests(TestCase):
    def setUp(self):
        mentor_user = User.objects.create_user(
            username="college-report-mentor",
            password="test-password",
            full_name="College Report Mentor",
            role=User.ROLE_MENTOR,
        )
        mentor = MentorProfile.objects.create(
            user=mentor_user,
            organization_type=ORGANIZATION_COLLEGE,
        )
        self.college_group = Group.objects.create(
            course_name="College Subject",
            mentor=mentor,
            study_days=Group.MON_FRI,
            organization_type=ORGANIZATION_COLLEGE,
        )
        college_user = User.objects.create_user(
            username="college-report-student",
            password="test-password",
            full_name="College Report Student",
            role=User.ROLE_STUDENT,
        )
        self.college_student = StudentProfile.objects.create(
            user=college_user,
            parent_name="College Parent",
            parent_phone="+996700000001",
            group=self.college_group,
            organization_type=ORGANIZATION_COLLEGE,
        )

        academy_mentor_user = User.objects.create_user(
            username="academy-report-mentor",
            password="test-password",
            full_name="Academy Report Mentor",
            role=User.ROLE_MENTOR,
        )
        academy_mentor = MentorProfile.objects.create(
            user=academy_mentor_user,
            organization_type=ORGANIZATION_ACADEMY,
        )
        academy_group = Group.objects.create(
            course_name="Academy Group",
            mentor=academy_mentor,
            study_days=Group.MON_WED_SAT,
            organization_type=ORGANIZATION_ACADEMY,
        )
        academy_user = User.objects.create_user(
            username="academy-report-student",
            password="test-password",
            full_name="Academy Report Student",
            role=User.ROLE_STUDENT,
        )
        self.academy_student = StudentProfile.objects.create(
            user=academy_user,
            parent_name="Academy Parent",
            parent_phone="+996700000002",
            group=academy_group,
            organization_type=ORGANIZATION_ACADEMY,
        )

    @patch("tabel_app.college_reports.service.send_student_month_report")
    def test_single_college_report_uses_standard_report_logic(self, mocked_send):
        mocked_send.return_value = {"status": "sent"}

        result = send_college_student_month_report(self.college_student, dry_run=True)

        self.assertEqual(result["status"], "sent")
        mocked_send.assert_called_once_with(self.college_student, dry_run=True)

    @patch("tabel_app.college_reports.service.send_student_month_report")
    def test_academy_student_is_rejected_before_delivery(self, mocked_send):
        result = send_college_student_month_report(self.academy_student)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "not_college_student")
        mocked_send.assert_not_called()

    @patch("tabel_app.college_reports.service.force_send_all_monthly_reports")
    def test_bulk_college_report_is_always_scoped_to_college(self, mocked_send_all):
        mocked_send_all.return_value = []

        force_send_all_college_monthly_reports(run_date=None)

        mocked_send_all.assert_called_once_with(
            organization_type=ORGANIZATION_COLLEGE,
            run_date=None,
        )

    @patch("tabel_app.college_reports.service.send_due_monthly_reports")
    def test_due_college_report_is_always_scoped_to_college(self, mocked_send_due):
        mocked_send_due.return_value = []

        send_due_college_monthly_reports(group_id=self.college_group.pk)

        mocked_send_due.assert_called_once_with(
            organization_type=ORGANIZATION_COLLEGE,
            group_id=self.college_group.pk,
        )
