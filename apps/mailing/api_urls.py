from django.urls import path
from . import api_views

app_name = 'mailing_api'

urlpatterns = [
    path('recipients/', api_views.recipients_api, name='recipients'),
    path('send-email/', api_views.send_bulk_email_api, name='send_email'),
    path('send-sms/', api_views.send_bulk_sms_api, name='send_sms'),
]
