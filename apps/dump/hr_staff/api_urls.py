# -*- coding: utf-8 -*-
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api_views

router = DefaultRouter()
router.register(r'departments', api_views.DepartmentViewSet, basename='hr-department')
router.register(r'employees', api_views.EmployeeViewSet, basename='hr-employee')
router.register(r'leave-requests', api_views.LeaveRequestViewSet, basename='hr-leaverequest')

app_name = 'hr_staff_api'
urlpatterns = [
    path('dashboard-stats/', api_views.dashboard_stats_api, name='dashboard_stats'),
    path('dashboard-widgets/', api_views.dashboard_widgets_api, name='dashboard_widgets'),
    path('notifications/', api_views.hr_notifications_api, name='hr_notifications'),
    path('account-users-without-employee/', api_views.account_users_without_employee_api, name='account_users_without_employee'),
    path('', include(router.urls)),
]
