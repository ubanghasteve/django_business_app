# Generated manually for per-register payment status

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('staff_offences', '0003_authorized_signature'),
    ]

    operations = [
        migrations.AddField(
            model_name='staffoffenceregister',
            name='payment_status',
            field=models.CharField(
                choices=[
                    ('unpaid', 'Unpaid'),
                    ('partially_paid', 'Partially Paid'),
                    ('paid', 'Paid'),
                    ('waived', 'Waived'),
                    ('pending_approval', 'Pending Approval'),
                ],
                db_index=True,
                default='pending_approval',
                help_text='Payment / settlement status for this monthly register.',
                max_length=32,
            ),
        ),
    ]
