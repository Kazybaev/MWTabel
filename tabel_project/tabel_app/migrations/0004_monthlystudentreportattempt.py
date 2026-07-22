from django.db import migrations, models
import django.db.models.deletion


def copy_existing_dispatches(apps, schema_editor):
    Dispatch = apps.get_model("tabel_app", "MonthlyStudentReportDispatch")
    Attempt = apps.get_model("tabel_app", "MonthlyStudentReportAttempt")
    for dispatch in Dispatch.objects.all().iterator():
        attempt = Attempt.objects.create(
            dispatch_id=dispatch.pk,
            attempt_number=max(dispatch.attempts, 1),
            status=dispatch.status,
            payload=dispatch.payload,
            response_payload=dispatch.response_payload,
            workflow_run_id=dispatch.workflow_run_id,
            error_message=dispatch.error_message,
            sent_at=dispatch.sent_at,
        )
        Attempt.objects.filter(pk=attempt.pk).update(
            created_at=dispatch.created_at,
            updated_at=dispatch.updated_at,
        )


class Migration(migrations.Migration):
    dependencies = [("tabel_app", "0003_studentprofile_archived_at")]

    operations = [
        migrations.CreateModel(
            name="MonthlyStudentReportAttempt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("attempt_number", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("pending", "Pending"), ("succeeded", "Succeeded"), ("failed", "Failed")], default="pending", max_length=16)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("response_payload", models.JSONField(blank=True, default=dict)),
                ("workflow_run_id", models.CharField(blank=True, max_length=255)),
                ("error_message", models.TextField(blank=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("dispatch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="delivery_attempts", to="tabel_app.monthlystudentreportdispatch")),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.AddConstraint(
            model_name="monthlystudentreportattempt",
            constraint=models.UniqueConstraint(fields=("dispatch", "attempt_number"), name="unique_monthly_report_delivery_attempt"),
        ),
        migrations.RunPython(copy_existing_dispatches, migrations.RunPython.noop),
    ]
