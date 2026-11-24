# Add view_hr_dashboard and view_own_hr_dashboard for explicit HR app access (no Full Company Visibility).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hr_staff", "0006_add_employee_portal_linking"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="employee",
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("view_hr_dashboard", "View HR dashboard"),
                    ("view_own_hr_dashboard", "View own HR dashboard"),
                    ("create_employee_account", "Create employee portal account"),
                    ("reset_employee_password", "Reset employee password"),
                    ("view_employee_activity", "View employee activity"),
                ],
                "verbose_name": "Employee",
                "verbose_name_plural": "Employees",
            },
        ),
    ]
