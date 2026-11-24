from django.urls import path
from . import views

app_name = 'accounting'

urlpatterns = [
    # Dashboard and main views
    path('', views.accounting_dashboard, name='dashboard'),
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('ledger/', views.ledger_summary, name='ledger_summary'),

    # High-level accounting pages (for spec alignment)
    path('chart-of-accounts/', views.chart_of_accounts_list, name='chart_of_accounts_list'),
    path('chart-of-accounts/create/', views.chart_of_accounts_create, name='chart_of_accounts_create'),
    path('chart-of-accounts/<int:account_id>/edit/', views.chart_of_accounts_edit, name='chart_of_accounts_edit'),
    path('chart-of-accounts/<int:account_id>/delete/', views.chart_of_accounts_delete, name='chart_of_accounts_delete'),
    path('journal/', views.accounting_journal_page, name='journal_page'),
    path('journal/create/', views.journal_entry_create_page, name='journal_create_page'),
    path('journal/<int:journal_id>/edit/', views.journal_entry_edit, name='journal_edit'),
    path('journal/<int:journal_id>/void/', views.journal_entry_void, name='journal_void'),
    path('journal/<int:journal_id>/delete/', views.journal_entry_delete, name='journal_delete'),
    path('trial-balance/', views.accounting_trial_balance_page, name='trial_balance_page'),
    path('profit-loss/', views.accounting_profit_loss_page, name='profit_loss_page'),
    path('balance-sheet/', views.accounting_balance_sheet_page, name='balance_sheet_page'),
    path('cash-flow/', views.accounting_cash_flow_page, name='cash_flow_page'),
    path('tax-summary/', views.accounting_tax_summary_page, name='tax_summary_page'),
    
    # Transaction management
    path('transactions/add/', views.add_transaction, name='add_transaction'),
    path('transactions/<uuid:transaction_id>/edit/', views.edit_transaction, name='edit_transaction'),
    path('transactions/<uuid:transaction_id>/delete/', views.delete_transaction, name='delete_transaction'),
    path('transactions/<uuid:transaction_id>/reconcile/', views.reconcile_transaction, name='reconcile_transaction'),
    path('transactions/<uuid:transaction_id>/unreconcile/', views.unreconcile_transaction, name='unreconcile_transaction'),
    path('transactions/update_currencies/', views.update_transaction_currencies, name='update_transaction_currencies'),
    
    # Export and reports
    path('export/', views.export_accounting_data, name='export_data'),
    path('reports/generate/', views.generate_report, name='generate_report'),
    path('reports/<int:report_id>/', views.view_report, name='view_report'),
    path('reports/<int:report_id>/export-pdf/', views.export_report_pdf, name='export_report_pdf'),
    path('reports/<int:report_id>/export-excel/', views.export_report_excel, name='export_report_excel'),
    
    # Sync and utilities
    path('sync/', views.sync_from_other_apps, name='sync_from_other_apps'),
    
    # AJAX endpoints
    path('ajax/update-ledger/', views.update_ledger_ajax, name='update_ledger_ajax'),
    path('ajax/update-currency/', views.update_accounting_currency, name='update_accounting_currency'),
]
