# -*- coding: utf-8 -*-
from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.api_reports_dashboard),
]
