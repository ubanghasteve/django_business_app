# Generated for per-team-member record isolation (STEP 8 - Job Orders)

from django.db import migrations, models
import django.db.models.deletion


def backfill_product_account(apps, schema_editor):
    """Backfill account_id from created_by.account_id for existing products."""
    Product = apps.get_model("job_orders", "Product")
    for prod in Product.objects.select_related("created_by").filter(created_by__isnull=False):
        if getattr(prod.created_by, "account_id", None):
            prod.account_id = prod.created_by.account_id
            prod.save(update_fields=["account_id"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("job_orders", "0004_add_view_jobordertemplate"),
        ("core", "0008_account_owner_set_null"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="account",
            field=models.ForeignKey(
                blank=True,
                help_text="Tenant account; set from created_by.account on save if missing.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="job_order_products",
                to="core.account",
            ),
        ),
        migrations.RunPython(backfill_product_account, noop_reverse),
        migrations.AddIndex(
            model_name="product",
            index=models.Index(fields=["account", "-date_created"], name="job_orders__account_idx"),
        ),
    ]
