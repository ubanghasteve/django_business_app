from django.urls import path
from . import api_views, views

app_name = 'notifications'

urlpatterns = [
    path('', views.notification_list_page, name='list'),
    path('api/', api_views.notification_list_api, name='api_list'),
    path('api/badge/', api_views.notification_badge_api, name='api_badge'),
    path('api/mark-all-read/', api_views.notification_mark_all_read_api, name='api_mark_all_read'),
    path('api/clear-all/', api_views.notification_clear_all_api, name='api_clear_all'),
    path('api/<int:pk>/mark-read/', api_views.notification_mark_read_api, name='api_mark_read'),
    path('api/<int:pk>/delete/', api_views.notification_delete_api, name='api_delete'),
]
