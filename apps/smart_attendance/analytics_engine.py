import logging
from datetime import date, timedelta

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .attendance_processor import _local_date
from .models import AttendanceAnalytics, DailyAttendance, Employee

logger = logging.getLogger("smart_attendance.sync")


def _period_bounds(anchor: date, period: str):
    if period == AttendanceAnalytics.PERIOD_DAILY:
        return anchor, anchor
    if period == AttendanceAnalytics.PERIOD_WEEKLY:
        start = anchor - timedelta(days=anchor.weekday())
        end = start + timedelta(days=6)
        return start, end
    if period == AttendanceAnalytics.PERIOD_MONTHLY:
        start = anchor.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
        return start, end
    if period == AttendanceAnalytics.PERIOD_QUARTERLY:
        q = (anchor.month - 1) // 3
        start_month = q * 3 + 1
        start = anchor.replace(month=start_month, day=1)
        end_month = start_month + 2
        if end_month >= 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = start.replace(month=end_month + 1, day=1) - timedelta(days=1)
        return start, end
    if period == AttendanceAnalytics.PERIOD_YEARLY:
        start = anchor.replace(month=1, day=1)
        end = anchor.replace(month=12, day=31)
        return start, end
    return anchor, anchor


@transaction.atomic
def update_analytics_for_employee(employee: Employee, anchor_date: date, period: str):
    """
    Compute analytics metrics for a given employee and period.
    """
    start, end = _period_bounds(anchor_date, period)

    days = DailyAttendance.objects.filter(
        employee=employee,
        date__gte=start,
        date__lte=end,
    )

    times_entered = days.exclude(first_check_in__isnull=True).count()
    times_exited = days.exclude(last_check_out__isnull=True).count()

    total_work_seconds = 0
    late_minutes = 0
    overtime_minutes = 0

    for d in days:
        if d.total_hours:
            total_work_seconds += int(d.total_hours.total_seconds())
        # Late: if status marked late, treat as 30 minutes for now (simplified)
        if d.status == DailyAttendance.STATUS_LATE:
            late_minutes += 30
        # Overtime: anything over 8 hours
        if d.total_hours and d.total_hours.total_seconds() > 8 * 3600:
            overtime_minutes += int(
                (d.total_hours.total_seconds() - 8 * 3600) / 60,
            )

    work_hours = timezone.timedelta(seconds=total_work_seconds) if total_work_seconds else None

    AttendanceAnalytics.objects.update_or_create(
        employee=employee,
        date=start,
        period=period,
        defaults={
            "times_entered": times_entered,
            "times_exited": times_exited,
            "work_hours": work_hours,
            "late_minutes": late_minutes,
            "overtime_minutes": overtime_minutes,
        },
    )

    logger.info(
        "Updated AttendanceAnalytics employee_id=%s period=%s start=%s end=%s",
        employee.id,
        period,
        start,
        end,
    )

