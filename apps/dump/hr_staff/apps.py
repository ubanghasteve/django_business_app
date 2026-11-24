# -*- coding: utf-8 -*-
from django.apps import AppConfig


class HrStaffConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.hr_staff'
    verbose_name = 'HR & Staff'

    def ready(self):
        from . import signals  # noqa: F401
