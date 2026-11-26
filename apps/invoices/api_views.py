from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q

from apps.core.permissions import DjangoModelPermissions
from apps.core.ownership import drf_filter_queryset_for_user
from .models import Invoice
from .serializers import InvoiceSerializer, InvoiceCreateSerializer


class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    model = Invoice
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status', 'invoice_date', 'due_date']
    search_fields = ['invoice_number', 'client_name', 'client_email']
    ordering = ['-created_at']
    
    def get_queryset(self):
        qs = Invoice.objects.prefetch_related('items').select_related('user', 'created_by')
        return drf_filter_queryset_for_user(qs, self.request, account_lookup='account')
    
    def get_serializer_class(self):
        if self.action == 'create':
            return InvoiceCreateSerializer
        return InvoiceSerializer
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def search(self, request):
        """Search invoices by invoice number, client name, or email"""
        query = request.query_params.get('q', '')
        if query:
            invoices = self.get_queryset().filter(
                Q(invoice_number__icontains=query) |
                Q(client_name__icontains=query) |
                Q(client_email__icontains=query)
            )
        else:
            invoices = self.get_queryset()
        
        serializer = self.get_serializer(invoices, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get invoice statistics"""
        invoices = self.get_queryset()
        return Response({
            'total_invoices': invoices.count(),
            'total_amount': sum(inv.grand_total for inv in invoices),
            'paid_amount': sum(inv.amount_paid for inv in invoices),
            'unpaid_count': invoices.filter(status='unpaid').count(),
            'partial_count': invoices.filter(status='partial').count(),
            'paid_count': invoices.filter(status='paid').count(),
        })

    @action(detail=True, methods=['get'], url_path='info')
    def info(self, request, pk=None):
        invoice = self.get_object()
        # Try to get default color and currency from company profile (account company for team members)
        custom_color = None
        currency_code = 'NGN'
        currency_symbol = '₦'
        try:
            from apps.core.utils import get_company_profile_for_user
            profile = get_company_profile_for_user(request.user, request)
            if profile:
                if hasattr(profile, 'currency_code'):
                    currency_code = profile.currency_code
                if hasattr(profile, 'currency_symbol'):
                    currency_symbol = profile.currency_symbol
                if hasattr(profile, 'primary_color'):
                    custom_color = profile.primary_color
        except Exception:
            pass
        from apps.core.utils import number_to_words
        # Use amount_paid for amount in words if available, otherwise use grand_total
        amount_for_words = invoice.amount_paid if invoice.amount_paid > 0 else invoice.grand_total
        amount_in_words = number_to_words(amount_for_words, currency_code)
        return Response({
            'client_name': invoice.client_name,
            'client_email': invoice.client_email,
            'client_phone': invoice.client_phone,
            'client_address': invoice.client_address,
            'grand_total': str(invoice.grand_total),
            'amount_paid': str(invoice.amount_paid),
            'balance_due': str(invoice.balance_due),
            'status': invoice.status,
            'invoice_number': invoice.invoice_number,
            'payment_method': 'cash',  # Default, or you can customize
            'received_by': request.user.get_full_name() or request.user.get_username() or '',
            'custom_color': custom_color or '#1976d2',
            'amount_in_words': amount_in_words,
            'transaction_id': invoice.invoice_number,
            'currency_code': currency_code,
            'currency_symbol': currency_symbol,
            'id': invoice.pk,
        })
