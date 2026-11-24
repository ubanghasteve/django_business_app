from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("waybills", "0005_add_sync_mixin"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="waybill",
            name="total_quantity_input",
            field=models.CharField(max_length=255, blank=True, null=True),
        ),
        migrations.AddField(
            model_name="waybill",
            name="delivered_quantity_input",
            field=models.CharField(max_length=255, blank=True, null=True),
        ),
        migrations.AddField(
            model_name="waybill",
            name="total_quantity_value",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="waybill",
            name="delivered_quantity_value",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="waybill",
            name="remaining_quantity_value",
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name="waybill",
            name="is_approved",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="waybill",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="waybill",
            name="approved_by",
            field=models.ForeignKey(
                related_name="approved_waybills",
                to=settings.AUTH_USER_MODEL,
                on_delete=models.SET_NULL,
                null=True,
                blank=True,
            ),
        ),
    ]

