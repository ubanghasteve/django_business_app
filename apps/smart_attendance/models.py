from django.conf import settings
from django.db import models


class Employee(models.Model):
    """
    Biometric/attendance employee profile (tenant scoped).

    Optionally links to HR Employee to avoid duplication at the business level.
    """

    tenant = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="attendance_employees",
    )
    hr_employee = models.OneToOneField(
        "hr_staff.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_profile",
    )
    employee_id = models.CharField(max_length=64, db_index=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    department = models.CharField(max_length=150, blank=True, default="")
    position = models.CharField(max_length=150, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=64, blank=True, default="")
    biometric_uid = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Primary UID used by biometric devices.",
    )
    profile_photo = models.ImageField(
        upload_to="attendance/employees/%Y/%m/",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "employee_id"]),
            models.Index(fields=["tenant", "biometric_uid"]),
        ]
        unique_together = (("tenant", "employee_id"),)
        ordering = ["last_name", "first_name"]
        permissions = [
            ("view_attendance_dashboard", "View attendance dashboard"),
            ("export_attendance", "Export attendance and analytics"),
            ("view_own_attendance", "View own attendance only"),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.first_name} {self.last_name}".strip() or self.employee_id


class BiometricDevice(models.Model):
    """
    Physical biometric terminal.
    """

    STATUS_ONLINE = "online"
    STATUS_OFFLINE = "offline"
    STATUS_UNKNOWN = "unknown"
    STATUS_CHOICES = [
        (STATUS_ONLINE, "Online"),
        (STATUS_OFFLINE, "Offline"),
        (STATUS_UNKNOWN, "Unknown"),
    ]

    tenant = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="biometric_devices",
    )
    device_name = models.CharField(max_length=255)
    device_serial = models.CharField(max_length=128, unique=True)
    device_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Required for pull sync. Use 0.0.0.0 for push-only devices.",
    )
    device_port = models.PositiveIntegerField(default=4370)
    device_model = models.CharField(max_length=255, blank=True, default="")
    firmware_version = models.CharField(max_length=255, blank=True, default="")
    device_secret = models.CharField(
        max_length=255,
        help_text="Shared secret/token for device push authentication.",
    )
    location = models.CharField(max_length=255, blank=True, default="")
    last_seen = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_UNKNOWN,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["device_name"]
        indexes = [
            models.Index(fields=["tenant", "device_serial"]),
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.device_name} ({self.device_serial})"


