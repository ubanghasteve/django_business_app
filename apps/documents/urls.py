# -*- coding: utf-8 -*-
from django.urls import path
from . import views

app_name = 'documents'

urlpatterns = [
    path('', views.document_list_view, name='list'),
    path('upload/', views.document_upload_view, name='upload'),
    path('<int:pk>/', views.document_detail_view, name='detail'),
    path('<int:pk>/preview/', views.document_preview_view, name='preview'),
    path('<int:pk>/download/', views.document_download_view, name='download'),
    path('<int:pk>/contents/', views.document_contents_view, name='contents'),
    path('<int:pk>/delete/', views.document_delete_view, name='delete'),
    path('<int:pk>/reprocess/', views.document_reprocess_view, name='reprocess'),
    path('<int:pk>/tables/update/', views.document_update_tables_view, name='update_tables'),
    path('<int:pk>/reprocess-from-tables/', views.document_reprocess_from_tables_view, name='reprocess_from_tables'),
    path('<int:pk>/tables/export-excel/', views.document_export_tables_excel_view, name='export_tables_excel'),
    path('<int:pk>/status/', views.ajax_document_processing_status, name='status'),
    path('<int:pk>/processing-status/', views.document_processing_status_page, name='processing_status_page'),
    path('<int:pk>/toggle-star/', views.document_toggle_star_view, name='toggle_star'),
    path('<int:pk>/toggle-archive/', views.document_toggle_archive_view, name='toggle_archive'),
    path('<int:pk>/file-data/', views.document_file_data_view, name='file_data'),
]
