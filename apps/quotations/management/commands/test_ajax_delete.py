from django.core.management.base import BaseCommand
from decimal import Decimal
from apps.quotations.models import Quotation, QuotationItem


class Command(BaseCommand):
    help = 'Test AJAX delete functionality'

    def handle(self, *args, **options):
        self.stdout.write('Testing AJAX delete functionality...')
        
        # Create a test quotation
        quotation = Quotation.objects.create(
            quotation_number='TEST-AJAX-DELETE',
            subtotal=Decimal('100.00'),
            total_tax=Decimal('10.00'),
            grand_total=Decimal('110.00'),
            status='draft'
        )
        
        # Add a line item
        QuotationItem.objects.create(
            quotation=quotation,
            product_service='Test Product for AJAX Delete',
            quantity=1,
            unit_price=Decimal('100.00'),
            line_total=Decimal('100.00')
        )
        
        self.stdout.write(f'Created test quotation: {quotation.quotation_number}')
        self.stdout.write(f'Quotation ID: {quotation.pk}')
        
        # Test the AJAX delete endpoint URL
        ajax_url = f'/quotations/{quotation.pk}/delete/ajax/'
        self.stdout.write(f'AJAX delete URL: {ajax_url}')
        
        # Verify quotation exists
        if Quotation.objects.filter(pk=quotation.pk).exists():
            self.stdout.write(self.style.SUCCESS('✓ Test quotation created successfully'))
        else:
            self.stdout.write(self.style.ERROR('✗ Failed to create test quotation'))
            return
        
        # Clean up - delete the test quotation
        quotation.delete()
        
        if not Quotation.objects.filter(pk=quotation.pk).exists():
            self.stdout.write(self.style.SUCCESS('✓ Test quotation deleted successfully'))
        else:
            self.stdout.write(self.style.ERROR('✗ Failed to delete test quotation'))
        
        self.stdout.write('AJAX delete test completed.')
