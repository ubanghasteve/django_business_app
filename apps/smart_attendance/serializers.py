from rest_framework import serializers

from .models import (
    Employee,
    BiometricDevice,
    AttendanceLog,
    DailyAttendance,
    SyncQueue,
)


class BiometricPushSerializer(serializers.Serializer):
    """
    Accepts ZKTeco-compatible push payload.
    uid/biometric_uid/user_id: at least one required (ZKTeco devices may use different field names).
    timestamp: flexible formats (ISO, %Y-%m-%d %H:%M:%S).
    """
    device_serial = serializers.CharField(max_length=128)
    uid = serializers.CharField(max_length=64, required=False, allow_blank=True)
    biometric_uid = serializers.CharField(max_length=64, required=False, allow_blank=True)
    user_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    timestamp = serializers.DateTimeField()
    verify_mode = serializers.CharField(max_length=64, required=False, default="")
    punch_type = serializers.CharField(max_length=64, required=False, default="")

    def validate(self, attrs):
        uid = attrs.get("uid") or attrs.get("biometric_uid") or attrs.get("user_id")
        if not uid or not str(uid).strip():
            raise serializers.ValidationError(
                "At least one of uid, biometric_uid, or user_id is required."
            )
        attrs["uid"] = str(uid).strip()
        return attrs


class BiometricLogItemSerializer(serializers.Serializer):
    """Single log item for batch push (same shape as BiometricPushSerializer minus device_serial)."""
    uid = serializers.CharField(max_length=64, required=False, allow_blank=True)
    biometric_uid = serializers.CharField(max_length=64, required=False, allow_blank=True)
    user_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    timestamp = serializers.DateTimeField()
    verify_mode = serializers.CharField(max_length=64, required=False, default="")
    punch_type = serializers.CharField(max_length=64, required=False, default="")

    def validate(self, attrs):
        uid = attrs.get("uid") or attrs.get("biometric_uid") or attrs.get("user_id")
        if not uid or not str(uid).strip():
            raise serializers.ValidationError(
                "At least one of uid, biometric_uid, or user_id is required."
            )
        attrs["uid"] = str(uid).strip()
        return attrs


class BiometricBatchPushSerializer(serializers.Serializer):
    """Batch push payload: device_serial + array of logs."""
    device_serial = serializers.CharField(max_length=128)
    logs = serializers.ListField(
        child=BiometricLogItemSerializer(),
        allow_empty=False,
        max_length=10000,
    )


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_id",
            "first_name",
            "last_name",
            "department",
            "position",
            "email",
            "phone",
            "biometric_uid",
            "is_active",
        ]


class BiometricDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = BiometricDevice
        fields = [
            "id",
            "device_name",
            "device_serial",
            "device_ip",
            "device_port",
            "device_model",
            "firmware_version",
            "location",
            "last_seen",
            "status",
        ]


class AttendanceLogSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    device = BiometricDeviceSerializer(read_only=True)

    class Meta:
        model = AttendanceLog
        fields = [
            "id",
            "employee",
            "device",
            "punch_time",
            "punch_type",
            "verify_mode",
            "work_code",
            "is_duplicate",
            "created_at",
        ]


class DailyAttendanceSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)

    class Meta:
        model = DailyAttendance
        fields = [
            "id",
            "employee",
            "date",
            "first_check_in",
            "last_check_out",
            "total_hours",
            "punch_count",
            "status",
        ]


class SyncQueueSerializer(serializers.ModelSerializer):
    device = BiometricDeviceSerializer(read_only=True)

    class Meta:
        model = SyncQueue
        fields = [
            "id",
            "device",
            "payload",
            "status",
            "retry_count",
            "queue_hash",
            "created_at",
        ]

