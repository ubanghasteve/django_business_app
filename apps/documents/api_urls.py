# -*- coding: utf-8 -*-
from django.urls import path
from . import api_views

urlpatterns = [
    path('upload/', api_views.api_upload),
    path('<int:pk>/status/', api_views.api_status),
]
