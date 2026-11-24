from django.core.management.base import BaseCommand
from django.test import Client, RequestFactory
from django.contrib.auth.models import AnonymousUser
from decimal import Decimal
from apps.quotations.models import Quotation, QuotationItem


class Command(BaseCommand):
    help = 'Test browser-like AJAX delete request'

    def handle(self, *args, **options):
        self.stdout.write('Testing browser-like AJAX delete request...')
        
        # Create a test quotation
        quotation = Quotation.objects.create(
            quotation_number='TEST-BROWSER-DELETE',
            subtotal=Decimal('100.00'),
            total_tax=Decimal('10.00'),
            grand_total=Decimal('110.00'),
            status='draft'
        )
        
        # Add a line item
        QuotationItem.objects.create(
            quotation=quotation,
            product_service='Test Product for Browser Delete',
            quantity=1,
            unit_price=Decimal('100.00'),
            line_total=Decimal('100.00')
        )
        
        self.stdout.write(f'Created test quotation: {quotation.quotation_number} (ID: {quotation.pk})')
        
        # Test the AJAX delete endpoint
        client = Client()
        
        # First, get the quotation list page to get CSRF token
        response = client.get('/quotations/')
        self.stdout.write(f'GET /quotations/ status: {response.status_code}')
        
        # Extract CSRF token if available
        csrf_token = None
        if 'csrftoken' in client.cookies:
            csrf_token = client.cookies['csrftoken'].value
            self.stdout.write(f'CSRF token found: {csrf_token[:10]}...')
        else:
            self.stdout.write('No CSRF token found in cookies')
        
        # Test AJAX delete request
        ajax_url = f'/quotations/{quotation.pk}/delete/ajax/'
        headers = {
            'X-Requested-With': 'XMLHttpRequest',
            'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'
        }
        
        if csrf_token:
            headers['X-CSRFToken'] = csrf_token
        
        self.stdout.write(f'Making POST request to: {ajax_url}')
        delete_response = client.post(ajax_url, headers=headers)
        
        self.stdout.write(f'Delete response status: {delete_response.status_code}')
        self.stdout.write(f'Delete response content: {delete_response.content.decode()}')
        
        # Check if quotation was actually deleted
        quotation_exists = Quotation.objects.filter(pk=quotation.pk).exists()
        
        if not quotation_exists:
            self.stdout.write(self.style.SUCCESS('✓ Quotation deleted successfully via AJAX'))
        else:
            self.stdout.write(self.style.ERROR('✗ Quotation still exists after AJAX delete'))
        
        # Clean up if still exists
        if quotation_exists:
            quotation.delete()
            self.stdout.write('Cleaned up test quotation')
        
        self.stdout.write('Browser-like AJAX delete test completed.')
