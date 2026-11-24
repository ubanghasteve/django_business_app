from django.core.management.base import BaseCommand
from apps.quotations.models import Quotation, QuotationItem
from decimal import Decimal


class Command(BaseCommand):
    help = 'Fix existing quotations with incorrect totals due to percentage calculation issues'

    def handle(self, *args, **options):
        self.stdout.write('Starting quotation totals fix process...')
        
        # Get all quotations
        quotations = Quotation.objects.all()
        fixed_count = 0
        
        for quotation in quotations:
            self.stdout.write(f'Processing quotation {quotation.quotation_number}...')
            
            # Get line items
            items = quotation.items.all()
            
            if items.exists():
                # Calculate correct subtotal from line items
                correct_subtotal = sum(item.line_total for item in items)
                
                # Calculate correct grand total
                correct_grand_total = (
                    correct_subtotal +
                    quotation.total_tax +
                    quotation.shipping_fee +
                    quotation.other_charges -
                    quotation.total_discount
                )
                
                # Check if totals need fixing
                if (quotation.subtotal != correct_subtotal or 
                    quotation.grand_total != correct_grand_total):
                    
                    old_subtotal = quotation.subtotal
                    old_grand_total = quotation.grand_total
                    
                    # Update the quotation
                    quotation.subtotal = correct_subtotal
                    quotation.grand_total = correct_grand_total
                    quotation.save(update_fields=['subtotal', 'grand_total'])
                    
                    self.stdout.write(
                        f'  - Fixed totals: Subtotal {old_subtotal} -> {correct_subtotal}, '
                        f'Grand Total {old_grand_total} -> {correct_grand_total}'
                    )
                    fixed_count += 1
                else:
                    self.stdout.write(f'  - Totals are correct')
            else:
                self.stdout.write(f'  - No line items found')
        
        self.stdout.write(
            self.style.SUCCESS(f'Quotation totals fix process completed! Fixed {fixed_count} quotations.')
        )
