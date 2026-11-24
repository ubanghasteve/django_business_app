# Generated migration: store delivery quantity as text for mixed input (e.g. "100 kg", "50+50")

from django.db import migrations, models


def copy_order_quantity_to_char(apps, schema_editor):
    Product = apps.get_model('job_orders', 'Product')
    for p in Product.objects.all():
        # Old field is still integer at this point (order_quantity)
        old_val = getattr(p, 'order_quantity', None)
        if old_val is not None:
            p.order_quantity_str = str(int(old_val))
        else:
            p.order_quantity_str = None
        p.save(update_fields=['order_quantity_str'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('job_orders', '0006_rename_job_orders__account_idx_job_orders__account_3d39a7_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='order_quantity_str',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.RunPython(copy_order_quantity_to_char, noop_reverse),
        migrations.RemoveField(
            model_name='product',
            name='order_quantity',
        ),
        migrations.RenameField(
            model_name='product',
            old_name='order_quantity_str',
            new_name='order_quantity',
        ),
    ]
