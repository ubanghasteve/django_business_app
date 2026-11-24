# -*- coding: utf-8 -*-
from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.inventory_list, name='list'),
    path('list/print/', views.inventory_list_print, name='list_print'),
    path('list/pdf/', views.inventory_list_pdf, name='list_pdf'),
    path('dashboard/', views.inventory_dashboard, name='dashboard'),
    path('create/', views.inventory_create, name='create'),
    path('update/<int:pk>/', views.inventory_update, name='update'),
    path('delete/<int:pk>/', views.inventory_delete, name='delete'),
    path('detail/<int:pk>/', views.inventory_detail, name='detail'),
    # Waste Log URLs
    path('waste/', views.waste_list, name='waste_list'),
    path('waste/create/', views.waste_create, name='waste_create'),
    path('waste/delete/<int:pk>/', views.waste_delete, name='waste_delete'),
    path('api/waste-stats/', views.waste_stats_json, name='waste_stats_json'),
    # Product report URLs
    path('product/<int:pk>/report/', views.inventory_product_report, name='product_report'),
    path('product/report/<int:pk>/', views.inventory_product_report, name='product_report_alt'),
    path('product/<int:pk>/report/print/', views.inventory_product_report_print, name='product_report_print'),
    path('product/<int:pk>/report/pdf/', views.inventory_product_report_pdf, name='product_report_pdf'),
    path('print/<int:pk>/', views.inventory_print, name='print'),
    path('pdf/<int:pk>/', views.inventory_pdf, name='pdf'),
    path('ajax/update-field/', views.ajax_update_field, name='ajax_update_field'),
    path('ajax/status-update/', views.ajax_status_update, name='ajax_status_update'),
    path('ajax/create/', views.ajax_create, name='ajax_create'),
    path('ajax/issue/create/', views.ajax_issue_create, name='ajax_issue_create'),
    path('ajax/issue/update/<int:pk>/', views.ajax_issue_update, name='ajax_issue_update'),
    path('ajax/issue/list/', views.ajax_issue_list, name='ajax_issue_list'),
    path('ajax/issue/delete/<int:pk>/', views.ajax_issue_delete, name='ajax_issue_delete'),
    path('ajax/issue/import-opening/', views.ajax_issue_import_opening, name='ajax_issue_import_opening'),
    path('ajax/receipt/create/', views.ajax_receipt_create, name='ajax_receipt_create'),
    path('ajax/receipt/update/<int:pk>/', views.ajax_receipt_update, name='ajax_receipt_update'),
    path('ajax/receipt/list/', views.ajax_receipt_list, name='ajax_receipt_list'),
    path('ajax/receipt/delete/<int:pk>/', views.ajax_receipt_delete, name='ajax_receipt_delete'),
    path('ajax/receipt/import-opening/', views.ajax_receipt_import_opening, name='ajax_receipt_import_opening'),
    path('ajax/waste-log/create/', views.ajax_waste_log_create, name='ajax_waste_log_create'),
    path('ajax/waste-log/update/<int:pk>/', views.ajax_waste_log_update, name='ajax_waste_log_update'),
    path('ajax/waste-log/list/', views.ajax_waste_log_list, name='ajax_waste_log_list'),
    path('ajax/waste-log/delete/<int:pk>/', views.ajax_waste_log_delete, name='ajax_waste_log_delete'),
    path('ajax/waste-log/import-opening/', views.ajax_waste_log_import_opening, name='ajax_waste_log_import_opening'),
    path('ajax/stock-summary/', views.ajax_stock_summary, name='ajax_stock_summary'),
    path('ajax/price-history/', views.ajax_price_history, name='ajax_price_history'),
    path('ajax/financial-timeline/', views.ajax_financial_timeline, name='ajax_financial_timeline'),
    path('api/dashboard-stats/', views.dashboard_stats_json, name='dashboard_stats_json'),
]
