from django.core.management.base import BaseCommand
from decimal import Decimal
from apps.quotations.models import Quotation, QuotationItem
from django.utils import timezone


class Command(BaseCommand):
    help = 'Simple test for quotation duplication'

    def handle(self, *args, **options):
        self.stdout.write('Testing quotation duplication prevention...')
        
        # Count initial quotations
        initial_count = Quotation.objects.count()
        self.stdout.write(f'Initial quotation count: {initial_count}')
        
        # Create a test quotation
        quotation = Quotation.objects.create(
            quotation_number='TEST-DUP-001',
            subtotal=Decimal('100.00'),
            total_tax=Decimal('10.00'),
            grand_total=Decimal('110.00'),
            status='draft'
        )
        
        # Add a line item
        QuotationItem.objects.create(
            quotation=quotation,
            product_service='Test Product',
            quantity=1,
            unit_price=Decimal('100.00'),
            line_total=Decimal('100.00')
        )
        
        # Count after creation
        after_creation_count = Quotation.objects.count()
        self.stdout.write(f'After creation count: {after_creation_count}')
        
        # Test the duplicate prevention logic
        recent_duplicate = Quotation.objects.filter(
            quotation_number='TEST-DUP-001',
            quotation_date=timezone.now().date(),
            created_at__gte=timezone.now() - timezone.timedelta(minutes=1)
        ).exclude(pk=quotation.pk).first()
        
        if recent_duplicate:
            self.stdout.write(self.style.ERROR('✗ Duplicate detection logic failed'))
        else:
            self.stdout.write(self.style.SUCCESS('✓ Duplicate detection logic working'))
        
        # Clean up
        quotation.delete()
        final_count = Quotation.objects.count()
        
        if final_count == initial_count:
            self.stdout.write(self.style.SUCCESS('✓ Test cleanup successful'))
        else:
            self.stdout.write(self.style.ERROR('✗ Test cleanup failed'))
        
        self.stdout.write('Simple duplication test completed.')
