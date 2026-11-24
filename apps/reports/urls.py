# -*- coding: utf-8 -*-
from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('dashboard/', views.tax_dashboard_view, name='tax_dashboard'),
    path('monthly/', views.monthly_report_view, name='monthly_report'),
    path('quarterly/', views.quarterly_report_view, name='quarterly_report'),
    path('annual/', views.annual_report_view, name='annual_report'),
    path('history/', views.tax_history_view, name='tax_history'),
    path('profit-and-loss/', views.profit_and_loss_view, name='profit_and_loss'),
    path('balance-sheet/', views.balance_sheet_view, name='balance_sheet'),
    path('api/dashboard/', views.api_reports_dashboard, name='api_dashboard'),
    path('export/pdf/', views.tax_report_pdf_view, name='tax_report_pdf'),
]
