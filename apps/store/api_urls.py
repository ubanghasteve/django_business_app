# -*- coding: utf-8 -*-
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import api_views

router = DefaultRouter()
router.register(r'store', api_views.StoreViewSet, basename='store')
router.register(r'waste-log', api_views.WasteLogViewSet, basename='waste-log')

app_name = 'store_api'
urlpatterns = [
    path('', include(router.urls)),
]
