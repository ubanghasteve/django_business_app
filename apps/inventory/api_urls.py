# -*- coding: utf-8 -*-
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api_views

router = DefaultRouter()
router.register(r'inventory', api_views.InventoryViewSet, basename='inventory')
router.register(r'waste-log', api_views.WasteLogViewSet, basename='waste-log')

app_name = 'inventory_api'
urlpatterns = [
    path('', include(router.urls)),
]
