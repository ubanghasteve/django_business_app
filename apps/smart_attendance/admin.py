from django.contrib import admin

from .models import (
    Employee,
    BiometricDevice,
    Shift,
    DeviceStatus,
    BiometricUser,
    RawBiometricLog,
    AttendanceLog,
    DailyAttendance,
    AttendanceAnalytics,
    SyncQueue,
    CorruptedLog,
    DeviceSyncHistory,
)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "first_name", "last_name", "email", "phone", "biometric_uid", "department", "position", "is_active")
    list_filter = ("tenant", "department", "is_active")
    search_fields = ("employee_id", "first_name", "last_name", "email", "phone", "biometric_uid")


@admin.register(BiometricDevice)
class BiometricDeviceAdmin(admin.ModelAdmin):
    list_display = ("device_name", "device_serial", "device_ip", "device_port", "tenant", "status", "last_seen")
    list_filter = ("tenant", "status")
    search_fields = ("device_name", "device_serial", "device_ip", "location")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "start_time", "end_time", "grace_period")
    list_filter = ("tenant",)
    search_fields = ("name",)


@admin.register(DeviceStatus)
class DeviceStatusAdmin(admin.ModelAdmin):
    list_display = ("device", "cpu_usage", "memory_usage", "temperature", "network_status", "last_ping")


@admin.register(BiometricUser)
class BiometricUserAdmin(admin.ModelAdmin):
    list_display = ("employee", "device", "biometric_uid", "card_id", "created_at")
    list_filter = ("device",)
    search_fields = ("biometric_uid", "card_id", "employee__employee_id", "employee__first_name", "employee__last_name")


@admin.register(RawBiometricLog)
class RawBiometricLogAdmin(admin.ModelAdmin):
    list_display = ("device", "biometric_uid", "timestamp", "verify_mode", "punch_type", "queue_hash")
    list_filter = ("device", "verify_mode", "punch_type")
    search_fields = ("biometric_uid", "queue_hash")
    date_hierarchy = "timestamp"


@admin.register(AttendanceLog)
class AttendanceLogAdmin(admin.ModelAdmin):
    list_display = ("employee", "device", "punch_time", "punch_type", "verify_mode")
    list_filter = ("device", "punch_type", "verify_mode")
    search_fields = ("employee__employee_id", "employee__first_name", "employee__last_name")
    date_hierarchy = "punch_time"


@admin.register(DailyAttendance)
class DailyAttendanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "first_check_in", "last_check_out", "total_hours", "punch_count", "status")
    list_filter = ("status", "date")
    search_fields = ("employee__employee_id", "employee__first_name", "employee__last_name")
    date_hierarchy = "date"


@admin.register(AttendanceAnalytics)
class AttendanceAnalyticsAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "period", "times_entered", "times_exited", "work_hours", "late_minutes", "overtime_minutes")
    list_filter = ("period", "date")
    search_fields = ("employee__employee_id", "employee__first_name", "employee__last_name")
    date_hierarchy = "date"


@admin.register(SyncQueue)
class SyncQueueAdmin(admin.ModelAdmin):
    list_display = ("id", "device", "status", "retry_count", "queue_hash", "created_at")
    list_filter = ("status", "device")
    search_fields = ("queue_hash",)
    date_hierarchy = "created_at"


@admin.register(CorruptedLog)
class CorruptedLogAdmin(admin.ModelAdmin):
    list_display = ("id", "device", "error_type", "repair_status", "repair_attempts", "created_at")
    list_filter = ("repair_status", "device")
    date_hierarchy = "created_at"


@admin.register(DeviceSyncHistory)
class DeviceSyncHistoryAdmin(admin.ModelAdmin):
    list_display = ("device", "last_sync_time", "logs_synced", "status")
    list_filter = ("status",)

