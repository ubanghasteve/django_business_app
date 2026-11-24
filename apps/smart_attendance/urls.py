from django.urls import path

from . import views

app_name = "smart_attendance"

urlpatterns = [
    path("dashboard", views.dashboard, name="dashboard"),
    path("devices", views.devices, name="devices"),
    path("devices/register", views.register_device, name="register_device"),
    path("device/<int:pk>/setup-complete", views.device_setup_complete, name="device_setup_complete"),
    path("device/<int:pk>", views.device_detail, name="device_detail"),
    path("employees", views.employees, name="employees"),
    path("employees/create", views.create_employee, name="create_employee"),
    path("employee/<int:pk>/edit", views.edit_employee, name="edit_employee"),
    path("employee/<int:pk>", views.employee_profile, name="employee_profile"),
    path("logs", views.attendance_logs, name="logs"),
    path("daily", views.daily_attendance_view, name="daily_attendance"),
    path("analytics", views.analytics_view, name="analytics"),
    # Export
    path("export/daily/csv", views.export_daily_attendance_csv, name="export_daily_csv"),
    path(
        "export/analytics/excel",
        views.export_attendance_analytics_excel,
        name="export_analytics_excel",
    ),
]

