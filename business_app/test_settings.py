"""
Test settings: extends main settings but uses StaticFilesStorage to avoid
manifest lookup errors during tests (e.g. Missing staticfiles manifest entry).
"""
from .settings import *  # noqa: F401, F403

STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
