# -*- coding: utf-8 -*-
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api_views

router = DefaultRouter()
router.register(r'', api_views.InventoryViewSet, basename='inventory')

app_name = 'inventory_api'
urlpatterns = [
    path('', include(router.urls)),
]
