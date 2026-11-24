from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .api_views import JobOrderViewSet

router = DefaultRouter()
router.register(r"", JobOrderViewSet, basename="job_order")

urlpatterns = [
    path("", include(router.urls)),
]
