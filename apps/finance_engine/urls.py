# -*- coding: utf-8 -*-
from django.urls import path
from . import views

app_name = 'finance_engine'

urlpatterns = [
    path('list/', views.api_transaction_list, name='api_list'),
]
