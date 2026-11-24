"""
Smart Payroll API URLs
==================
API endpoints for the payroll records app.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    PayrollRecordViewSet,
    PayrollCategoryViewSet,
    PayrollTemplateViewSet,
    PayrollEntryViewSet,
    ExtractedPayrollDataViewSet,
    api_record_list,
    api_record_detail,
    api_record_upload,
    api_record_delete,
    api_record_download,
    api_record_stats,
    api_dashboard_stats,
    api_bulk_action,
    api_search,
    api_share_create,
    api_share_revoke,
    api_access_logs,
    api_notifications,
    api_mark_notification_read,
    api_record_file_data,
)

router = DefaultRouter()
router.register(r'records', PayrollRecordViewSet, basename='payroll-record')
router.register(r'categories', PayrollCategoryViewSet, basename='payroll-category')
router.register(r'templates', PayrollTemplateViewSet, basename='payroll-template')
router.register(r'entries', PayrollEntryViewSet, basename='payroll-entry')
router.register(r'extracted', ExtractedPayrollDataViewSet, basename='extracted-data')

urlpatterns = [
    path('', include(router.urls)),
    
    path('records/list/', api_record_list, name='api_record_list'),
    path('records/search/', api_search, name='api_search'),
    path('records/upload/', api_record_upload, name='api_upload'),
    path('records/delete/', api_record_delete, name='api_delete'),
    path('records/download/<int:record_id>/', api_record_download, name='api_download'),
    path('records/<int:record_id>/file/', api_record_file_data, name='api_record_file_data'),
    path('records/stats/', api_record_stats, name='api_stats'),
    path('dashboard/stats/', api_dashboard_stats, name='api_dashboard_stats'),
    path('records/bulk-action/', api_bulk_action, name='api_bulk_action'),
    
    path('shares/create/', api_share_create, name='api_share_create'),
    path('shares/<int:share_id>/revoke/', api_share_revoke, name='api_share_revoke'),
    
    path('access-logs/', api_access_logs, name='api_access_logs'),
    
    path('notifications/', api_notifications, name='api_notifications'),
    path('notifications/<int:notification_id>/read/', api_mark_notification_read, name='api_mark_notification_read'),
]
