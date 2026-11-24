"""
Versioned Sync API: /api/v1/
Offline-first bulk create/update and changes endpoints per model.
"""
from django.urls import path, include

app_name = 'sync_api'

urlpatterns = [
    path('', include(('apps.sync_api.v1_urls', 'v1'))),
]
