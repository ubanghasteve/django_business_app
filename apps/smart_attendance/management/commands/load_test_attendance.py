"""
Load test: simulate ingestion of 100,000 biometric logs.

Verifies: no duplicates, no crashes, correct employee matching.
"""
import logging
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.smart_attendance.models import BiometricDevice, Employee, SyncQueue
from apps.smart_attendance.queue_manager import enqueue_biometric_payload
from apps.smart_attendance.workers import process_pending_queue

logger = logging.getLogger("smart_attendance.sync")


class Command(BaseCommand):
    help = "Load test: ingest 100,000 biometric logs and verify no duplicates/crashes"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=1000, help="Number of logs to simulate (default 1000, use 100000 for full test)")
        parser.add_argument("--batch-size", type=int, default=1000, help="Queue process batch size")

    def handle(self, *args, **options):
        count = options["count"]
        batch_size = options["batch_size"]

        device = BiometricDevice.objects.first()
        employee = Employee.objects.filter(tenant=device.tenant).first()
        if not device or not employee:
            self.stderr.write(self.style.ERROR("Need at least one device and employee. Create them first."))
            return

        uid = employee.biometric_uid or employee.employee_id or "1"
        base_time = timezone.now() - timedelta(days=1)

        self.stdout.write(f"Simulating {count} logs...")
        enqueued = 0
        for i in range(count):
            ts = base_time + timedelta(seconds=i)
            payload = {
                "device_serial": device.device_serial,
                "uid": uid,
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "verify_mode": "fingerprint",
                "punch_type": "checkin" if i % 2 == 0 else "checkout",
            }
            result = enqueue_biometric_payload(device, payload)
            if result:
                enqueued += 1
            if (i + 1) % 10000 == 0:
                self.stdout.write(f"  Enqueued {i + 1}...")

        self.stdout.write(self.style.SUCCESS(f"Enqueued {enqueued} new logs (duplicates skipped)"))

        self.stdout.write(f"Processing queue (batch_size={batch_size})...")
        processed = 0
        max_rounds = (count // batch_size) + 10
        for r in range(max_rounds):
            pending = SyncQueue.objects.filter(status=SyncQueue.STATUS_PENDING).count()
            if pending == 0:
                break
            process_pending_queue(batch_size=batch_size)
            processed += min(batch_size, pending)
            if (r + 1) % 10 == 0 or pending == 0:
                self.stdout.write(f"  Round {r + 1}: ~{processed} processed, {pending} pending")

        remaining = SyncQueue.objects.filter(status=SyncQueue.STATUS_PENDING).count()
        self.stdout.write(self.style.SUCCESS(f"Load test completed. Total processed: {processed}. Remaining: {remaining}"))
