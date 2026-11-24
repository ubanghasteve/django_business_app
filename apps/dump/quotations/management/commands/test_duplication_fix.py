from django.core.management.base import BaseCommand
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser
from decimal import Decimal
from apps.quotations.models import Quotation, QuotationItem
from apps.quotations.views import quotation_create


class Command(BaseCommand):
    help = 'Test quotation duplication fix'

    def handle(self, *args, **options):
        self.stdout.write('Testing quotation duplication fix...')
        
        # Count initial quotations
        initial_count = Quotation.objects.count()
        self.stdout.write(f'Initial quotation count: {initial_count}')
        
        # Create a mock request factory
        factory = RequestFactory()
        
        # Test data
        test_data = {
            'client_name': 'Test Client',
            'total_tax': '10.00',
            'total_discount': '0.00',
            'shipping_fee': '0.00',
            'other_charges': '0.00',
            'terms': 'Test terms',
            'notes': 'Test notes',
            'items-TOTAL_FORMS': '1',
            'items-INITIAL_FORMS': '0',
            'items-MIN_NUM_FORMS': '0',
            'items-MAX_NUM_FORMS': '1000',
            'items-0-product_service': 'Test Product',
            'items-0-description': 'Test Description',
            'items-0-quantity': '1',
            'items-0-unit_price': '100.00',
            'items-0-id': '',
            'items-0-DELETE': '',
        }
        
        # Simulate creating a quotation
        request = factory.post('/quotations/create/', data=test_data)
        request.user = AnonymousUser()
        
        # Create the quotation
        response = quotation_create(request)
        
        # Count quotations after creation
        final_count = Quotation.objects.count()
        self.stdout.write(f'Final quotation count: {final_count}')
        
        # Check if only one quotation was created
        if final_count == initial_count + 1:
            self.stdout.write(
                self.style.SUCCESS('✓ Duplication fix working correctly - only 1 quotation created')
            )
        else:
            self.stdout.write(
                self.style.ERROR(f'✗ Duplication still exists - {final_count - initial_count} quotations created')
            )
        
        # Clean up test data
        Quotation.objects.filter(client__name='Test Client').delete()
        
        self.stdout.write('Test completed.')
