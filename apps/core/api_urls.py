from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api_views, views

app_name = 'core_api'

# router = DefaultRouter()
# router.register(r'company-profiles', api_views.CompanyProfileViewSet, basename='companyprofile')
# router.register(r'bank-accounts', api_views.BankAccountViewSet, basename='bankaccount')

urlpatterns = [
    # path('', include(router.urls)),
    # path('currencies/', api_views.CurrencyListView.as_view(), name='currency_list'),
    # path('auto-number/<str:doc_type>/', api_views.AutoNumberView.as_view(), name='auto_number'),
    path('num2words/', api_views.num2words_api, name='num2words'),
    path('my-ip/', api_views.my_ip, name='my_ip'),
    
    # Dashboard API endpoints
    path('dashboard/stats/', api_views.dashboard_stats, name='dashboard_stats'),
    path('dashboard/charts/', api_views.dashboard_charts_data, name='dashboard_charts'),
    path('dashboard/actions/', api_views.dashboard_quick_actions, name='dashboard_actions'),
    path('dashboard/tips/', api_views.dashboard_tips, name='dashboard_tips'),
    
    # Real-time update endpoints
    path('dashboard/realtime/', api_views.dashboard_realtime_updates, name='dashboard_realtime'),
    path('dashboard/notifications/', api_views.dashboard_notifications, name='dashboard_notifications'),
    path('dashboard/activity/', api_views.dashboard_activity_feed, name='dashboard_activity'),
    path('dashboard/inventory-alerts/', api_views.dashboard_inventory_alerts, name='dashboard_inventory_alerts'),
    path('dashboard/system-health/', api_views.dashboard_system_health, name='dashboard_system_health'),
    
    # Currency and settings
    path('update-currency/', views.update_currency, name='update_currency'),
    path('currency-status/', api_views.currency_status, name='currency_status'),
]
