# -*- coding: utf-8 -*-
"""
Recompute balance_quantity and stock_status for all Inventory records in chronological order.
Run this once after fixing _get_previous_balance_quantity() so existing data matches
Rem. qqt, Low stock threshold, and Stock status.
"""
from django.core.management.base import BaseCommand
from apps.inventory.models import Inventory


class Command(BaseCommand):
    help = (
        'Recompute balance_quantity and stock_status for all Inventory records '
        'in (created_at, pk) order per company so Stock Status stays in sync with '
        'Rem. qqt and Low stock threshold.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--company',
            type=int,
            default=None,
            help='Recompute only for this company ID (optional).',
        )

    def handle(self, *args, **options):
        company_id = options.get('company')
        qs = Inventory.objects.all().order_by('company_id', 'created_at', 'pk')
        if company_id is not None:
            qs = qs.filter(company_id=company_id)
        company_ids = qs.values_list('company_id', flat=True).distinct()
        updated = 0
        for cid in company_ids:
            if cid is None:
                continue
            for obj in Inventory.objects.filter(company_id=cid).order_by('created_at', 'pk'):
                obj.save()
                updated += 1
        self.stdout.write(self.style.SUCCESS(f'Recomputed balances and stock status for {updated} record(s).'))
