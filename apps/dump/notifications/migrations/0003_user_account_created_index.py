# Generated for query optimization: list/badge filter by user+account, order by created_at

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('notifications', '0002_action_url_charfield'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='notification',
            index=models.Index(
                fields=['user', 'account', '-created_at'],
                name='notif_user_account_created',
            ),
        ),
    ]
