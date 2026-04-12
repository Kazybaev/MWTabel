from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tabel_app", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="MonthlyStudentReportDispatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("month", models.DateField(help_text="First day of the reporting month.")),
                ("trigger_date", models.DateField(help_text="Last lesson date in the reporting month.")),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("succeeded", "Succeeded"), ("failed", "Failed")],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("response_payload", models.JSONField(blank=True, default=dict)),
                ("workflow_run_id", models.CharField(blank=True, max_length=255)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="monthly_report_dispatches",
                        to="tabel_app.studentprofile",
                    ),
                ),
            ],
            options={
                "ordering": ("-month", "student__user__full_name"),
            },
        ),
        migrations.AddConstraint(
            model_name="monthlystudentreportdispatch",
            constraint=models.UniqueConstraint(
                fields=("student", "month"),
                name="unique_monthly_student_report_dispatch",
            ),
        ),
    ]
