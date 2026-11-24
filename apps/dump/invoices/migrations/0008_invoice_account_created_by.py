# Generated for per-team-member record isolation (STEP 4)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_invoice_account_created_by(apps, schema_editor):
    """Backfill account_id and created_by_id from user_id for existing invoices."""
    Invoice = apps.get_model("invoices", "Invoice")
    User = apps.get_model(settings.AUTH_USER_MODEL)
    for inv in Invoice.objects.select_related("user").filter(user__isnull=False):
        if getattr(inv.user, "account_id", None):
            inv.account_id = inv.user.account_id
            inv.created_by_id = inv.user_id
            inv.save(update_fields=["account_id", "created_by_id"])


def noop_reverse(apps, schema_editor):
    """No data to reverse; columns are dropped by migration framework."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0007_alter_invoice_options"),
        ("core", "0008_account_owner_set_null"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="invoice",
            name="account",
            field=models.ForeignKey(
                blank=True,
                help_text="Tenant account; set from user.account on save if missing.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="invoices",
                to="core.account",
            ),
        ),
        migrations.AddField(
            model_name="invoice",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                help_text="User who created this invoice; set from user on save if missing.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="invoices_created",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_invoice_account_created_by, noop_reverse),
        migrations.AddIndex(
            model_name="invoice",
            index=models.Index(fields=["account", "-created_at"], name="inv_account_created_at_idx"),
        ),
    ]
