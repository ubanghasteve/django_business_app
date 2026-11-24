import logging

from django.core.management.base import BaseCommand

from apps.core.models import Account

from apps.smart_attendance.corrupted_log_repair import attempt_repair
from apps.smart_attendance.device_discovery import discover_devices_for_tenant
from apps.smart_attendance.models import CorruptedLog
from apps.smart_attendance.workers import process_pending_queue


logger = logging.getLogger("smart_attendance.sync")


class Command(BaseCommand):
    help = (
        "Run Smart Attendance background processing in a cron-friendly way.\n"
        "- Process pending SyncQueue items (biometric logs)\n"
        "- Optionally discover devices on 192.168.x.x\n"
        "- Optionally attempt repair of corrupted logs\n\n"
        "Intended for shared hosting / cPanel where Redis/Celery workers cannot run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Maximum number of queue items and corrupted logs to process per run.",
        )
        parser.add_argument(
            "--discover-devices",
            action="store_true",
            help="Also run device auto-discovery for all tenants in this run.",
        )
        parser.add_argument(
            "--repair-corrupted",
            action="store_true",
            help="Also attempt repair of pending corrupted logs in this run.",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        do_discover = options["discover_devices"]
        do_repair = options["repair_corrupted"]

        self.stdout.write(self.style.NOTICE("Starting smart_attendance_cron run"))

        # 1. Process pending biometric queue using the existing sync engine
        self.stdout.write(f"- Processing up to {batch_size} pending queue item(s)...")
        try:
            process_pending_queue(batch_size=batch_size)
        except Exception as exc:
            logger.exception("Error while processing pending queue items")
            self.stderr.write(self.style.ERROR(f"Error processing queue: {exc}"))

        # 2. Optional: run device discovery for all tenants
        if do_discover:
            self.stdout.write("- Running device discovery for all tenants...")
            for account in Account.objects.all():
                try:
                    discovered = discover_devices_for_tenant(account)
                    self.stdout.write(
                        f"  Tenant {account.id}: discovered/updated {discovered} device(s)"
                    )
                except Exception as exc:
                    logger.exception(
                        "Error during device discovery for tenant_id=%s", account.id
                    )
                    self.stderr.write(
                        self.style.ERROR(
                            f"Error discovering devices for tenant {account.id}: {exc}"
                        )
                    )

        # 3. Optional: attempt repair of corrupted logs
        if do_repair:
            self.stdout.write(
                f"- Attempting repair for up to {batch_size} corrupted log(s)..."
            )
            pending = (
                CorruptedLog.objects.filter(
                    repair_status=CorruptedLog.REPAIR_STATUS_PENDING
                )
                .order_by("created_at")[:batch_size]
            )
            for log in pending:
                try:
                    success, _ = attempt_repair(log)
                    status = "repaired" if success else "unrecoverable"
                    self.stdout.write(
                        f"  CorruptedLog {log.id}: {status} (device_id={log.device_id})"
                    )
                except Exception as exc:
                    logger.exception("Error attempting repair for CorruptedLog id=%s", log.id)
                    self.stderr.write(
                        self.style.ERROR(
                            f"Error repairing CorruptedLog {log.id}: {exc}"
                        )
                    )

        self.stdout.write(self.style.SUCCESS("smart_attendance_cron run completed."))

