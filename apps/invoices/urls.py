from django.urls import path
from . import views

app_name = 'invoices'

urlpatterns = [
    path('', views.invoice_list, name='list'),
    path('create/', views.invoice_create, name='create'),
    path('create/dynamic/', views.invoice_create, name='create_dynamic'),
    path('<int:pk>/', views.invoice_detail, name='detail'),
    path('<int:pk>/edit/', views.invoice_edit, name='edit'),
    path('<int:pk>/delete/', views.invoice_delete, name='delete'),
    path('<int:pk>/delete-ajax/', views.invoice_delete_ajax, name='delete_ajax'),
    path('<int:pk>/pdf/', views.invoice_pdf, name='pdf'),
    path('<int:pk>/print/', views.invoice_print, name='print'),
    path('<int:pk>/report/', views.invoice_product_report, name='product_report'),
    path('export/excel/', views.export_excel, name='export_excel'),
    path('export/pdf/', views.export_pdf, name='export_pdf'),
    
    # Invoice Template URLs
    path('templates/', views.template_list, name='template_list'),
    path('templates/create/', views.template_create, name='template_create'),
    path('templates/<int:pk>/', views.template_detail, name='template_detail'),
    path('templates/<int:pk>/edit/', views.template_edit, name='template_edit'),
    path('templates/<int:pk>/delete/', views.template_delete, name='template_delete'),
    path('templates/<int:pk>/duplicate/', views.template_duplicate, name='template_duplicate'),
    path('templates/<int:pk>/apply-to-all/', views.template_apply_to_all, name='template_apply_to_all'),
    
    # API endpoints
    path('api/templates/', views.api_templates, name='api_templates'),
    path('api/card-records/', views.invoice_card_records_api, name='api_card_records'),
    path('api/report/', views.invoice_report_api, name='api_report'),
    path('api/supply-ledger/', views.invoice_supply_ledger_api, name='api_supply_ledger'),
    path('export/report-pdf/', views.export_report_pdf, name='export_report_pdf'),
    path('<int:pk>/update-status/', views.invoice_update_status, name='update_status'),
    path('<int:pk>/toggle-payment/', views.invoice_toggle_payment, name='toggle_payment'),
]
