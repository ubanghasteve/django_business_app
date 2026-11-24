from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from apps.core.permissions import DjangoModelPermissions
from apps.core.ownership import drf_filter_queryset_for_user
from .models import StaffOffenceRegister, StaffOffenceEntry
from .serializers import (
    StaffOffenceRegisterSerializer,
    StaffOffenceRegisterCreateUpdateSerializer,
    StaffOffenceEntrySerializer,
)


class StaffOffenceRegisterViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    model = StaffOffenceRegister
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['year', 'month', 'staff_name']
    ordering = ['year', 'month', 'created_at', 'id']

    def get_queryset(self):
        qs = StaffOffenceRegister.objects.select_related(
            'created_by', 'company'
        ).prefetch_related('entries')
        return drf_filter_queryset_for_user(qs, self.request, account_lookup='account')

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return StaffOffenceRegisterCreateUpdateSerializer
        return StaffOffenceRegisterSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class StaffOffenceEntryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    model = StaffOffenceEntry
    serializer_class = StaffOffenceEntrySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['register', 'date']
    ordering = ['date', 'id']

    def get_queryset(self):
        qs = StaffOffenceEntry.objects.select_related('register', 'created_by')
        register_qs = drf_filter_queryset_for_user(
            StaffOffenceRegister.objects.all(),
            self.request,
            account_lookup='account',
        )
        return qs.filter(register__in=register_qs, is_deleted=False)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
