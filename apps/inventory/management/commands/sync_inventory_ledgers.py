# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand

from apps.inventory.ledger_sync import sync_inventory_row
from apps.inventory.models import Inventory


class Command(BaseCommand):
    help = 'Repair and sync Quantity In / Out / Waste from receipt, issue, and waste logs.'

    def handle(self, *args, **options):
        qs = Inventory.objects.filter(is_deleted=False).order_by('pk')
        total = qs.count()
        self.stdout.write(f'Syncing {total} inventory row(s)...')
        for i, inv in enumerate(qs.iterator(), start=1):
            sync_inventory_row(inv.pk)
            if i % 50 == 0 or i == total:
                self.stdout.write(f'  {i}/{total}')
        self.stdout.write(self.style.SUCCESS('Done.'))