class Shift(models.Model):
    """
    Work shift definition (tenant scoped).
    """
    tenant = models.ForeignKey(
        "core.Account",
        on_delete=models.CASCADE,
        related_name="attendance_shifts",
    )
    name = models.CharField(max_length=128)
    start_time = models.TimeField()
    end_time = models.TimeField()
    grace_period = models.PositiveIntegerField(
        default=0,
        help_text="Minutes of grace for late arrival.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["tenant"])]

    def __str__(self) -> str:
        return self.name


class DeviceStatus(models.Model):
    """
    Periodic health snapshot for a device.
    """

    device = models.OneToOneField(
        BiometricDevice,
        on_delete=models.CASCADE,
        related_name="status_info",
    )
    cpu_usage = models.FloatField(null=True, blank=True)
    memory_usage = models.FloatField(null=True, blank=True)
    temperature = models.FloatField(null=True, blank=True)
    network_status = models.CharField(max_length=64, blank=True, default="")
    last_ping = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"Status for {self.device}"


class BiometricUser(models.Model):
    """
    Enrollment of an employee on a specific biometric device.
    """

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="biometric_users",
    )
    device = models.ForeignKey(
        BiometricDevice,
        on_delete=models.CASCADE,
        related_name="biometric_users",
    )
    biometric_uid = models.CharField(max_length=64, db_index=True)
    fingerprint_template = models.BinaryField(null=True, blank=True)
    face_template = models.BinaryField(null=True, blank=True)
    card_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (("device", "biometric_uid"),)
        indexes = [
            models.Index(fields=["device", "biometric_uid"]),
            models.Index(fields=["employee", "device"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.employee} @ {self.device}"


class RawBiometricLog(models.Model):
    """
    Ingested raw log from a device before attendance processing.
    """

    device = models.ForeignKey(
        BiometricDevice,
        on_delete=models.CASCADE,
        related_name="raw_logs",
    )
    biometric_uid = models.CharField(max_length=64, db_index=True)
    timestamp = models.DateTimeField()
    verify_mode = models.CharField(max_length=64, blank=True, default="")
    punch_type = models.CharField(max_length=64, blank=True, default="")
    raw_payload = models.JSONField()
    queue_hash = models.CharField(
        max_length=128,
        db_index=True,
        help_text="SHA256 hash of (employee + timestamp + device) used for duplicate detection.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["device", "timestamp"]),
            models.Index(fields=["queue_hash"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"RawLog {self.device} {self.timestamp}"


class AttendanceLog(models.Model):
    """
    Normalized attendance event, mapped to an employee and device.
    """

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_logs",
    )
    device = models.ForeignKey(
        BiometricDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_logs",
    )
    punch_time = models.DateTimeField(db_index=True)
    punch_type = models.CharField(max_length=64, blank=True, default="")
    verify_mode = models.CharField(max_length=64, blank=True, default="")
    work_code = models.CharField(max_length=64, blank=True, default="")
    is_duplicate = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["employee", "punch_time"]),
            models.Index(fields=["punch_time"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.employee} {self.punch_time} ({self.punch_type})"


class DailyAttendance(models.Model):
    """
    Aggregated per-day attendance per employee.
    """

    STATUS_PRESENT = "present"
    STATUS_ABSENT = "absent"
    STATUS_LATE = "late"
    STATUS_HALF_DAY = "half_day"

    STATUS_CHOICES = [
        (STATUS_PRESENT, "Present"),
        (STATUS_ABSENT, "Absent"),
        (STATUS_LATE, "Late"),
        (STATUS_HALF_DAY, "Half Day"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="daily_attendance",
    )
    date = models.DateField()
    first_check_in = models.DateTimeField(null=True, blank=True)
    last_check_out = models.DateTimeField(null=True, blank=True)
    total_hours = models.DurationField(null=True, blank=True)
    punch_count = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_ABSENT,
    )

    class Meta:
        unique_together = (("employee", "date"),)
        indexes = [
            models.Index(fields=["employee", "date"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.employee} - {self.date}"


class AttendanceAnalytics(models.Model):
    """
    Precomputed analytics metrics for attendance.
    """

    PERIOD_DAILY = "daily"
    PERIOD_WEEKLY = "weekly"
    PERIOD_MONTHLY = "monthly"
    PERIOD_QUARTERLY = "quarterly"
    PERIOD_YEARLY = "yearly"

    PERIOD_CHOICES = [
        (PERIOD_DAILY, "Daily"),
        (PERIOD_WEEKLY, "Weekly"),
        (PERIOD_MONTHLY, "Monthly"),
        (PERIOD_QUARTERLY, "Quarterly"),
        (PERIOD_YEARLY, "Yearly"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_analytics",
    )
    date = models.DateField(
        help_text="Anchor date for the period (start of day/week/month/etc.).",
    )
    period = models.CharField(
        max_length=16,
        choices=PERIOD_CHOICES,
        default=PERIOD_DAILY,
    )
    times_entered = models.PositiveIntegerField(default=0)
    times_exited = models.PositiveIntegerField(default=0)
    work_hours = models.DurationField(null=True, blank=True)
    late_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = (("employee", "date", "period"),)
        indexes = [
            models.Index(fields=["employee", "date", "period"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.employee} {self.period} {self.date}"


class SyncQueue(models.Model):
    """
    Queue of raw biometric payloads for async processing.
    """

    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    device = models.ForeignKey(
        BiometricDevice,
        on_delete=models.CASCADE,
        related_name="sync_queue_items",
    )
    payload = models.JSONField()
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
    )
    retry_count = models.PositiveIntegerField(default=0)
    queue_hash = models.CharField(
        max_length=128,
        db_index=True,
        help_text="Hash used for duplicate detection at queue level.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=128, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["queue_hash"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"QueueItem {self.id} {self.status}"


class CorruptedLog(models.Model):
    """
    Stores payloads that could not be parsed; used by repair engine.
    """

    REPAIR_STATUS_PENDING = "pending"
    REPAIR_STATUS_REPAIRED = "repaired"
    REPAIR_STATUS_UNRECOVERABLE = "unrecoverable"
    REPAIR_STATUS_CHOICES = [
        (REPAIR_STATUS_PENDING, "Pending"),
        (REPAIR_STATUS_REPAIRED, "Repaired"),
        (REPAIR_STATUS_UNRECOVERABLE, "Unrecoverable"),
    ]

    device = models.ForeignKey(
        BiometricDevice,
        on_delete=models.CASCADE,
        related_name="corrupted_logs",
    )
    raw_payload = models.JSONField()
    error_type = models.CharField(max_length=255)
    repair_status = models.CharField(
        max_length=32,
        choices=REPAIR_STATUS_CHOICES,
        default=REPAIR_STATUS_PENDING,
    )
    repair_attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["device", "repair_status"]),
        ]

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"CorruptedLog {self.device} {self.error_type}"


class DeviceSyncHistory(models.Model):
    """
    Tracks the last successful sync point per device for offline recovery.
    """

    device = models.OneToOneField(
        BiometricDevice,
        on_delete=models.CASCADE,
        related_name="sync_history",
    )
    last_sync_time = models.DateTimeField(null=True, blank=True)
    logs_synced = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=64, blank=True, default="")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"SyncHistory {self.device}"

