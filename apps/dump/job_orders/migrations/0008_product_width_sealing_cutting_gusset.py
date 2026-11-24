# Generated migration: add Width, Sealing Type, Cutting, Gusset to Product

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('job_orders', '0007_product_order_quantity_char'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='width',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='product',
            name='sealing_type',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='product',
            name='cutting',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='product',
            name='gusset',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
