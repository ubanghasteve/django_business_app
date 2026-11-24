# Generated for offline-first SyncMixin (uuid + is_deleted + updated_at)

import uuid
from django.db import migrations, models
from django.utils import timezone


def fill_product_uuids(apps, schema_editor):
    Product = apps.get_model('job_orders', 'Product')
    for obj in Product.objects.all():
        obj.uuid = uuid.uuid4()
        obj.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('job_orders', '0009_product_job_order_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='uuid',
            field=models.UUIDField(blank=True, default=None, editable=False, null=True, unique=False),
        ),
        migrations.AddField(
            model_name='product',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, default=timezone.now),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='product',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(fill_product_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='product',
            name='uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=False, unique=True),
        ),
    ]
