"""
URL configuration for business_app project.
"""
from django.contrib import admin
from django.urls import path, include, re_path

from .views import permission_denied as permission_denied_403
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from django.views.static import serve as static_serve

from apps.smart_attendance import views as attendance_views

from .service_worker_views import service_worker, service_worker_offline

# PWA helpers (optional so a partial upload cannot take the whole site down)
try:
    from .service_worker_views import web_manifest, favicon_ico
except ImportError:  # pragma: no cover
    web_manifest = None
    favicon_ico = None

urlpatterns = [
    path('sw.js', service_worker),
    path('service-worker.js', service_worker_offline),
]
if web_manifest is not None:
    urlpatterns += [
        path('manifest.webmanifest', web_manifest, name='web_manifest'),
        path('manifest.json', web_manifest),
    ]
if favicon_ico is not None:
    urlpatterns += [
        path('favicon.ico', favicon_ico),
    ]
urlpatterns += [
    path('admin/', admin.site.urls),
    path('', RedirectView.as_view(url='/dashboard/landing/', permanent=False)),
    path('auth/', include(('apps.accounts.urls', 'accounts'), namespace='auth')),
    path('dashboard/', include('apps.core.urls')),
    path('api/invoices/', include('apps.invoices.api_urls')),
    path('api/requisitions/', include('apps.requisitions.api_urls')),
    path('api/staff-offences/', include('apps.staff_offences.api_urls')),
    path('api/core/', include('apps.core.api_urls')),
    path('api/receipts/', include('apps.receipts.api_urls')),
    path('api/waybills/', include('apps.waybills.api_urls')),
    path('api/job-orders/', include('apps.job_orders.api_urls')),
    path('quotations/', include(('apps.quotations.urls', 'quotations'), namespace='quotations')),
    # path('api/inventory/', include('apps.inventory.api_urls')),
    path('api/clients/', include('apps.clients.api_urls')),
    path('api/mailing/', include('apps.mailing.api_urls')),
    path('api/inventory/', include('apps.inventory.api_urls')),
    path('api/store/', include('apps.store.api_urls')),
    path('api/expense/', include('apps.expense.api_urls')),
    path('accounting/api/', include(('apps.accounting.api_urls', 'accounting_api'), namespace='accounting_api')),
    path('invoices/', include('apps.invoices.urls')),
    path('receipts/', include(('apps.receipts.urls', 'receipts'), namespace='receipts')),
    path('requisitions/', include('apps.requisitions.urls')),
    path('staff-offences/', include(('apps.staff_offences.urls', 'staff_offences'), namespace='staff_offences')),
    path('waybills/', include('apps.waybills.urls')),
    path('job-orders/', include(('apps.job_orders.urls', 'job_orders'), namespace='job_orders')),
    path('clients/', include(('apps.clients.urls', 'clients'), namespace='clients')),
    path('inventory/', include(('apps.inventory.urls', 'inventory'), namespace='inventory')),
    path('store/', include(('apps.store.urls', 'store'), namespace='store')),
    path('expense/', include(('apps.expense.urls', 'expense'), namespace='expense')),
    path('accounting/', include(('apps.accounting.urls', 'accounting'), namespace='accounting')),
    path('messaging/', include(('apps.messaging.urls', 'messaging'), namespace='messaging')),
    path('mailing/', include(('apps.mailing.urls', 'mailing'), namespace='mailing')),
    path('hr-staff/', include(('apps.hr_staff.urls', 'hr_staff'), namespace='hr_staff')),
    path('api/hr-staff/', include('apps.hr_staff.api_urls')),
    path('api/v1/', include('apps.sync_api.urls')),
    # AI Document Analyzer (Tax Analyzer)
    path('documents/', include(('apps.documents.urls', 'documents'), namespace='documents')),
    path('reports/', include(('apps.reports.urls', 'reports'), namespace='reports')),
    path('api/documents/', include('apps.documents.api_urls')),
    path('api/extraction/', include('apps.extraction.urls')),
    path('api/ai/', include('apps.ai_engine.urls')),
    path('api/finance/', include('apps.finance_engine.api_urls')),
    path('api/tax/', include('apps.tax_engine.urls')),
    path('api/reports/', include('apps.reports.api_urls')),
    path('payroll/', include(('apps.payroll.urls', 'smart_payroll'), namespace='smart_payroll')),
    path('api/payroll/', include('apps.payroll.api.urls')),
    path('notifications/', include(('apps.notifications.urls', 'notifications'), namespace='notifications')),
    # path('clients/', include('apps.clients.urls')),
    # Smart attendance web UI
    path('attendance/', include(('apps.smart_attendance.urls', 'smart_attendance'), namespace='smart_attendance')),
    # Smart attendance APIs
    path('api/biometric/push', attendance_views.biometric_push_api, name='biometric_push_api'),
    path('api/biometric/push/', attendance_views.biometric_push_api, name='biometric_push_api_trailing'),
    path('api/biometric/push/batch', attendance_views.biometric_push_batch_api, name='biometric_push_batch_api'),
    path('api/biometric/push/batch/', attendance_views.biometric_push_batch_api, name='biometric_push_batch_api_trailing'),
    path('api/devices', attendance_views.devices_api, name='devices_api'),
    path('api/devices/discover', attendance_views.devices_discover_api, name='devices_discover_api'),
    path('api/attendance/live', attendance_views.attendance_live_api, name='attendance_live_api'),
    path('api/attendance/realtime', attendance_views.attendance_realtime_api, name='attendance_realtime_api'),
    path('api/attendance/logs', attendance_views.attendance_logs_api, name='attendance_logs_api'),
    path('api/attendance/employee/<int:pk>', attendance_views.attendance_employee_api, name='attendance_employee_api'),
    path('api/attendance/device-status', attendance_views.attendance_device_status_api, name='attendance_device_status_api'),
    path('api/attendance/device-stats', attendance_views.attendance_device_stats_api, name='attendance_device_stats_api'),
    path('api/attendance/device/<int:device_id>/last-punch', attendance_views.attendance_device_last_punch_api, name='attendance_device_last_punch_api'),
    path('api/attendance/today', attendance_views.attendance_today_api, name='attendance_today_api'),
    path('api/attendance/report', attendance_views.attendance_report_api, name='attendance_report_api'),
    path('api/attendance/push-offline', attendance_views.attendance_offline_push_api, name='attendance_offline_push_api'),
    path('api/attendance/push-offline/', attendance_views.attendance_offline_push_api, name='attendance_offline_push_api_trailing'),
    path('api/payroll/offline-sync', lambda r: __import__('apps.payroll.views', fromlist=['payroll_offline_sync']).payroll_offline_sync(r), name='payroll_offline_sync'),
    path('api/payroll/offline-sync/', lambda r: __import__('apps.payroll.views', fromlist=['payroll_offline_sync']).payroll_offline_sync(r), name='payroll_offline_sync_trailing'),
    path('videocalls/', include(('apps.videocalls.urls', 'videocalls'), namespace='videocalls')),
]

# Serve media files (images, uploads)
if settings.DEBUG:
    # Use Django's helper in development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
else:
    # In production (DEBUG=False), explicitly serve media through Django
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', static_serve, {'document_root': settings.MEDIA_ROOT}),
    ]

# Serve static files in development (WhiteNoise handles this in production)
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Custom 403 handler for role-based activation message (owner vs team member)
handler403 = permission_denied_403
