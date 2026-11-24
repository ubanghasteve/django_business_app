from django.core.management.base import BaseCommand
from decimal import Decimal
from apps.quotations.models import Quotation, QuotationItem
from apps.core.utils import format_currency


class Command(BaseCommand):
    help = 'Test currency formatting with commas'

    def handle(self, *args, **options):
        self.stdout.write('Testing currency formatting...')
        
        # Test various amounts
        test_amounts = [
            Decimal('100.00'),
            Decimal('1000.00'),
            Decimal('10000.00'),
            Decimal('100000.00'),
            Decimal('1000000.00'),
            Decimal('1234.56'),
            Decimal('123456.78'),
            Decimal('1234567.89'),
        ]
        
        self.stdout.write('\nTesting format_currency function:')
        for amount in test_amounts:
            formatted = format_currency(amount, '$', 2)
            self.stdout.write(f'{amount:>12} -> {formatted}')
        
        # Test with different currency symbols
        self.stdout.write('\nTesting with different currency symbols:')
        test_amount = Decimal('1234567.89')
        symbols = ['$', '₦', '€', '£', '¥', '₹']
        
        for symbol in symbols:
            formatted = format_currency(test_amount, symbol, 2)
            self.stdout.write(f'{symbol} -> {formatted}')
        
        # Test PDF safe formatting
        self.stdout.write('\nTesting PDF safe formatting:')
        for symbol in ['₦', '₹', '₽', '₩']:
            formatted_normal = format_currency(test_amount, symbol, 2, pdf_safe=False)
            formatted_pdf = format_currency(test_amount, symbol, 2, pdf_safe=True)
            self.stdout.write(f'{symbol} Normal: {formatted_normal}')
            self.stdout.write(f'{symbol} PDF Safe: {formatted_pdf}')
        
        # Create a test quotation to see actual formatting
        self.stdout.write('\nCreating test quotation...')
        quotation = Quotation.objects.create(
            quotation_number='TEST-FORMAT',
            subtotal=Decimal('1234567.89'),
            total_tax=Decimal('123456.79'),
            total_discount=Decimal('12345.68'),
            shipping_fee=Decimal('1234.57'),
            other_charges=Decimal('123.46'),
            grand_total=Decimal('1358036.03'),
            status='draft'
        )
        
        # Add a line item
        QuotationItem.objects.create(
            quotation=quotation,
            product_service='Test Product for Formatting',
            quantity=Decimal('123.45'),
            unit_price=Decimal('10000.00'),
            line_total=Decimal('1234500.00')
        )
        
        self.stdout.write(f'Created quotation: {quotation.quotation_number}')
        self.stdout.write(f'Subtotal: {format_currency(quotation.subtotal)}')
        self.stdout.write(f'Tax: {format_currency(quotation.total_tax)}')
        self.stdout.write(f'Discount: {format_currency(quotation.total_discount)}')
        self.stdout.write(f'Shipping: {format_currency(quotation.shipping_fee)}')
        self.stdout.write(f'Other Charges: {format_currency(quotation.other_charges)}')
        self.stdout.write(f'Grand Total: {format_currency(quotation.grand_total)}')
        
        # Test line item formatting
        item = quotation.items.first()
        if item:
            self.stdout.write(f'Line Item - Unit Price: {format_currency(item.unit_price)}')
            self.stdout.write(f'Line Item - Line Total: {format_currency(item.line_total)}')
        
        # Clean up
        quotation.delete()
        self.stdout.write('\n✓ Test quotation cleaned up')
        
        self.stdout.write('\nCurrency formatting test completed!')
        self.stdout.write('If you see commas in the output above, formatting is working correctly.')
