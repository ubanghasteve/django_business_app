from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from apps.core.permissions import DjangoModelPermissions
from apps.core.ownership import drf_filter_queryset_for_user

from .models import Waybill
from .serializers import WaybillSerializer


class WaybillViewSet(viewsets.ModelViewSet):
    """
    REST API for waybills.

    - Scoped to the current tenant account (account field)
    - Excludes soft-deleted records (is_deleted=True)
    - Uses standard Django model permissions for RBAC
    """

    serializer_class = WaybillSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "waybill_date"]
    search_fields = ["waybill_number"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Waybill.objects.select_related("user", "account", "template")
        qs = qs.filter(is_deleted=False)
        return drf_filter_queryset_for_user(qs, self.request, account_lookup="account")

