"""
Ensure all application permissions exist in the database.

This command creates any missing permissions that are defined in app models
but may not exist in the database (e.g., after adding new custom permissions).

Usage:
  python manage.py setup_all_permissions
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import transaction


class Command(BaseCommand):
    help = (
        "Ensure all application permissions exist in the database. "
        "Creates missing permissions for all apps including custom permissions "
        "defined in model Meta.permissions."
    )

    PERMISSIONS_TO_CREATE = {
        # invoices
        'invoices': [
            ('print_invoice', 'Can print invoice'),
            ('download_invoice', 'Can download or export invoice data'),
            ('can_approve_invoice', 'Can approve invoices'),
        ],
        # quotations
        'quotations': [
            ('print_quotation', 'Can print quotation'),
            ('download_quotation', 'Can download or export quotation data'),
            ('can_approve_quotation', 'Can approve quotations'),
        ],
        # receipts
        'receipts': [
            ('print_receipt', 'Can print receipt'),
            ('download_receipt', 'Can download or export receipt data'),
        ],
        # waybills
        'waybills': [
            ('print_waybill', 'Can print waybill'),
            ('download_waybill', 'Can download or export waybill data'),
            ('can_approve_waybill', 'Can approve waybills'),
        ],
        # requisitions
        'requisitions': [
            ('print_requisition', 'Can print requisition'),
            ('download_requisition', 'Can download or export requisition data'),
            ('can_approve_requisition', 'Can approve requisitions'),
        ],
        # inventory
        'inventory': [
            ('print_inventory', 'Can print inventory'),
            ('download_inventory', 'Can download or export inventory data'),
            ('can_approve_inventory', 'Can approve inventory records'),
        ],
        # expense
        'expense': [
            ('print_expense', 'Can print expense'),
            ('download_expense', 'Can download or export expense data'),
            ('can_approve_expense', 'Can approve expense records'),
        ],
        # clients
        'clients': [
            ('print_client', 'Can print client'),
            ('download_client', 'Can download or export client data'),
        ],
        # job_orders
        'job_orders': [
            ('print_product', 'Can print job order'),
            ('download_product', 'Can download or export job order'),
            ('can_approve_jobs', 'Can approve job orders'),
            ('can_view_all_jobs', 'Can view all job orders'),
            ('can_export_jobs', 'Can export job orders'),
            ('can_manage_production', 'Can manage production status'),
            ('view_dashboard', 'Can view dashboard'),
            ('manage_leave', 'Can manage leave requests'),
            ('can_export_products', 'Can export products'),
            ('can_export_leaves', 'Can export leaves'),
            ('view_jobordertemplate', 'Can view Job Order Template'),
        ],
        # hr_staff
        'hr_staff': [
            ('view_hr_dashboard', 'View HR dashboard'),
            ('view_own_hr_dashboard', 'View own HR dashboard'),
            ('create_employee_account', 'Create employee portal account'),
            ('reset_employee_password', 'Reset employee password'),
            ('view_employee_activity', 'View employee activity'),
        ],
        # smart_attendance
        'smart_attendance': [
            ('view_attendance_dashboard', 'View attendance dashboard'),
            ('export_attendance', 'Export attendance and analytics'),
            ('view_own_attendance', 'View own attendance only'),
        ],
        # documents
        'documents': [
            ('view_tax_report', 'Can view tax reports'),
            ('process_document', 'Can process documents'),
            ('view_documentprocessingstatus', 'Can view processing status'),
        ],
        # mailing
        'mailing': [
            ('use_bulk_mailing', 'Use bulk mailing'),
        ],
        # accounts
        'accounts': [
            ('view_activity_log', 'View activity log'),
        ],
    }

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without making changes.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        created_count = 0
        skipped_count = 0

        for app_label, permissions in self.PERMISSIONS_TO_CREATE.items():
            try:
                content_type, created = ContentType.objects.get_or_create(
                    app_label=app_label,
                    model=app_label,
                )
                if created:
                    self.stdout.write(f"  Created ContentType for '{app_label}'")
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"  Skipping {app_label}: {e}")
                )
                continue

            for codename, name in permissions:
                spec = f"{app_label}.{codename}"
                
                # Check if permission already exists
                if Permission.objects.filter(
                    content_type=content_type,
                    codename=codename,
                ).exists():
                    skipped_count += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(f"  [DRY RUN] Would create: {spec}")
                    )
                    continue

                # Create the permission
                with transaction.atomic():
                    Permission.objects.create(
                        content_type=content_type,
                        codename=codename,
                        name=name,
                    )
                    created_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"  Created: {spec}")
                    )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run complete. Would create {len(self.PERMISSIONS_TO_CREATE) * 3} permissions."
                )
            )
        else:
            total = created_count + skipped_count
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nDone. Created {created_count} new permissions. "
                    f"Skipped {skipped_count} existing permissions. Total checked: {total}."
                )
            )
