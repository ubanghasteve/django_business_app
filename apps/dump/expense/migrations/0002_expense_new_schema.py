# Migration: Replace expense table with new schema (Expense Date, Category, Department, etc.)

from decimal import Decimal

from django.db import migrations, models
from django.utils import timezone
from django.core.validators import MinValueValidator


def copy_old_to_new(apps, schema_editor):
    Expense = apps.get_model('expense', 'Expense')
    for obj in Expense.objects.all():
        if hasattr(obj, 'quantity_in'):
            obj.quantity_purchased = obj.quantity_in or Decimal('0')
        if hasattr(obj, 'category'):
            obj.product_category = obj.category or ''
        if hasattr(obj, 'remark'):
            obj.description = obj.remark or ''
        if hasattr(obj, 'approval_status'):
            obj.status = obj.approval_status or 'draft'
        if hasattr(obj, 'low_stock_threshold'):
            obj.quantity_threshold = obj.low_stock_threshold or Decimal('0')
        if obj.created_at:
            obj.expense_date = obj.created_at.date()
        else:
            obj.expense_date = timezone.now().date()
        if hasattr(obj, 'quantity_in') and hasattr(obj, 'unit_price'):
            obj.subtotal = (obj.quantity_in or Decimal('0')) * (obj.unit_price or Decimal('0'))
        obj.tax = Decimal('0')
        obj.discount = Decimal('0')
        obj.total_amount = obj.subtotal - obj.discount + obj.tax
        obj.save(update_fields=[
            'quantity_purchased', 'product_category', 'description', 'status',
            'quantity_threshold', 'expense_date', 'subtotal', 'tax', 'discount', 'total_amount',
        ])


class Migration(migrations.Migration):

    dependencies = [
        ('expense', '0002_alter_expense_options_and_more'),
    ]

    operations = [
        # Add new fields (nullable or with defaults)
        migrations.AddField(
            model_name='expense',
            name='expense_date',
            field=models.DateField(default=None, null=True),
        ),
        migrations.AddField(
            model_name='expense',
            name='expense_category',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='expense',
            name='department',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='expense',
            name='po_number',
            field=models.CharField(blank=True, max_length=100, verbose_name='PO Number'),
        ),
        migrations.AddField(
            model_name='expense',
            name='description',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='expense',
            name='product_id',
            field=models.CharField(blank=True, max_length=100, verbose_name='Product ID'),
        ),
        migrations.AddField(
            model_name='expense',
            name='product_category',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='expense',
            name='product_description',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='expense',
            name='unit_of_measurement',
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name='expense',
            name='quantity_purchased',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, validators=[MinValueValidator(Decimal('0'))]),
        ),
        migrations.AddField(
            model_name='expense',
            name='quantity_threshold',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=14, validators=[MinValueValidator(Decimal('0'))]),
        ),
        migrations.AddField(
            model_name='expense',
            name='subtotal',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=16, validators=[MinValueValidator(Decimal('0'))]),
        ),
        migrations.AddField(
            model_name='expense',
            name='tax',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=16, validators=[MinValueValidator(Decimal('0'))]),
        ),
        migrations.AddField(
            model_name='expense',
            name='discount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0'), max_digits=16, validators=[MinValueValidator(Decimal('0'))]),
        ),
        migrations.AddField(
            model_name='expense',
            name='payment_method',
            field=models.CharField(blank=True, choices=[('cash', 'Cash'), ('card', 'Card'), ('transfer', 'Bank Transfer'), ('cheque', 'Cheque'), ('mobile', 'Mobile Money'), ('other', 'Other')], default='other', max_length=20),
        ),
        migrations.AddField(
            model_name='expense',
            name='payment_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='expense',
            name='receipt_upload',
            field=models.FileField(blank=True, null=True, upload_to='expense/receipts/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='expense',
            name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='draft', max_length=20),
        ),
        migrations.RunPython(copy_old_to_new, migrations.RunPython.noop),
        # Remove indexes first (SQLite requires dropping indexes before dropping columns they reference)
        migrations.RemoveIndex(model_name='expense', name='expense_exp_approva_0dbaa4_idx'),
        migrations.RemoveIndex(model_name='expense', name='expense_exp_stock_s_23abcd_idx'),
        migrations.RemoveIndex(model_name='expense', name='expense_exp_workflo_f2267e_idx'),
        migrations.RemoveIndex(model_name='expense', name='expense_exp_stock_l_95ba0c_idx'),
        # Remove old fields
        migrations.RemoveField(model_name='expense', name='category'),
        migrations.RemoveField(model_name='expense', name='company_name'),
        migrations.RemoveField(model_name='expense', name='stock_location'),
        migrations.RemoveField(model_name='expense', name='phone_number'),
        migrations.RemoveField(model_name='expense', name='quantity_in'),
        migrations.RemoveField(model_name='expense', name='balance_quantity'),
        migrations.RemoveField(model_name='expense', name='low_stock_threshold'),
        migrations.RemoveField(model_name='expense', name='stock_status'),
        migrations.RemoveField(model_name='expense', name='approval_status'),
        migrations.RemoveField(model_name='expense', name='workflow_status'),
        migrations.RemoveField(model_name='expense', name='remark'),
        migrations.AlterField(
            model_name='expense',
            name='product_name',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(fields=['company', '-expense_date'], name='expense_exp_company_exp_idx'),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(fields=['status'], name='expense_exp_status_idx'),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(fields=['expense_category'], name='expense_exp_exp_cat_idx'),
        ),
    ]
