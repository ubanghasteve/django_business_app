# -*- coding: utf-8 -*-
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api_views

router = DefaultRouter()
router.register(r'', api_views.ExpenseViewSet, basename='expense')

app_name = 'expense_api'
urlpatterns = [
    path('', include(router.urls)),
]
