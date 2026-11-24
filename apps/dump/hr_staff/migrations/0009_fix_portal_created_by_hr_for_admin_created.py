# Generated manually to fix employees created by company admin

from django.db import migrations


def set_portal_created_by_hr_false_for_admin_created(apps, schema_editor):
    """Set portal_created_by_hr=False for employees created by the account owner (company admin)."""
    Employee = apps.get_model("hr_staff", "Employee")
    Account = apps.get_model("core", "Account")
    # Employees where creator is the account owner should not be manageable by HR
    for emp in Employee.objects.filter(portal_created_by_hr=True).select_related("account", "created_by"):
        if emp.account_id and emp.created_by_id and getattr(emp.account, "owner_id", None) == emp.created_by_id:
            emp.portal_created_by_hr = False
            emp.save(update_fields=["portal_created_by_hr"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("hr_staff", "0008_add_portal_created_by_hr"),
        ("core", "0008_account_owner_set_null"),
    ]

    operations = [
        migrations.RunPython(set_portal_created_by_hr_false_for_admin_created, noop),
    ]
