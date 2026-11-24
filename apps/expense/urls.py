# -*- coding: utf-8 -*-
from django.urls import path
from . import views

app_name = 'expense'

urlpatterns = [
    path('', views.expense_list, name='list'),
    path('list/print/', views.expense_list_print, name='list_print'),
    path('list/pdf/', views.expense_list_pdf, name='list_pdf'),
    path('dashboard/', views.expense_dashboard, name='dashboard'),
    path('create/', views.expense_create, name='create'),
    path('update/<int:pk>/', views.expense_update, name='update'),
    path('delete/<int:pk>/', views.expense_delete, name='delete'),
    path('detail/<int:pk>/', views.expense_detail, name='detail'),
    path('product/<int:pk>/report/', views.expense_product_report, name='product_report'),
    path('product/report/<int:pk>/', views.expense_product_report, name='product_report_alt'),
    path('print/<int:pk>/', views.expense_print, name='print'),
    path('pdf/<int:pk>/', views.expense_pdf, name='pdf'),
    path('ajax/update-field/', views.ajax_update_field, name='ajax_update_field'),
    path('ajax/status-update/', views.ajax_status_update, name='ajax_status_update'),
    path('ajax/create/', views.ajax_create, name='ajax_create'),
    path('api/dashboard-stats/', views.dashboard_stats_json, name='dashboard_stats_json'),
]
