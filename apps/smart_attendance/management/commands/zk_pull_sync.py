"""
ZKTeco pull sync – run in terminal for automatic device sync.

Connects to all registered ZKTeco devices, pulls attendance logs, enqueues
them, and processes the queue. Runs in a loop so everything stays in sync
without needing cron or Celery.

Usage:
    python manage.py zk_pull_sync
    python manage.py zk_pull_sync --interval 60
    python manage.py zk_pull_sync --once
"""
import logging
import time

from django.core.management.base import BaseCommand

from apps.smart_attendance.workers import process_pending_queue
from apps.smart_attendance.zk_pull_service import pull_from_all_zk_devices

logger = logging.getLogger("smart_attendance.sync")


class Command(BaseCommand):
    help = (
        "ZKTeco pull sync: connect to devices, pull attendance logs, process queue.\n"
        "Runs in a loop so everything stays in sync. Leave running in terminal.\n"
        "Requires: pip install pyzk"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=30,
            help="Seconds between each sync cycle (default: 30)",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run one sync cycle and exit (no loop)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Max queue items to process per cycle (default: 1000)",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        run_once = options["once"]
        batch_size = options["batch_size"]

        self.stdout.write(
            self.style.NOTICE(
                "ZKTeco pull sync started. Press Ctrl+C to stop.\n"
                f"Interval: {interval}s | Batch size: {batch_size}"
            )
        )

        cycle = 0
        try:
            while True:
                cycle += 1
                self.stdout.write(f"\n--- Cycle {cycle} ---")

                # 1. Pull from all ZKTeco devices
                try:
                    pulled = pull_from_all_zk_devices()
                    if pulled:
                        self.stdout.write(self.style.SUCCESS(f"  Pulled {pulled} log(s) from devices"))
                    else:
                        self.stdout.write("  No new logs from devices")
                except ImportError as e:
                    self.stderr.write(
                        self.style.ERROR(
                            f"  pyzk not installed. Run: pip install pyzk\n  {e}"
                        )
                    )
                    if run_once:
                        break
                    time.sleep(interval)
                    continue
                except Exception as exc:
                    logger.exception("Error during ZKTeco pull")
                    self.stderr.write(self.style.ERROR(f"  Pull error: {exc}"))

                # 2. Process pending queue (same as cron)
                try:
                    process_pending_queue(batch_size=batch_size)
                    self.stdout.write("  Queue processed")
                except Exception as exc:
                    logger.exception("Error processing queue")
                    self.stderr.write(self.style.ERROR(f"  Queue error: {exc}"))

                if run_once:
                    self.stdout.write(self.style.SUCCESS("\nSingle run completed."))
                    break

                self.stdout.write(f"  Next sync in {interval}s...")
                time.sleep(interval)

        except KeyboardInterrupt:
            self.stdout.write(self.style.NOTICE("\nStopped by user."))
