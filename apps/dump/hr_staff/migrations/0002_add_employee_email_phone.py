# Generated manually for Employee email/phone

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hr_staff', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='email',
            field=models.EmailField(blank=True, default='', max_length=254),
        ),
        migrations.AddField(
            model_name='employee',
            name='phone',
            field=models.CharField(blank=True, default='', max_length=50),
        ),
    ]
