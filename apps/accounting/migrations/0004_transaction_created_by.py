# Generated for per-team-member record isolation (Accounting / Transaction)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_transaction_created_by(apps, schema_editor):
    """Backfill created_by_id from user_id for existing transactions."""
    Transaction = apps.get_model("accounting", "Transaction")
    for txn in Transaction.objects.select_related("user").filter(user__isnull=False):
        txn.created_by_id = txn.user_id
        txn.save(update_fields=["created_by_id"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0003_transaction_discount_type_transaction_discount_value_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="transaction",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                help_text="User who created this transaction; set from user on save if missing.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="accounting_transactions_created",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_transaction_created_by, noop_reverse),
    ]
