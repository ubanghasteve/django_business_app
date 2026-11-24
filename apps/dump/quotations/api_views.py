from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import DjangoModelPermissions
from apps.core.ownership import drf_filter_queryset_for_user
from .models import Quotation, QuotationItem, QuotationTemplate
from .serializers import QuotationSerializer, QuotationItemSerializer, QuotationTemplateSerializer


class QuotationViewSet(viewsets.ModelViewSet):
    serializer_class = QuotationSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    model = Quotation

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Quotation.objects.none()
        qs = Quotation.objects.all()
        return drf_filter_queryset_for_user(qs, self.request, account_lookup='account')


class QuotationItemViewSet(viewsets.ModelViewSet):
    serializer_class = QuotationItemSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    model = QuotationItem

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return QuotationItem.objects.none()
        visible_quotations = drf_filter_queryset_for_user(
            Quotation.objects.all(), self.request, account_lookup='account'
        )
        return QuotationItem.objects.filter(quotation__in=visible_quotations)


class QuotationTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = QuotationTemplateSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    model = QuotationTemplate

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return QuotationTemplate.objects.none()
        return QuotationTemplate.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)