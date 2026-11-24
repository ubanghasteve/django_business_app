# Generated migration: add optional job_order_date to Product

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('job_orders', '0008_product_width_sealing_cutting_gusset'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='job_order_date',
            field=models.DateField(
                blank=True,
                help_text='Optional date set by user for the job order (e.g. order date).',
                null=True,
            ),
        ),
    ]
