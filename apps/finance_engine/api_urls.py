# -*- coding: utf-8 -*-
from django.urls import path
from . import api_views

urlpatterns = [
    path('extract/', api_views.api_extract),
]
