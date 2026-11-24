# -*- coding: utf-8 -*-
from django.urls import path
from . import views

app_name = 'tax_engine'

urlpatterns = [
    path('compute/', views.api_tax_compute, name='api_compute'),
    path('list/', views.api_tax_list, name='api_list'),
]
