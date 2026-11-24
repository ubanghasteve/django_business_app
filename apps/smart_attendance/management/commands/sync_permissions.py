from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType


class Command(BaseCommand):
    help = "Sync smart_attendance permissions"

    def handle(self, *args, **options):
        from apps.smart_attendance.models import AttendanceLog, Employee, BiometricDevice
        
        content_types = {
            "attendancelog": ContentType.objects.get_for_model(AttendanceLog),
            "employee": ContentType.objects.get_for_model(Employee),
            "biometricdevice": ContentType.objects.get_for_model(BiometricDevice),
        }
        
        perms_to_create = [
            # Attendance Log
            ("view_attendancelog", "Can view attendance log", content_types["attendancelog"]),
            ("add_attendancelog", "Can add attendance log", content_types["attendancelog"]),
            ("change_attendancelog", "Can change attendance log", content_types["attendancelog"]),
            ("delete_attendancelog", "Can delete attendance log", content_types["attendancelog"]),
            # Employee
            ("view_employee", "Can view attendance employee", content_types["employee"]),
            ("add_employee", "Can add attendance employee", content_types["employee"]),
            ("change_employee", "Can change attendance employee", content_types["employee"]),
            ("delete_employee", "Can delete attendance employee", content_types["employee"]),
            # Biometric Device
            ("view_biometricdevice", "Can view biometric device", content_types["biometricdevice"]),
            ("add_biometricdevice", "Can add biometric device", content_types["biometricdevice"]),
            ("change_biometricdevice", "Can change biometric device", content_types["biometricdevice"]),
            ("delete_biometricdevice", "Can delete biometric device", content_types["biometricdevice"]),
        ]
        
        for codename, name, content_type in perms_to_create:
            perm, created = Permission.objects.get_or_create(
                codename=codename,
                content_type=content_type,
                defaults={"name": name}
            )
            if created:
                self.stdout.write(f"Created: {codename}")
            else:
                self.stdout.write(f"Exists: {codename}")
        
        self.stdout.write(self.style.SUCCESS("Smart attendance permissions synced successfully!"))
