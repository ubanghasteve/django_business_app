# Generated manually for inventory receipt logs and waste quantity_input

from decimal import Decimal
import django.core.validators
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('inventory', '0020_inventory_issue'),
    ]

    operations = [
        migrations.AddField(
            model_name='wastelog',
            name='quantity_input',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Original user input (e.g. "2 Rolls").',
                max_length=255,
            ),
        ),
        migrations.CreateModel(
            name='InventoryReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.DecimalField(
                    decimal_places=2,
                    default=Decimal('0'),
                    help_text='Quantity received in this delivery only.',
                    max_digits=14,
                    validators=[django.core.validators.MinValueValidator(Decimal('0.01'))],
                )),
                ('quantity_input', models.CharField(
                    blank=True,
                    default='',
                    help_text='Original user input (e.g. "10 Rolls").',
                    max_length=255,
                )),
                ('supplier_name', models.CharField(
                    blank=True,
                    help_text='Supplier or source of this stock.',
                    max_length=255,
                )),
                ('received_at', models.DateTimeField(
                    default=django.utils.timezone.now,
                    help_text='Date and time when stock was received.',
                )),
                ('remark', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('account', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='inventory_receipts',
                    to='core.account',
                )),
                ('company', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='inventory_receipts',
                    to='core.companyprofile',
                )),
                ('created_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='inventory_receipts_created',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('inventory', models.ForeignKey(
                    help_text='Inventory row this receipt belongs to.',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='receipts',
                    to='inventory.inventory',
                )),
            ],
            options={
                'verbose_name': 'Inventory Receipt',
                'verbose_name_plural': 'Inventory Receipts',
                'ordering': ['-received_at', '-pk'],
            },
        ),
        migrations.AddIndex(
            model_name='inventoryreceipt',
            index=models.Index(fields=['inventory', '-received_at'], name='inventory_i_invento_8a1f2d_idx'),
        ),
        migrations.AddIndex(
            model_name='inventoryreceipt',
            index=models.Index(fields=['company', '-received_at'], name='inventory_i_company_4c2e1a_idx'),
        ),
        migrations.AddIndex(
            model_name='inventoryreceipt',
            index=models.Index(fields=['supplier_name'], name='inventory_i_supplie_9b3f4c_idx'),
        ),
    ]
