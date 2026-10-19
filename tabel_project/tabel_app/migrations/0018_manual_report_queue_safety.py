import hashlib
import json
import re

from django.db import migrations, models


ACTIVE_STATUSES = ("queued", "processing", "pending")


def _dedupe_key(item):
    student = item.student
    recipient = re.sub(r"\D", "", str(student.parent_phone or ""))
    context = {
        "student_id": student.pk,
        "organization_type": item.batch.organization_type,
        "college_branch": (
            student.college_branch if item.batch.organization_type == "college" else None
        ),
    }
    material = json.dumps(
        {"month": item.month.isoformat(), "recipient": recipient, "context": context},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def backfill_legacy_queue_safety(apps, schema_editor):
    BatchItem = apps.get_model("tabel_app", "MonthlyStudentReportBatchItem")
    active_keys = set()
    queryset = BatchItem.objects.select_related("batch", "student").order_by("created_at", "id")
    for item in queryset.iterator():
        canonical_key = _dedupe_key(item)
        dedupe_key = canonical_key
        if item.status in ACTIVE_STATUSES and canonical_key in active_keys:
            # Preserve both legacy jobs and both statuses. A deterministic
            # migration-only key lets the partial unique constraint be added
            # without silently choosing between duplicate legacy batches.
            dedupe_key = hashlib.sha256(
                f"{canonical_key}:legacy-item:{item.pk}".encode("utf-8")
            ).hexdigest()
        if item.status in ACTIVE_STATUSES:
            active_keys.add(dedupe_key)
        item.dedupe_key = dedupe_key
        item.requires_operator_review = True
        item.save(update_fields=["dedupe_key", "requires_operator_review"])


class Migration(migrations.Migration):

    dependencies = [
        ("tabel_app", "0017_enforce_college_branches"),
    ]

    operations = [
        migrations.AlterField(
            model_name="monthlystudentreportbatch",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("processing", "Processing"),
                    ("completed", "Completed"),
                    ("cancelled", "Cancelled"),
                ],
                default="queued",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="monthlystudentreportbatchitem",
            name="dedupe_key",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="monthlystudentreportbatchitem",
            name="requires_operator_review",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AlterField(
            model_name="monthlystudentreportbatchitem",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "Queued"),
                    ("processing", "Processing"),
                    ("pending", "Pending callback"),
                    ("accepted", "Accepted by Meta"),
                    ("delivered", "Delivered"),
                    ("failed", "Failed"),
                    ("skipped", "Skipped"),
                    ("cancelled", "Cancelled"),
                ],
                db_index=True,
                default="queued",
                max_length=16,
            ),
        ),
        migrations.RunPython(backfill_legacy_queue_safety, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="monthlystudentreportbatchitem",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("dedupe_key__isnull", False),
                    ("status__in", ("queued", "processing", "pending")),
                ),
                fields=("dedupe_key",),
                name="unique_active_monthly_report_context",
            ),
        ),
    ]
