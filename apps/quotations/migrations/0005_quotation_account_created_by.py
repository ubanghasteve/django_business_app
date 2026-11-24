# Generated for per-team-member record isolation (STEP 8 - Quotations)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_quotation_account_created_by(apps, schema_editor):
    """Backfill account_id and created_by_id from user_id for existing quotations."""
    Quotation = apps.get_model("quotations", "Quotation")
    for q in Quotation.objects.select_related("user").filter(user__isnull=False):
        if getattr(q.user, "account_id", None):
            q.account_id = q.user.account_id
            q.created_by_id = q.user_id
            q.save(update_fields=["account_id", "created_by_id"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("quotations", "0004_alter_quotation_options"),
        ("core", "0008_account_owner_set_null"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="quotation",
            name="account",
            field=models.ForeignKey(
                blank=True,
                help_text="Tenant account; set from user.account on save if missing.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="quotations",
                to="core.account",
            ),
        ),
        migrations.AddField(
            model_name="quotation",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                help_text="User who created this quotation; set from user on save if missing.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="quotations_created",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(backfill_quotation_account_created_by, noop_reverse),
        migrations.AddIndex(
            model_name="quotation",
            index=models.Index(fields=["account", "-created_at"], name="quotations__account_idx"),
        ),
    ]
