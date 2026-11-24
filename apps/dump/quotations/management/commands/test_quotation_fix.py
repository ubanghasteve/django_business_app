from django.core.management.base import BaseCommand
from decimal import Decimal
from apps.quotations.models import Quotation, QuotationItem


class Command(BaseCommand):
    help = 'Test quotation creation and tax calculation fixes'

    def handle(self, *args, **options):
        self.stdout.write('Testing quotation tax calculation fixes...')
        
        # Test 1: Create a quotation with percentage tax
        self.stdout.write('\nTest 1: Creating quotation with 10% tax...')
        quotation1 = Quotation.objects.create(
            quotation_number='TEST-001',
            subtotal=Decimal('1000.00'),
            total_tax=Decimal('10.00'),  # 10% tax
            status='draft'
        )
        
        # Add line item
        QuotationItem.objects.create(
            quotation=quotation1,
            product_service='Test Product',
            quantity=1,
            unit_price=Decimal('1000.00'),
            line_total=Decimal('1000.00')
        )
        
        # Calculate totals
        quotation1.calculate_totals()
        quotation1.refresh_from_db()
        
        self.stdout.write(f'Subtotal: {quotation1.subtotal}')
        self.stdout.write(f'Tax: {quotation1.total_tax}')
        self.stdout.write(f'Grand Total: {quotation1.grand_total}')
        
        # Test 2: Create a quotation with fixed tax amount
        self.stdout.write('\nTest 2: Creating quotation with $50 fixed tax...')
        quotation2 = Quotation.objects.create(
            quotation_number='TEST-002',
            subtotal=Decimal('1000.00'),
            total_tax=Decimal('50.00'),  # $50 fixed tax
            status='draft'
        )
        
        # Add line item
        QuotationItem.objects.create(
            quotation=quotation2,
            product_service='Test Product',
            quantity=1,
            unit_price=Decimal('1000.00'),
            line_total=Decimal('1000.00')
        )
        
        # Calculate totals
        quotation2.calculate_totals()
        quotation2.refresh_from_db()
        
        self.stdout.write(f'Subtotal: {quotation2.subtotal}')
        self.stdout.write(f'Tax: {quotation2.total_tax}')
        self.stdout.write(f'Grand Total: {quotation2.grand_total}')
        
        # Test 3: Create a quotation with decimal percentage tax
        self.stdout.write('\nTest 3: Creating quotation with 0.15 (15%) tax...')
        quotation3 = Quotation.objects.create(
            quotation_number='TEST-003',
            subtotal=Decimal('1000.00'),
            total_tax=Decimal('0.15'),  # 15% tax as decimal
            status='draft'
        )
        
        # Add line item
        QuotationItem.objects.create(
            quotation=quotation3,
            product_service='Test Product',
            quantity=1,
            unit_price=Decimal('1000.00'),
            line_total=Decimal('1000.00')
        )
        
        # Calculate totals
        quotation3.calculate_totals()
        quotation3.refresh_from_db()
        
        self.stdout.write(f'Subtotal: {quotation3.subtotal}')
        self.stdout.write(f'Tax: {quotation3.total_tax}')
        self.stdout.write(f'Grand Total: {quotation3.grand_total}')
        
        # Clean up test quotations
        quotation1.delete()
        quotation2.delete()
        quotation3.delete()
        
        self.stdout.write(
            self.style.SUCCESS('All tests completed successfully!')
        )
