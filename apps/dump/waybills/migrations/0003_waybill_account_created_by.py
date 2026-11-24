# Generated for per-team-member record isolation (STEP 4)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_waybill_account_created_by(apps, schema_editor):
    """Backfill account_id and created_by_id from user_id for existing waybills."""
    Waybill = apps.get_model("waybills", "Waybill")
    User = apps.get_model(settings.AUTH_USER_MODEL)
    for wb in Waybill.objects.select_related("user").filter(user__isnull=False):
        if getattr(wb.user, "account_id", None):
            wb.account_id = wb.user.account_id
            wb.created_by_id = wb.user_id
            wb.save(update_fields=["account_id", "created_by_id"])


def noop_reverse(apps, schema_editor):
    """No data to reverse; columns are dropped by migration framework."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("waybills", "0002_alter_waybill_options"),
        ("core", "0008_account_owner_set_null"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="waybill",
            name="account",
            field=models.ForeignKey(
                blank=True,
                help_text="Tenant account; set from user.account on save if missing.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="waybills",
                to="core.account",
            ),
        ),
        migrations.AddField(
            model_name="waybill",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                help_text="User who created this waybill; set from user on save if missing.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="waybills_created",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_waybill_account_created_by, noop_reverse),
        migrations.AddIndex(
            model_name="waybill",
            index=models.Index(fields=["account", "-created_at"], name="waybills_waybill_account_idx"),
        ),
    ]
