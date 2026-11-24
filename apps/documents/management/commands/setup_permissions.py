from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from apps.documents.models import Document


class Command(BaseCommand):
    help = 'Ensure all document model permissions exist in the database'

    def handle(self, *args, **options):
        self.stdout.write('Setting up Document model permissions...')
        
        ct, created = ContentType.objects.get_or_create(
            app_label='documents',
            model='document'
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created ContentType: documents.document'))
        else:
            self.stdout.write(f'ContentType already exists: documents.document')
        
        # Get or create standard permissions
        standard_perms = [
            ('view_document', 'Can view document'),
            ('add_document', 'Can add document'),
            ('change_document', 'Can change document'),
            ('delete_document', 'Can delete document'),
        ]
        
        # Also add custom permissions from Meta
        custom_perms = [
            ('view_tax_report', 'Can view tax reports'),
        ]
        
        all_perms = standard_perms + custom_perms
        
        for codename, name in all_perms:
            perm, created = Permission.objects.get_or_create(
                codename=codename,
                content_type=ct,
                defaults={'name': name}
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Created permission: {codename}'))
            else:
                self.stdout.write(f'Permission already exists: {codename}')
        
        # Verify permissions exist
        perms = Permission.objects.filter(content_type=ct)
        self.stdout.write(f'\nTotal permissions for documents.document: {perms.count()}')
        for p in perms:
            self.stdout.write(f'  - {p.codename}')
        
        self.stdout.write(self.style.SUCCESS('\nDone!'))
