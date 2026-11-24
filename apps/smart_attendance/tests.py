from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.core.models import Account

from .attendance_processor import update_daily_attendance_for_employee
from .corrupted_log_repair import attempt_repair
from .duplicate_detector import is_duplicate_attendance
from .models import (
    AttendanceLog,
    BiometricDevice,
    CorruptedLog,
    Employee,
    RawBiometricLog,
)


class SmartAttendanceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="admin@example.com", password="pass")
        self.account = Account.objects.create(owner=self.user, name="Test Co")
        self.user.account = self.account
        self.user.account_id = self.account.id
        self.user.save()
        self.employee = Employee.objects.create(
            tenant=self.account,
            employee_id="E001",
            first_name="John",
            last_name="Doe",
        )
        self.device = BiometricDevice.objects.create(
            tenant=self.account,
            device_name="Test Device",
            device_serial="SERIAL1",
            device_ip="192.168.1.10",
            device_port=4370,
            device_model="X100",
            firmware_version="1.0",
            device_secret="secret",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_biometric_push_api_enqueues_queue_item(self):
        url = reverse("biometric_push_api")
        ts = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "device_serial": self.device.device_serial,
            "uid": self.employee.employee_id,
            "timestamp": ts,
            "verify_mode": "fingerprint",
            "punch_type": "checkin",
        }
        response = self.client.post(
            url,
            data=payload,
            format="json",
            HTTP_X_DEVICE_SECRET=self.device.device_secret,
        )
        self.assertEqual(response.status_code, 200)

    def test_duplicate_detection(self):
        ts = timezone.now()
        AttendanceLog.objects.create(
            employee=self.employee,
            device=self.device,
            punch_time=ts,
            punch_type="checkin",
            verify_mode="fingerprint",
        )
        self.assertTrue(
            is_duplicate_attendance(self.employee.id, self.device.id, ts),
        )

    def test_corrupted_log_repair(self):
        corrupted = CorruptedLog.objects.create(
            device=self.device,
            raw_payload={
                "uid": self.employee.employee_id,
                "punch_type": "checkin",
                "verify_mode": "fingerprint",
            },
            error_type="missing timestamp",
            repair_status=CorruptedLog.REPAIR_STATUS_PENDING,
        )
        success, raw_log = attempt_repair(corrupted)
        self.assertTrue(success)
        self.assertIsInstance(raw_log, RawBiometricLog)

    def test_attendance_processing_updates_daily(self):
        ts1 = timezone.now().replace(hour=8, minute=0, second=0, microsecond=0)
        ts2 = ts1 + timedelta(hours=9)
        AttendanceLog.objects.create(
            employee=self.employee,
            device=self.device,
            punch_time=ts1,
            punch_type="checkin",
            verify_mode="fingerprint",
        )
        AttendanceLog.objects.create(
            employee=self.employee,
            device=self.device,
            punch_time=ts2,
            punch_type="checkout",
            verify_mode="fingerprint",
        )
        update_daily_attendance_for_employee(self.employee, ts1.date())
        daily = self.employee.daily_attendance.get(date=ts1.date())
        self.assertEqual(daily.punch_count, 2)

    def test_attendance_live_api(self):
        url = reverse("attendance_live_api")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total_employees", data)

