import logging
from datetime import date

from django.db import transaction
from django.db.models import Min, Max, Count, F, ExpressionWrapper, DurationField
from django.utils import timezone

from .models import AttendanceLog, DailyAttendance, Employee

logger = logging.getLogger("smart_attendance.sync")


def _local_date(dt) -> date:
    if not dt:
        return timezone.localdate()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    return timezone.localdate(dt)


@transaction.atomic
def update_daily_attendance_for_employee(employee: Employee, target_date: date):
    """
    Convert raw attendance logs into a DailyAttendance record for a given date.
    """
    logs = AttendanceLog.objects.filter(
        employee=employee,
        punch_time__date=target_date,
    ).order_by("punch_time")

    punch_count = logs.count()
    if punch_count == 0:
        DailyAttendance.objects.update_or_create(
            employee=employee,
            date=target_date,
            defaults={
                "first_check_in": None,
                "last_check_out": None,
                "total_hours": None,
                "punch_count": 0,
                "status": DailyAttendance.STATUS_ABSENT,
            },
        )
        return

    first_check_in = logs.first().punch_time
    last_check_out = logs.last().punch_time
    total_hours = last_check_out - first_check_in

    status = DailyAttendance.STATUS_PRESENT
    # Simple late rule: after 9:15 local time
    local_first = timezone.localtime(first_check_in)
    if local_first.hour > 9 or (local_first.hour == 9 and local_first.minute > 15):
        status = DailyAttendance.STATUS_LATE

    DailyAttendance.objects.update_or_create(
        employee=employee,
        date=target_date,
        defaults={
            "first_check_in": first_check_in,
            "last_check_out": last_check_out,
            "total_hours": total_hours,
            "punch_count": punch_count,
            "status": status,
        },
    )

    logger.info(
        "Updated DailyAttendance employee_id=%s date=%s punches=%s status=%s",
        employee.id,
        target_date,
        punch_count,
        status,
    )

    # Keep daily analytics in sync for real-time analytics page
    try:
        from .analytics_engine import update_analytics_for_employee
        update_analytics_for_employee(employee, target_date, "daily")
    except Exception:
        pass


def recompute_daily_attendance_for_range(employee: Employee, start_date: date, end_date: date):
    """
    Rebuild DailyAttendance in bulk for a date range.
    """
    current = start_date
    while current <= end_date:
        update_daily_attendance_for_employee(employee, current)
        current += timezone.timedelta(days=1)

