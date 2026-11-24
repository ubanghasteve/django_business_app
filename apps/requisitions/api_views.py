from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q

from apps.core.permissions import DjangoModelPermissions
from apps.core.ownership import drf_filter_queryset_for_user
from .models import Requisition
from .serializers import RequisitionSerializer, RequisitionCreateUpdateSerializer


class RequisitionViewSet(viewsets.ModelViewSet):
    """
    List, Create, Retrieve, Update, Delete requisitions.
    All endpoints enforce company isolation (account + visibility) and permission checks.
    """
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    model = Requisition
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'date']
    search_fields = ['reference_number', 'organization_name']
    ordering = ['-created_at']

    def get_queryset(self):
        qs = Requisition.objects.select_related('created_by', 'company')
        return drf_filter_queryset_for_user(qs, self.request, account_lookup='account')

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return RequisitionCreateUpdateSerializer
        return RequisitionSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
