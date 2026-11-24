# Remove expense_management app permissions from the database after app removal.
# This cleans auth_permission, django_content_type, and auth_group_permissions
# so role forms and permission checks no longer reference the removed app.

from django.db import migrations


def remove_expense_management_permissions(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')

    # Delete all permissions for expense_management app
    ct_ids = ContentType.objects.filter(app_label='expense_management').values_list('pk', flat=True)
    perm_ids = list(Permission.objects.filter(content_type_id__in=ct_ids).values_list('pk', flat=True))

    # Remove these permissions from all groups first (auth_group_permissions)
    for group in Group.objects.all():
        group.permissions.remove(*perm_ids)

    # Then delete permissions and content types
    Permission.objects.filter(content_type_id__in=ct_ids).delete()
    ContentType.objects.filter(app_label='expense_management').delete()


def noop_reverse(apps, schema_editor):
    # Cannot recreate permissions for a removed app; no-op.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_accountgroup_full_company_visibility'),
    ]

    operations = [
        migrations.RunPython(remove_expense_management_permissions, noop_reverse),
    ]
