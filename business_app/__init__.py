"""
Project package for business_app.

On shared hosting (cPanel) we avoid importing Celery at import time so that
management commands and WSGI/ASGI startup do not require the Celery library
or a running worker. The Celery app is still available in environments where
Celery is installed, but its absence will not break Django startup.
"""

try:
    from .celery import app as celery_app  # type: ignore
except Exception:
    celery_app = None  # Celery is optional in some deployments

__all__ = ("celery_app",)

