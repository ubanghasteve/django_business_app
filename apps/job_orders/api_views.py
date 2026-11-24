from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from apps.core.permissions import DjangoModelPermissions
from apps.core.ownership import drf_filter_queryset_for_user

from .models import Product
from .serializers import JobOrderSerializer


class JobOrderViewSet(viewsets.ModelViewSet):
    """
    REST API for job orders (products).

    - Scoped to the current tenant account (account field)
    - Excludes soft-deleted records (is_deleted=True)
    - Uses standard Django model permissions for RBAC
    """

    serializer_class = JobOrderSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["approval_status", "estimated_delivery_date"]
    search_fields = ["job_order", "organization_name", "contact_number"]
    ordering = ["-date_created"]

    def get_queryset(self):
        qs = Product.objects.select_related("created_by", "account")
        qs = qs.filter(is_deleted=False)
        return drf_filter_queryset_for_user(qs, self.request, account_lookup="account")

