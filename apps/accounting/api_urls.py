from django.urls import path, include
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
# ViewSets can be registered here in future if needed.

urlpatterns = [
    path("", include(router.urls)),
    # Core accounting APIs (JSON, AJAX-friendly)
    path("chart-of-accounts/", views.api_chart_of_accounts, name="api_chart_of_accounts"),
    path("journal/", views.api_journal_list, name="api_journal_list"),
    path("journal/create/", views.api_journal_create, name="api_journal_create"),
    path("journal/<int:journal_id>/", views.api_journal_detail, name="api_journal_detail"),
    path("ledger/", views.api_ledger, name="api_ledger"),
    path("trial-balance/", views.api_trial_balance, name="api_trial_balance"),
    path("profit-loss/", views.api_profit_loss, name="api_profit_loss"),
    path("balance-sheet/", views.api_balance_sheet, name="api_balance_sheet"),
    path("ledger-summary/", views.api_ledger_summary, name="api_ledger_summary"),
    path("accounts-receivable/", views.api_accounts_receivable, name="api_accounts_receivable"),
    path("outstanding-invoices/", views.api_outstanding_invoices, name="api_outstanding_invoices"),
    path("accounts-payable/", views.api_accounts_payable, name="api_accounts_payable"),
    path("tax-summary/", views.api_tax_summary, name="api_tax_summary"),
    path("dashboard/", views.api_dashboard, name="api_dashboard"),
    path("transactions/", views.api_transactions, name="api_transactions"),
]
