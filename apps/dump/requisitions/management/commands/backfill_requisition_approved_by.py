# -*- coding: utf-8 -*-
"""
Backfill approved_by for requisitions that were approved before the field existed.

Sets approved_by = created_by (and approved_at = updated_at) for requisitions
where status is 'approved' or 'completed' and approved_by is null.

Usage:
    python manage.py backfill_requisition_approved_by
    python manage.py backfill_requisition_approved_by --dry-run
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.requisitions.models import Requisition


class Command(BaseCommand):
    help = 'Set approved_by = created_by for already-approved requisitions that have no approver stored.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Only report what would be updated.')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        qs = Requisition.objects.filter(
            status__in=('approved', 'completed'),
            approved_by__isnull=True,
            created_by__isnull=False,
        )
        count = qs.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS('No requisitions need backfill.'))
            return
        if dry_run:
            self.stdout.write(self.style.WARNING(f'Would backfill approved_by for {count} requisition(s).'))
            return
        updated = 0
        for req in qs:
            req.approved_by = req.created_by
            req.approved_at = req.updated_at or timezone.now()
            req.save(update_fields=['approved_by', 'approved_at'])
            updated += 1
        self.stdout.write(self.style.SUCCESS(f'Backfilled approved_by for {updated} requisition(s).'))
