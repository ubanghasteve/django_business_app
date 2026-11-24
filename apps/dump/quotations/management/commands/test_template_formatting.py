from django.core.management.base import BaseCommand
from django.test import Client
from apps.accounts.models import User
from decimal import Decimal
from apps.quotations.models import Quotation, QuotationItem
from apps.core.models import CompanyProfile


class Command(BaseCommand):
    help = 'Test comma formatting in all quotation templates'

    def handle(self, *args, **options):
        self.stdout.write('Testing comma formatting in quotation templates...')
        
        # Create a test user and company profile
        user, created = User.objects.get_or_create(
            email='test@example.com',
            defaults={
                'first_name': 'Test',
                'last_name': 'User'
            }
        )
        
        company_profile, created = CompanyProfile.objects.get_or_create(
            user=user,
            defaults={
                'company_name': 'Test Company',
                'currency_symbol': '$',
                'currency_code': 'USD'
            }
        )
        
        # Create a test quotation with large numbers
        quotation = Quotation.objects.create(
            quotation_number='TEST-COMMA-FORMAT',
            user=user,
            subtotal=Decimal('1234567.89'),
            total_tax=Decimal('123456.79'),
            total_discount=Decimal('12345.68'),
            shipping_fee=Decimal('1234.57'),
            other_charges=Decimal('123.46'),
            grand_total=Decimal('1358036.03'),
            status='draft'
        )
        
        # Add line items with large numbers
        QuotationItem.objects.create(
            quotation=quotation,
            product_service='Expensive Product 1',
            quantity=Decimal('100.00'),
            unit_price=Decimal('10000.00'),
            line_total=Decimal('1000000.00')
        )
        
        QuotationItem.objects.create(
            quotation=quotation,
            product_service='Expensive Product 2',
            quantity=Decimal('50.00'),
            unit_price=Decimal('5000.00'),
            line_total=Decimal('250000.00')
        )
        
        self.stdout.write(f'Created test quotation: {quotation.quotation_number}')
        
        # Test client
        client = Client()
        
        # Test different templates
        test_urls = [
            ('quotation_detail', f'/quotations/{quotation.pk}/'),
            ('quotation_pdf', f'/quotations/{quotation.pk}/pdf/'),
            ('quotation_print', f'/quotations/{quotation.pk}/print/'),
            ('quotation_list', '/quotations/'),
        ]
        
        formatting_tests = []
        
        for url_name, url in test_urls:
            try:
                response = client.get(url)
                if response.status_code == 200:
                    content = response.content.decode()
                    
                    # Check for comma formatting in the content
                    has_commas = ',' in content
                    has_large_numbers = any(str(num) in content for num in [
                        '1,234,567.89', '123,456.79', '12,345.68', '1,234.57', 
                        '1,358,036.03', '1,000,000.00', '250,000.00'
                    ])
                    
                    formatting_tests.append({
                        'template': url_name,
                        'url': url,
                        'status': response.status_code,
                        'has_commas': has_commas,
                        'has_large_numbers': has_large_numbers,
                        'success': has_commas and has_large_numbers
                    })
                    
                    if has_commas and has_large_numbers:
                        self.stdout.write(self.style.SUCCESS(f'✓ {url_name}: Comma formatting working'))
                    else:
                        self.stdout.write(self.style.WARNING(f'⚠ {url_name}: May need comma formatting'))
                        
                else:
                    formatting_tests.append({
                        'template': url_name,
                        'url': url,
                        'status': response.status_code,
                        'has_commas': False,
                        'has_large_numbers': False,
                        'success': False
                    })
                    self.stdout.write(self.style.ERROR(f'✗ {url_name}: HTTP {response.status_code}'))
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'✗ {url_name}: Error - {str(e)}'))
                formatting_tests.append({
                    'template': url_name,
                    'url': url,
                    'status': 'ERROR',
                    'has_commas': False,
                    'has_large_numbers': False,
                    'success': False,
                    'error': str(e)
                })
        
        # Summary
        self.stdout.write('\n' + '='*60)
        self.stdout.write('FORMATTING TEST SUMMARY')
        self.stdout.write('='*60)
        
        successful_tests = [t for t in formatting_tests if t.get('success')]
        failed_tests = [t for t in formatting_tests if not t.get('success')]
        
        self.stdout.write(f'Total templates tested: {len(formatting_tests)}')
        self.stdout.write(f'Successful: {len(successful_tests)}')
        self.stdout.write(f'Failed: {len(failed_tests)}')
        
        if successful_tests:
            self.stdout.write('\n✓ Templates with working comma formatting:')
            for test in successful_tests:
                self.stdout.write(f'  - {test["template"]}')
        
        if failed_tests:
            self.stdout.write('\n✗ Templates that may need attention:')
            for test in failed_tests:
                status = test.get('status', 'Unknown')
                error = test.get('error', '')
                self.stdout.write(f'  - {test["template"]} (Status: {status})')
                if error:
                    self.stdout.write(f'    Error: {error}')
        
        # Clean up
        quotation.delete()
        self.stdout.write('\n✓ Test quotation cleaned up')
        
        self.stdout.write('\nComma formatting test completed!')
        
        if len(successful_tests) == len(formatting_tests):
            self.stdout.write(self.style.SUCCESS('\n🎉 All templates have proper comma formatting!'))
        else:
            self.stdout.write(self.style.WARNING(f'\n⚠ {len(failed_tests)} template(s) may need comma formatting fixes.'))
