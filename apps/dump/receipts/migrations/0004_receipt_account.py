# Generated for per-team-member record isolation (STEP 8 - Receipts)

from django.db import migrations, models
import django.db.models.deletion


def backfill_receipt_account(apps, schema_editor):
    """Backfill account_id from invoice.user.account_id or created_by.account_id."""
    Receipt = apps.get_model("receipts", "Receipt")
    for rec in Receipt.objects.select_related("invoice", "invoice__user", "created_by").all():
        account_id = None
        if getattr(rec, "invoice_id", None) and rec.invoice_id:
            try:
                inv = rec.invoice
                if getattr(inv, "user_id", None) and getattr(inv.user, "account_id", None):
                    account_id = inv.user.account_id
            except Exception:
                pass
        if not account_id and getattr(rec, "created_by_id", None) and rec.created_by_id:
            try:
                if getattr(rec.created_by, "account_id", None):
                    account_id = rec.created_by.account_id
            except Exception:
                pass
        if account_id:
            rec.account_id = account_id
            rec.save(update_fields=["account_id"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("receipts", "0003_alter_receipt_options"),
        ("core", "0008_account_owner_set_null"),
    ]

    operations = [
        migrations.AddField(
            model_name="receipt",
            name="account",
            field=models.ForeignKey(
                blank=True,
                help_text="Tenant account; set from invoice or created_by on save if missing.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="receipts",
                to="core.account",
            ),
        ),
        migrations.RunPython(backfill_receipt_account, noop_reverse),
        migrations.AddIndex(
            model_name="receipt",
            index=models.Index(fields=["account", "-created_at"], name="rec_account_created_idx"),
        ),
    ]
