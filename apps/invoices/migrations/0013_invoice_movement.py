# -*- coding: utf-8 -*-
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('invoices', '0012_alter_invoice_options'),
    ]

    operations = [
        migrations.CreateModel(
            name='InvoiceMovement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('client_name', models.CharField(blank=True, default='', help_text='Client name at time of movement.', max_length=200)),
                ('client_phone', models.CharField(blank=True, default='', help_text='Client phone at time of movement.', max_length=20)),
                ('client_email', models.EmailField(blank=True, default='', help_text='Client email at time of movement.', max_length=254)),
                ('client_address', models.TextField(blank=True, default='', help_text='Client address at time of movement.')),
                ('subtotal', models.DecimalField(decimal_places=2, default='0', help_text='Subtotal at time of movement.', max_digits=12)),
                ('total_tax', models.DecimalField(decimal_places=2, default='0', help_text='Total tax at time of movement.', max_digits=12)),
                ('tax_type', models.CharField(choices=[('percentage', 'Percentage (%)'), ('fixed', 'Fixed Amount (₦)')], default='percentage', max_length=15)),
                ('tax_value', models.DecimalField(decimal_places=2, default='0', max_digits=10)),
                ('total_discount', models.DecimalField(decimal_places=2, default='0', help_text='Total discount at time of movement.', max_digits=12)),
                ('discount_type', models.CharField(choices=[('percentage', 'Percentage (%)'), ('fixed', 'Fixed Amount (₦)')], default='percentage', max_length=15)),
                ('discount_value', models.DecimalField(decimal_places=2, default='0', max_digits=10)),
                ('shipping_fee', models.DecimalField(decimal_places=2, default='0', max_digits=12)),
                ('other_charges', models.DecimalField(decimal_places=2, default='0', max_digits=12)),
                ('grand_total', models.DecimalField(decimal_places=2, default='0', help_text='Grand total at time of movement.', max_digits=12)),
                ('amount_paid', models.DecimalField(decimal_places=2, default='0', help_text='Amount paid at time of movement.', max_digits=12)),
                ('balance_due', models.DecimalField(decimal_places=2, default='0', help_text='Balance due at time of movement.', max_digits=12)),
                ('status', models.CharField(choices=[('unpaid', 'Unpaid'), ('partial', 'Partially Paid'), ('paid', 'Paid'), ('delivered', 'Delivered')], default='unpaid', help_text='Status at time of movement.', max_length=15)),
                ('notes', models.TextField(blank=True, default='', help_text='Notes at time of movement.')),
                ('show_bank_details', models.BooleanField(default=True, help_text='Show bank details at time of movement.')),
                ('show_signature', models.BooleanField(default=True, help_text='Show signature at time of movement.')),
                ('items_snapshot', models.JSONField(default=list, help_text='Snapshot of invoice items at time of movement.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='invoice_movements_created', to='auth.user')),
                ('invoice', models.ForeignKey(help_text='Invoice this movement belongs to.', on_delete=django.db.models.deletion.CASCADE, related_name='movements', to='invoices.invoice')),
            ],
            options={
                'verbose_name': 'Invoice Movement',
                'verbose_name_plural': 'Invoice Movements',
                'ordering': ['created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='invoicemovement',
            index=models.Index(fields=['invoice', '-created_at'], name='invoices_inv_invoice_4e8e8e_idx'),
        ),
    ]
