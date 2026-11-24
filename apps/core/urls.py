from django.urls import path
from . import views, api_views, summary_api

app_name = 'core'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('landing/', views.landing_page, name='landing_page'),
    path('company-profile/', views.company_profile_view, name='company_profile'),
    path('bank-accounts/', views.bank_accounts_view, name='bank_accounts'),
    path('bank-accounts/<int:pk>/edit/', views.edit_bank_account, name='edit_bank_account'),
    path('bank-accounts/<int:pk>/delete/', views.delete_bank_account, name='delete_bank_account'),
    path('bank-accounts/<int:pk>/set-default/', views.set_default_bank_account, name='set_default_bank_account'),
    path('update-currency/', views.update_currency, name='update_currency'),
    
    # API endpoints for dashboard
    path('api/dashboard/stats/', api_views.dashboard_stats, name='dashboard_stats'),
    path('api/dashboard/charts/', api_views.dashboard_charts_data, name='dashboard_charts'),
    path('api/dashboard/actions/', api_views.dashboard_quick_actions, name='dashboard_actions'),
    path('api/dashboard/tips/', api_views.dashboard_tips, name='dashboard_tips'),
    path('api/core/num2words/', api_views.num2words_api, name='num2words_api'),
    path('api/ping/', api_views.api_ping, name='api_ping'),
    path('api/debug-session/', api_views.debug_session, name='debug_session'),
    # Read-only summary endpoints (for AJAX metrics refresh)
    path('api/summaries/dashboard/', summary_api.dashboard_metrics, name='summary_dashboard'),
    path('api/summaries/dashboard/full/', summary_api.dashboard_full_metrics, name='summary_dashboard_full'),
    path('api/summaries/invoices/', summary_api.invoices_summary, name='summary_invoices'),
    path('api/summaries/receipts/', summary_api.receipts_summary, name='summary_receipts'),
    path('api/summaries/quotations/', summary_api.quotations_summary, name='summary_quotations'),
    path('api/summaries/job-orders/', summary_api.job_orders_summary, name='summary_job_orders'),
    path('api/summaries/waybills/', summary_api.waybills_summary, name='summary_waybills'),
]
