from rest_framework.routers import DefaultRouter
from .api_views import StaffOffenceRegisterViewSet, StaffOffenceEntryViewSet

router = DefaultRouter()
router.register(r'registers', StaffOffenceRegisterViewSet, basename='staff-offence-register')
router.register(r'entries', StaffOffenceEntryViewSet, basename='staff-offence-entry')

urlpatterns = router.urls
