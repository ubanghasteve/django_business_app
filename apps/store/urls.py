# -*- coding: utf-8 -*-
from django.urls import path
from . import views

app_name = 'store'

urlpatterns = [
    path('', views.store_list, name='list'),
    path('list/print/', views.store_list_print, name='list_print'),
    path('list/pdf/', views.store_list_pdf, name='list_pdf'),
    path('dashboard/', views.store_dashboard, name='dashboard'),
    path('create/', views.store_create, name='create'),
    path('update/<int:pk>/', views.store_update, name='update'),
    path('delete/<int:pk>/', views.store_delete, name='delete'),
    path('confirm-delete/<int:pk>/', views.store_confirm_delete, name='confirm_delete'),
    path('detail/<int:pk>/', views.store_detail, name='detail'),
    # Waste Log URLs
    path('waste/', views.waste_list, name='waste_list'),
    path('waste/create/', views.waste_create, name='waste_create'),
    path('waste/delete/<int:pk>/', views.waste_delete, name='waste_delete'),
    path('api/waste-stats/', views.waste_stats_json, name='waste_stats_json'),
    # Product report URLs
    path('product/<int:pk>/report/', views.store_product_report, name='product_report'),
    path('product/report/<int:pk>/', views.store_product_report, name='product_report_alt'),
    path('print/<int:pk>/', views.store_print, name='print'),
    path('pdf/<int:pk>/', views.store_pdf, name='pdf'),
    path('ajax/update-field/', views.ajax_update_field, name='ajax_update_field'),
    path('ajax/status-update/', views.ajax_status_update, name='ajax_status_update'),
    path('ajax/create/', views.ajax_create, name='ajax_create'),
    path('api/dashboard-stats/', views.dashboard_stats_json, name='dashboard_stats_json'),
    # Category URLs
    path('category/', views.category_list, name='category_list'),
    path('category/create/', views.category_create, name='category_create'),
    path('category/update/<int:pk>/', views.category_update, name='category_update'),
    path('category/delete/<int:pk>/', views.category_delete, name='category_delete'),
    # Custom Field URLs
    path('custom-field/', views.custom_field_list, name='custom_field_list'),
    path('custom-field/create/', views.custom_field_create, name='custom_field_create'),
    path('custom-field/update/<int:pk>/', views.custom_field_update, name='custom_field_update'),
    path('custom-field/delete/<int:pk>/', views.custom_field_delete, name='custom_field_delete'),
    # Custom Form URLs
    path('custom-form/', views.custom_form_list, name='custom_form_list'),
    path('custom-form/create/', views.custom_form_create, name='custom_form_create'),
    path('custom-form/update/<int:pk>/', views.custom_form_update, name='custom_form_update'),
    path('custom-form/detail/<int:pk>/', views.custom_form_detail, name='custom_form_detail'),
    path('custom-form/delete/<int:pk>/', views.custom_form_delete, name='custom_form_delete'),
    # Layout URLs
    path('layout/', views.layout_list, name='layout_list'),
    path('layout/create/', views.layout_create, name='layout_create'),
    path('layout/update/<int:pk>/', views.layout_update, name='layout_update'),
    path('layout/preview/<int:pk>/', views.layout_preview, name='layout_preview'),
    path('layout/management/', views.layout_management, name='layout_management'),
    path('layout/delete/<int:pk>/', views.layout_delete, name='layout_delete'),
]
