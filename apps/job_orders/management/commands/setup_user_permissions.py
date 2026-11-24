from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from apps.accounts.models import User
from apps.job_orders.models import Product


class Command(BaseCommand):
    help = 'Set up basic permissions for all users to access job orders'

    def handle(self, *args, **options):
        # Create a basic user group if it doesn't exist
        user_group, created = Group.objects.get_or_create(name='Basic Users')
        
        if created:
            self.stdout.write(
                self.style.SUCCESS('Created "Basic Users" group')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS('"Basic Users" group already exists')
            )
        
        # Get all job order permissions
        content_type = ContentType.objects.get_for_model(Product)
        permissions = Permission.objects.filter(content_type=content_type)
        
        # Add all permissions to the Basic Users group
        for permission in permissions:
            user_group.permissions.add(permission)
        
        self.stdout.write(
            self.style.SUCCESS(f'Added {permissions.count()} permissions to Basic Users group')
        )
        
        # Add all existing users to the Basic Users group
        users = User.objects.filter(is_active=True)
        for user in users:
            user.groups.add(user_group)
        
        self.stdout.write(
            self.style.SUCCESS(f'Added {users.count()} users to Basic Users group')
        )
        
        self.stdout.write(
            self.style.SUCCESS('Successfully set up user permissions!')
        )
