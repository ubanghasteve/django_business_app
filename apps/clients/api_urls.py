from django.urls import path
from . import api_views

app_name = 'clients_api'

urlpatterns = [
    path('', api_views.client_list_api, name='client_list'),
    path('<int:client_id>/', api_views.client_detail_api, name='client_detail'),
]
