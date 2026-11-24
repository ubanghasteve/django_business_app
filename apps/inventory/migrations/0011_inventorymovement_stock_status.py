from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0010_inventorymovement'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventorymovement',
            name='stock_status',
            field=models.CharField(
                choices=[
                    ('out_of_stock', 'Out of Stock'),
                    ('low_stock', 'Low Stock'),
                    ('in_stock', 'In Stock'),
                ],
                max_length=20,
                default='out_of_stock',
                help_text='Stock status snapshot (in_stock, low_stock, out_of_stock) at the time of movement.',
            ),
            preserve_default=False,
        ),
    ]

