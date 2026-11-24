"""
Smart Payroll Records URLs
========================
URL configuration for the payroll records app.
"""

from django.urls import path
from . import views

app_name = 'payroll'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    
    path('records/', views.record_list, name='record_list'),
    path('records/upload/', views.record_upload, name='record_upload'),
    path('records/<int:record_id>/', views.record_detail, name='record_detail'),
    path('records/<int:record_id>/edit/', views.record_edit, name='record_edit'),
    path('records/<int:record_id>/delete/', views.record_delete, name='record_delete'),
    path('records/<int:record_id>/download/', views.record_download, name='record_download'),
    path('records/<int:record_id>/preview/', views.record_preview, name='record_preview'),
    path('records/<int:record_id>/toggle-star/', views.record_toggle_star, name='record_toggle_star'),
    path('records/<int:record_id>/toggle-archive/', views.record_toggle_archive, name='record_toggle_archive'),
    path('records/<int:record_id>/verify/', views.record_verify, name='record_verify'),
    path('records/<int:record_id>/approve/', views.record_approve, name='record_approve'),
    path('records/<int:record_id>/share/', views.record_share, name='record_share'),
    path('records/<int:record_id>/update-status/', views.record_update_status, name='record_update_status'),
    
    path('categories/', views.category_list, name='category_list'),
    path('categories/create/', views.category_create, name='category_create'),
    path('categories/<int:category_id>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:category_id>/delete/', views.category_delete, name='category_delete'),
    
    path('access-logs/', views.access_logs, name='access_logs'),
    path('analytics/', views.analytics, name='analytics'),
    
    path('templates/', views.template_list, name='template_list'),
    
    path('entries/', views.entry_list, name='entry_list'),
    path('entries/<int:entry_id>/', views.entry_detail, name='entry_detail'),
    
    path('share/<str:token>/', views.shared_record_access, name='shared_record_access'),
    path('share/<str:token>/download/', views.shared_record_download, name='shared_record_download'),
    
    path('api/upload/', views.api_upload, name='api_upload'),
    path('api/delete/', views.api_delete, name='api_delete'),
    path('api/bulk-action/', views.api_bulk_action, name='api_bulk_action'),
    path('api/stats/', views.api_stats, name='api_stats'),
    path('api/stream/', views.api_stream, name='api_stream'),
    path('records/<int:record_id>/file-data/', views.record_file_data, name='record_file_data'),
]
