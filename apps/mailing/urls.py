from django.urls import path
from . import views

app_name = 'mailing'

urlpatterns = [
    path('', views.bulk_send_page, name='bulk_send'),
]
