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
    # Primary (correct) product report URL: /inventory/product/<pk>/report/
    path('product/<int:pk>/report/', views.inventory_product_report, name='product_report'),
    # Friendly alias so /inventory/product/report/<pk>/ also works (no 404 if typed manually).
    path('product/report/<int:pk>/', views.inventory_product_report, name='product_report_alt'),
    path('print/<int:pk>/', views.inventory_print, name='print'),
    path('pdf/<int:pk>/', views.inventory_pdf, name='pdf'),
    path('ajax/update-field/', views.ajax_update_field, name='ajax_update_field'),
    path('ajax/status-update/', views.ajax_status_update, name='ajax_status_update'),
    path('ajax/create/', views.ajax_create, name='ajax_create'),
    path('api/dashboard-stats/', views.dashboard_stats_json, name='dashboard_stats_json'),
]
