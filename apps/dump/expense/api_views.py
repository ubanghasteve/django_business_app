# -*- coding: utf-8 -*-
"""
DRF API for Expense: list, retrieve, create, update, destroy, status_update, search_filter.
Company isolation via drf_filter_queryset_for_user(account_lookup='account').
"""
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from apps.core.permissions import DjangoModelPermissions
from apps.core.ownership import drf_filter_queryset_for_user
from .models import Expense
from .serializers import ExpenseSerializer


class ExpenseViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = ExpenseSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'expense_category', 'payment_method']
    search_fields = [
        'product_name', 'vendor', 'transaction_id', 'expense_category', 'department',
        'po_number', 'description', 'product_id', 'product_category',
    ]
    ordering_fields = [
        'created_at', 'expense_date', 'product_name', 'quantity_purchased',
        'quantity_out', 'total_amount', 'updated_at',
    ]
    ordering = ['-expense_date', '-created_at']

    def get_queryset(self):
        qs = Expense.objects.select_related('company', 'created_by', 'approved_by', 'account')
        qs = drf_filter_queryset_for_user(qs, self.request, account_lookup='account')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(expense_date__gte=date_from)
        if date_to:
            qs = qs.filter(expense_date__lte=date_to)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def status_update(self, request, pk=None):
        from django.utils import timezone
        obj = self.get_object()
        status_val = request.data.get('status') or request.data.get('approval_status')
        if status_val and status_val in dict(Expense.STATUS_CHOICES):
            obj.status = status_val
            if status_val == 'approved':
                obj.approved_by = request.user
                obj.approved_at = timezone.now()
            else:
                obj.approved_by = None
                obj.approved_at = None
            obj.save()
        serializer = self.get_serializer(obj)
        return Response(serializer.data)
