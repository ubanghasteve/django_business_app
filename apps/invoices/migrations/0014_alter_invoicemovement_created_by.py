# -*- coding: utf-8 -*-
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0013_invoice_movement'),
    ]

    operations = [
        migrations.AlterField(
            model_name='invoicemovement',
            name='created_by',
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text='ID of the user who created this movement.',
            ),
        ),
    ]
