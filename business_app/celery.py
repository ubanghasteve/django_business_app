import os

from celery import Celery

# Set default Django settings module for 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "business_app.settings")

app = Celery("business_app")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self):
    from logging import getLogger

    logger = getLogger("smart_attendance")
    logger.info(f"Debug task executed: {self.request!r}")

