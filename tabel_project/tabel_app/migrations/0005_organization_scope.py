from django.db import migrations, models
import django.db.models.deletion


def ensure_schema(apps, schema_editor):
    from tabel_app.models import Group, MentorProfile, StudentProfile, UserOrganizationAccess

    connection = schema_editor.connection
    tables = set(connection.introspection.table_names())
    for model in (MentorProfile, Group, StudentProfile):
        with connection.cursor() as cursor:
            columns = {
                column.name for column in connection.introspection.get_table_description(
                    cursor, model._meta.db_table
                )
            }
        if "organization_type" not in columns:
            schema_editor.add_field(model, model._meta.get_field("organization_type"))
    if UserOrganizationAccess._meta.db_table not in tables:
        schema_editor.create_model(UserOrganizationAccess)


def seed_access(apps, schema_editor):
    User = apps.get_model("tabel_app", "User")
    Access = apps.get_model("tabel_app", "UserOrganizationAccess")
    rows = []
    for user in User.objects.all().iterator():
        rows.append(Access(user_id=user.id, organization_type="academy"))
        if user.role == "ADMIN":
            rows.append(Access(user_id=user.id, organization_type="college"))
    Access.objects.bulk_create(rows, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("tabel_app", "0004_monthlystudentreportattempt")]

    state_operations = [
        migrations.AddField(
            model_name=name, name="organization_type",
            field=models.CharField(
                choices=[("academy", "Академия"), ("college", "Колледж")],
                db_index=True, default="academy", max_length=16,
            ),
        )
        for name in ("mentorprofile", "group", "studentprofile")
    ] + [
        migrations.CreateModel(
            name="UserOrganizationAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("organization_type", models.CharField(choices=[("academy", "Академия"), ("college", "Колледж")], default="academy", max_length=16)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="organization_accesses", to="tabel_app.user")),
            ],
            options={"constraints": [
                models.UniqueConstraint(fields=("user", "organization_type"), name="unique_user_organization_access")
            ]},
        )
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=state_operations,
            database_operations=[migrations.RunPython(ensure_schema, migrations.RunPython.noop)],
        ),
        migrations.RunPython(seed_access, migrations.RunPython.noop),
    ]
