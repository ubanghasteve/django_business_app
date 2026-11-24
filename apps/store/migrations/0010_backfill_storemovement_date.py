# -*- coding: utf-8 -*-
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0009_add_date_to_storemovement'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                UPDATE store_storemovement
                SET date = (
                    SELECT store_store.date
                    FROM store_store
                    WHERE store_store.id = store_storemovement.product_id
                )
                WHERE store_storemovement.date IS NULL
                AND EXISTS (
                    SELECT 1 FROM store_store
                    WHERE store_store.id = store_storemovement.product_id
                    AND store_store.date IS NOT NULL
                );
            """,
            reverse_sql="""
                -- No reverse needed for data backfill
            """,
        ),
    ]
