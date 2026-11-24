# -*- coding: utf-8 -*-
"""
DRF API for Inventory: list, retrieve, create, update, destroy, status_update, search_filter.
Company isolation via drf_filter_queryset_for_user(account_lookup='account').
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from django.db.models import Q

from apps.core.permissions import DjangoModelPermissions
from apps.core.ownership import drf_filter_queryset_for_user
from .models import Inventory, WasteLog
from .serializers import InventorySerializer, WasteLogSerializer


class InventoryViewSet(viewsets.ModelViewSet):
    """
    list, retrieve, create, update, destroy, status_update, search_filter.
    All queries enforce company isolation (account + visibility).
    """
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = InventorySerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['approval_status', 'stock_status', 'workflow_status']
    search_fields = ['product_name', 'vendor', 'transaction_id', 'stock_location', 'category']
    ordering_fields = ['created_at', 'product_name', 'quantity_in', 'quantity_out', 'total_amount']
    ordering = ['-created_at']

    def get_queryset(self):
        qs = Inventory.objects.select_related('company', 'created_by', 'account')
        qs = drf_filter_queryset_for_user(qs, self.request, account_lookup='account')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def status_update(self, request, pk=None):
        """Update approval_status and/or workflow_status. Only authorized roles can approve."""
        obj = self.get_object()
        approval = request.data.get('approval_status')
        workflow = request.data.get('workflow_status')
        if approval and approval in dict(Inventory.APPROVAL_STATUS_CHOICES):
            obj.approval_status = approval
        if workflow and workflow in dict(Inventory.WORKFLOW_STATUS_CHOICES):
            obj.workflow_status = workflow
        obj.save()
        serializer = self.get_serializer(obj)
        return Response(serializer.data)


class WasteLogViewSet(viewsets.ModelViewSet):
    """
    API for WasteLog: list, retrieve, create, destroy.
    Company isolation via drf_filter_queryset_for_user(account_lookup='account').
    """
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = WasteLogSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['reason', 'inventory']
    search_fields = ['inventory__product_name', 'description']
    ordering_fields = ['waste_date', 'created_at', 'quantity', 'total_value']
    ordering = ['-waste_date', '-created_at']

    def get_queryset(self):
        qs = WasteLog.objects.select_related('inventory', 'created_by', 'company')
        qs = drf_filter_queryset_for_user(qs, self.request, account_lookup='account')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(waste_date__gte=date_from)
        if date_to:
            qs = qs.filter(waste_date__lte=date_to)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
