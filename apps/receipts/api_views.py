from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from apps.core.permissions import DjangoModelPermissions
from apps.core.ownership import drf_filter_queryset_for_user

from .models import Receipt
from .serializers import ReceiptSerializer


class ReceiptViewSet(viewsets.ModelViewSet):
    """
    REST API for receipts.

    - Scoped to the current tenant account (account field)
    - Excludes soft-deleted records (is_deleted=True)
    - Uses standard Django model permissions for RBAC
    """

    serializer_class = ReceiptSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["payment_method", "date_received"]
    search_fields = ["receipt_no", "client_name", "client_phone", "client_address"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Receipt.objects.select_related("invoice", "created_by", "account")
        qs = qs.filter(is_deleted=False)
        return drf_filter_queryset_for_user(qs, self.request, account_lookup="account")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

