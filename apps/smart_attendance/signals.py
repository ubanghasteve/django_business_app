from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.ownership import get_account_for_user

from .models import Employee as AttendanceEmployee


try:
    from apps.hr_staff.models import Employee as HrEmployee
except Exception:  # pragma: no cover - optional dependency
    HrEmployee = None


if HrEmployee is not None:

    @receiver(post_save, sender=HrEmployee)
    def create_or_update_attendance_employee(sender, instance: "HrEmployee", created: bool, **kwargs):
        """
        Keep smart_attendance.Employee in sync with HR Employee records.
        """
        account = getattr(instance, "account", None) or get_account_for_user(
            getattr(instance, "linked_user", None)
        )
        if not account:
            return

        attendance_emp, _ = AttendanceEmployee.objects.get_or_create(
            hr_employee=instance,
            defaults={
                "tenant": account,
                "employee_id": instance.employee_id or str(instance.pk),
                "first_name": instance.first_name,
                "last_name": instance.last_name,
                "department": getattr(instance.department, "name", "") if getattr(instance, "department", None) else "",
                "position": instance.position or "",
                "email": instance.email or "",
                "phone": instance.phone or "",
                "biometric_uid": "",
                "profile_photo": instance.profile_photo if getattr(instance, "profile_photo", None) else None,
                "is_active": instance.status == "active",
            },
        )
        if not created:
            attendance_emp.first_name = instance.first_name
            attendance_emp.last_name = instance.last_name
            attendance_emp.department = getattr(instance.department, "name", "") if getattr(instance, "department", None) else ""
            attendance_emp.position = instance.position or ""
            attendance_emp.email = instance.email or ""
            attendance_emp.phone = instance.phone or ""
            attendance_emp.is_active = instance.status == "active"
            if getattr(instance, "profile_photo", None):
                attendance_emp.profile_photo = instance.profile_photo
            attendance_emp.save()

