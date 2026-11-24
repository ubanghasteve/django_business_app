# Generated for Expense app - single Expense model (duplicate structure of Inventory)

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.core.validators import MinValueValidator
from decimal import Decimal
from django.db.models import Q


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0008_account_owner_set_null'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Expense',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('transaction_id', models.CharField(editable=False, help_text='EXP- + 4 unique digits per company (e.g. EXP-3847).', max_length=64)),
                ('sn', models.PositiveIntegerField(default=0, editable=False, help_text='Auto-increment per company (S/N).')),
                ('product_name', models.CharField(max_length=255)),
                ('category', models.CharField(blank=True, max_length=100)),
                ('company_name', models.CharField(blank=True, help_text='Company name; fillable. When empty, display uses company FK.', max_length=255)),
                ('vendor', models.CharField(blank=True, max_length=255)),
                ('stock_location', models.CharField(blank=True, max_length=255)),
                ('phone_number', models.CharField(blank=True, max_length=50)),
                ('quantity_in', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, validators=[MinValueValidator(Decimal('0'))])),
                ('quantity_out', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, validators=[MinValueValidator(Decimal('0'))])),
                ('unit_price', models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, validators=[MinValueValidator(Decimal('0'))])),
                ('total_amount', models.DecimalField(decimal_places=2, default=Decimal('0'), editable=False, max_digits=16)),
                ('balance_quantity', models.DecimalField(decimal_places=2, default=Decimal('0'), editable=False, max_digits=14)),
                ('low_stock_threshold', models.DecimalField(decimal_places=2, default=Decimal('10'), max_digits=14, validators=[MinValueValidator(Decimal('0'))])),
                ('stock_status', models.CharField(choices=[('out_of_stock', 'Out of Stock'), ('low_stock', 'Low Stock'), ('in_stock', 'In Stock')], default='in_stock', editable=False, max_length=20)),
                ('approval_status', models.CharField(choices=[('draft', 'Draft'), ('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='draft', max_length=20)),
                ('workflow_status', models.CharField(choices=[('draft', 'Draft'), ('pending_approval', 'Pending Approval'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('posted', 'Posted')], default='draft', max_length=20)),
                ('remark', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('account', models.ForeignKey(blank=True, help_text='Tenant account; set from user.account on save if missing.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='expense_records', to='core.account')),
                ('company', models.ForeignKey(blank=True, help_text='Company profile; set from user company on save if missing.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='expense_records', to='core.companyprofile')),
                ('created_by', models.ForeignKey(blank=True, help_text='User who created this record.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='expense_records_created', to=settings.AUTH_USER_MODEL)),
                ('approved_by', models.ForeignKey(blank=True, help_text='User who set approval status to Approved.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='expense_records_approved', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Expense',
                'verbose_name_plural': 'Expense',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='expense',
            constraint=models.UniqueConstraint(condition=Q(company_id__isnull=False), fields=('company', 'transaction_id'), name='expense_company_txn_id_uniq'),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(fields=['company', '-created_at'], name='expense_exp_company_2a1_idx'),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(fields=['transaction_id'], name='expense_exp_transac_2a1_idx'),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(fields=['approval_status'], name='expense_exp_approva_2a1_idx'),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(fields=['stock_status'], name='expense_exp_stock_s_2a1_idx'),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(fields=['workflow_status'], name='expense_exp_workflo_2a1_idx'),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(fields=['product_name'], name='expense_exp_product_2a1_idx'),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(fields=['vendor'], name='expense_exp_vendor__2a1_idx'),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(fields=['stock_location'], name='expense_exp_stock_l_2a1_idx'),
        ),
    ]
