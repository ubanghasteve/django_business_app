# Generated manually for permission hardening (Job Order Template / Layouts)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("job_orders", "0003_add_print_download_permissions"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="product",
            options={
                "ordering": ["-date_created"],
                "permissions": [
                    ("can_approve_jobs", "Can approve job orders"),
                    ("can_view_all_jobs", "Can view all job orders"),
                    ("can_export_jobs", "Can export job orders"),
                    ("can_manage_production", "Can manage production status"),
                    ("view_dashboard", "Can view dashboard"),
                    ("manage_leave", "Can manage leave requests"),
                    ("can_export_products", "Can export products"),
                    ("can_export_leaves", "Can export leaves"),
                    ("print_product", "Can print job order"),
                    ("download_product", "Can download or export job order"),
                    ("view_jobordertemplate", "Can view Job Order Template"),
                ],
            },
        ),
    ]
