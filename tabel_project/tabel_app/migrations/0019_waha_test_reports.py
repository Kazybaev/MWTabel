from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import phonenumber_field.modelfields


class Migration(migrations.Migration):

    dependencies = [
        ("tabel_app", "0018_manual_report_queue_safety"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WahaTestReportBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("month", models.DateField(help_text="First day of the reporting month.")),
                ("organization_type", models.CharField(choices=[("academy", "Академия"), ("college", "Колледж")], db_index=True, max_length=16)),
                ("status", models.CharField(choices=[("queued", "Queued"), ("processing", "Processing"), ("completed", "Completed")], default="queued", max_length=16)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="waha_test_report_batches", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.CreateModel(
            name="WahaTestReportBatchItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("month", models.DateField(help_text="First day of the reporting month.")),
                ("recipient_phone", phonenumber_field.modelfields.PhoneNumberField(max_length=128, region=None)),
                ("report_payload", models.JSONField(blank=True, default=dict)),
                ("message_text", models.TextField()),
                ("status", models.CharField(choices=[("queued", "Queued"), ("processing", "Processing"), ("accepted", "Accepted by WAHA"), ("failed", "Failed"), ("unknown", "Delivery result unknown"), ("skipped", "Skipped")], db_index=True, default="queued", max_length=16)),
                ("dedupe_key", models.CharField(blank=True, max_length=64, null=True)),
                ("response_payload", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items", to="tabel_app.wahatestreportbatch")),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="waha_test_report_items", to="tabel_app.studentprofile")),
            ],
            options={
                "ordering": ("batch_id", "id"),
            },
        ),
        migrations.AddConstraint(
            model_name="wahatestreportbatchitem",
            constraint=models.UniqueConstraint(fields=("batch", "student", "month"), name="unique_waha_test_batch_student_month"),
        ),
        migrations.AddConstraint(
            model_name="wahatestreportbatchitem",
            constraint=models.UniqueConstraint(condition=models.Q(("dedupe_key__isnull", False), ("status__in", ("queued", "processing"))), fields=("dedupe_key",), name="unique_active_waha_test_report_context"),
        ),
    ]
