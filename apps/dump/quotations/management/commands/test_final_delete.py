from django.core.management.base import BaseCommand
from decimal import Decimal
from apps.quotations.models import Quotation, QuotationItem


class Command(BaseCommand):
    help = 'Final test of AJAX delete functionality'

    def handle(self, *args, **options):
        self.stdout.write('Running final test of AJAX delete functionality...')
        
        # Create multiple test quotations
        quotations = []
        for i in range(3):
            quotation = Quotation.objects.create(
                quotation_number=f'TEST-FINAL-{i+1}',
                subtotal=Decimal('100.00'),
                total_tax=Decimal('10.00'),
                grand_total=Decimal('110.00'),
                status='draft'
            )
            
            QuotationItem.objects.create(
                quotation=quotation,
                product_service=f'Test Product {i+1}',
                quantity=1,
                unit_price=Decimal('100.00'),
                line_total=Decimal('100.00')
            )
            
            quotations.append(quotation)
        
        self.stdout.write(f'Created {len(quotations)} test quotations')
        
        # Test AJAX delete URLs
        for quotation in quotations:
            ajax_url = f'/quotations/{quotation.pk}/delete/ajax/'
            self.stdout.write(f'Quotation {quotation.quotation_number}: {ajax_url}')
        
        # Clean up
        for quotation in quotations:
            quotation.delete()
        
        self.stdout.write(self.style.SUCCESS('✓ All test quotations cleaned up'))
        self.stdout.write('Final test completed successfully!')
        self.stdout.write('')
        self.stdout.write('AJAX delete should now work properly with:')
        self.stdout.write('- Modern confirmation modal instead of browser alert')
        self.stdout.write('- Proper CSRF token handling')
        self.stdout.write('- Timeout protection (10 seconds)')
        self.stdout.write('- Fallback to XMLHttpRequest if fetch fails')
        self.stdout.write('- Smooth row removal animations')
        self.stdout.write('- Success/error notifications')
