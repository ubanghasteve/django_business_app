# Generated manually for Message.deleted_at

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("messaging", "0005_add_message_hidden_for_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="deleted_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When deleted for everyone",
                null=True,
            ),
        ),
    ]
