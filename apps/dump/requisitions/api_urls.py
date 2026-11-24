from rest_framework.routers import DefaultRouter
from .api_views import RequisitionViewSet

router = DefaultRouter()
router.register(r'', RequisitionViewSet, basename='requisition')

urlpatterns = router.urls
