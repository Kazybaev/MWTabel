from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import phonenumber_field.modelfields


class Migration(migrations.Migration):

    dependencies = [
        ("tabel_app", "0019_waha_test_reports"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WahaParentReportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("month", models.DateField(help_text="First day of the reporting month.")),
                ("organization_type", models.CharField(choices=[("academy", "Академия"), ("college", "Колледж")], db_index=True, max_length=16)),
                ("college_branch", models.CharField(blank=True, choices=[("kuwait", "Кувейтский колледж"), ("agrarian", "Аграрный колледж")], db_index=True, max_length=16)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("queued", "Queued"), ("processing", "Processing"), ("completed", "Completed"), ("cancelled", "Cancelled")], db_index=True, default="draft", max_length=16)),
                ("requested_filters", models.JSONField(blank=True, default=dict)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="waha_parent_report_batches", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.CreateModel(
            name="WahaParentReportBatchItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("month", models.DateField(help_text="First day of the reporting month.")),
                ("recipient_phone", phonenumber_field.modelfields.PhoneNumberField(max_length=128, region=None)),
                ("report_payload", models.JSONField(blank=True, default=dict)),
                ("message_text", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("draft", "Draft"), ("queued", "Queued"), ("processing", "Processing"), ("accepted", "Accepted by WAHA"), ("failed", "Failed"), ("unknown", "Delivery result unknown"), ("skipped", "Skipped"), ("cancelled", "Cancelled")], db_index=True, default="draft", max_length=16)),
                ("dedupe_key", models.CharField(blank=True, max_length=64, null=True)),
                ("response_payload", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="tabel_app.wahaparentreportbatch")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="waha_parent_report_items", to="tabel_app.studentprofile")),
            ],
            options={
                "ordering": ("batch_id", "id"),
            },
        ),
        migrations.AddConstraint(
            model_name="wahaparentreportbatchitem",
            constraint=models.UniqueConstraint(fields=("batch", "student", "month"), name="unique_waha_parent_batch_student_month"),
        ),
        migrations.AddIndex(
            model_name="wahaparentreportbatchitem",
            index=models.Index(fields=["student", "month", "status"], name="waha_parent_stu_month_st_idx"),
        ),
        migrations.AddConstraint(
            model_name="wahaparentreportbatchitem",
            constraint=models.UniqueConstraint(condition=models.Q(("dedupe_key__isnull", False), ("status__in", ("draft", "queued", "processing"))), fields=("dedupe_key",), name="unique_active_waha_parent_report_context"),
        ),
    ]
