# -*- coding: utf-8 -*-
"""
Reports app - tax dashboard and period reports. All company-scoped.
AJAX endpoints return JSON for live refresh.
Export tax report as PDF.
"""
from datetime import date
import calendar
from decimal import Decimal
from io import BytesIO

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum

from apps.core.utils import get_company_profile_for_user
from apps.core.permissions import company_admin_or_permission_required
from apps.finance_engine.models import FinancialTransaction, Account, JournalLine
from apps.tax_engine.models import TaxRecord
from apps.tax_engine.services import compute_tax


def _company(request):
    return getattr(request, 'company', None) or get_company_profile_for_user(request.user, request)


def _period_bounds(period_type, year=None, month=None):
    """Return (period_start, period_end) for monthly/quarterly/yearly."""
    today = date.today()
    y = year or today.year
    m = month or today.month
    if period_type == 'yearly':
        return date(y, 1, 1), date(y, 12, 31)
    if period_type == 'quarterly':
        q = (m - 1) // 3 + 1
        start_m = (q - 1) * 3 + 1
        end_m = q * 3
        _, end_d = calendar.monthrange(y, end_m)
        return date(y, start_m, 1), date(y, end_m, end_d)
    # monthly
    _, last_d = calendar.monthrange(y, m)
    return date(y, m, 1), date(y, m, last_d)


@login_required
@company_admin_or_permission_required('documents.view_tax_report', raise_exception=True)
@require_GET
def tax_dashboard_view(request):
    """Tax dashboard page. Uses AJAX for live refresh of totals."""
    company = _company(request)
    if not company:
        return render(request, 'reports/tax_dashboard.html', {'error': 'No company'})
    return render(request, 'reports/tax_dashboard.html', {})


@login_required
@company_admin_or_permission_required('documents.view_tax_report', raise_exception=True)
@require_GET
def monthly_report_view(request):
    """Monthly report page."""
    company = _company(request)
    if not company:
        return render(request, 'reports/monthly_report.html', {'error': 'No company'})
    return render(request, 'reports/monthly_report.html', {})


@login_required
@company_admin_or_permission_required('documents.view_tax_report', raise_exception=True)
@require_GET
def quarterly_report_view(request):
    """Quarterly report page."""
    company = _company(request)
    if not company:
        return render(request, 'reports/quarterly_report.html', {'error': 'No company'})
    return render(request, 'reports/quarterly_report.html', {})


@login_required
@company_admin_or_permission_required('documents.view_tax_report', raise_exception=True)
@require_GET
def annual_report_view(request):
    """Annual report page."""
    company = _company(request)
    if not company:
        return render(request, 'reports/annual_report.html', {'error': 'No company'})
    return render(request, 'reports/annual_report.html', {})


@login_required
@company_admin_or_permission_required('documents.view_tax_report', raise_exception=True)
@require_GET
def tax_history_view(request):
    """
    List all saved TaxRecord rows for the current company.
    This gives a visible history of computed reports (monthly/quarterly/yearly).
    """
    company = _company(request)
    if not company:
        return render(request, 'reports/tax_history.html', {'error': 'No company', 'records': []})
    records = list(TaxRecord.objects.filter(company=company).order_by('-period_end', '-created_at'))
    return render(request, 'reports/tax_history.html', {'records': records})


# ----- AJAX API: dashboard data (JSON) -----
@login_required
@company_admin_or_permission_required('documents.view_tax_report', raise_exception=True)
@require_GET
def api_reports_dashboard(request):
    """
    GET: optional period_type, year, month. Returns total revenue, total expenses, tax payable, vat payable.
    """
    company = _company(request)
    if not company:
        return JsonResponse({'status': 'error', 'message': 'No company'}, status=403)
    period_type = request.GET.get('period_type', 'monthly')
    try:
        year = int(request.GET.get('year') or date.today().year)
        month = int(request.GET.get('month') or date.today().month)
    except (TypeError, ValueError):
        year, month = date.today().year, date.today().month
    period_start, period_end = _period_bounds(period_type, year, month)
    record = compute_tax(company, period_type, period_start, period_end)
    return JsonResponse({
        'status': 'success',
        'period_type': period_type,
        'period_start': period_start.isoformat(),
        'period_end': period_end.isoformat(),
        'total_revenue': str(record.total_revenue),
        'total_expenses': str(record.total_expenses),
        'tax_payable': str(record.corporate_tax),
        'vat_payable': str(record.vat_payable),
    })


# ----- Export tax report as PDF -----
@login_required
@company_admin_or_permission_required('documents.view_tax_report', raise_exception=True)
@require_GET
def tax_report_pdf_view(request):
    """
    GET: period_type, year, month. Returns PDF with tax summary for that period.
    """
    company = _company(request)
    if not company:
        return HttpResponse('No company', status=403)
    try:
        period_type = request.GET.get('period_type', 'monthly')
        year = int(request.GET.get('year') or date.today().year)
        month = int(request.GET.get('month') or date.today().month)
    except (TypeError, ValueError):
        year, month = date.today().year, date.today().month
    period_start, period_end = _period_bounds(period_type, year, month)
    record = compute_tax(company, period_type, period_start, period_end)
    currency = getattr(company, 'currency_symbol', None) or ''

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.units import inch
    except ImportError:
        return HttpResponse('PDF export requires reportlab', status=500)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=inch, leftMargin=inch, topMargin=inch, bottomMargin=inch)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, spaceAfter=12)
    story.append(Paragraph('Tax Report', title_style))
    story.append(Paragraph(f'Company: {getattr(company, "company_name", "") or "N/A"}', styles['Normal']))
    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph(f'Period: {period_start} to {period_end} ({period_type})', styles['Normal']))
    story.append(Spacer(1, 0.3 * inch))

    def _fmt(d):
        return f'{currency}{float(d):,.2f}'
    data = [
        ['Metric', 'Amount'],
        ['Total Revenue', _fmt(record.total_revenue)],
        ['Total Expenses', _fmt(record.total_expenses)],
        ['Taxable Profit', _fmt(record.taxable_profit)],
        ['Corporate Tax (30%)', _fmt(record.corporate_tax)],
        ['VAT Payable', _fmt(record.vat_payable)],
    ]
    t = Table(data, colWidths=[3 * inch, 2.5 * inch])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    story.append(t)
    doc.build(story)
    buffer.seek(0)
    filename = f'tax_report_{period_type}_{period_start}_{period_end}.pdf'
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
@company_admin_or_permission_required('documents.view_tax_report', raise_exception=True)
@require_GET
def profit_and_loss_view(request):
    """
    Simple Profit & Loss report built from journal lines.
    Shows totals for income and expense accounts for a selected year/month.
    """
    company = _company(request)
    if not company:
        return render(request, 'reports/profit_and_loss.html', {'error': 'No company'})
    try:
        year = int(request.GET.get('year') or date.today().year)
        month = int(request.GET.get('month') or date.today().month)
    except (TypeError, ValueError):
        year, month = date.today().year, date.today().month
    period_start, period_end = _period_bounds('monthly', year, month)

    q = JournalLine.objects.filter(
        entry__company=company,
        entry__entry_date__gte=period_start,
        entry__entry_date__lte=period_end,
    ).select_related('account')

    # Aggregate by account for income and expenses.
    income_accounts = {}
    expense_accounts = {}
    for line in q:
        acc = line.account
        if acc.account_type not in (Account.TYPE_INCOME, Account.TYPE_EXPENSE):
            continue
        balance = (line.credit or Decimal('0')) - (line.debit or Decimal('0')) if acc.account_type == Account.TYPE_INCOME else (line.debit or Decimal('0')) - (line.credit or Decimal('0'))
        if acc.account_type == Account.TYPE_INCOME:
            income_accounts.setdefault(acc, Decimal('0'))
            income_accounts[acc] += balance
        else:
            expense_accounts.setdefault(acc, Decimal('0'))
            expense_accounts[acc] += balance

    total_income = sum(income_accounts.values()) if income_accounts else Decimal('0')
    total_expenses = sum(expense_accounts.values()) if expense_accounts else Decimal('0')
    net_profit = total_income - total_expenses

    context = {
        'error': '',
        'period_start': period_start,
        'period_end': period_end,
        'year': year,
        'month': month,
        'income_accounts': income_accounts,
        'expense_accounts': expense_accounts,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net_profit': net_profit,
    }
    return render(request, 'reports/profit_and_loss.html', context)


@login_required
@company_admin_or_permission_required('documents.view_tax_report', raise_exception=True)
@require_GET
def balance_sheet_view(request):
    """
    Simple Balance Sheet built from journal lines.
    Uses all entries up to the selected date (year/month end).
    """
    company = _company(request)
    if not company:
        return render(request, 'reports/balance_sheet.html', {'error': 'No company'})
    try:
        year = int(request.GET.get('year') or date.today().year)
        month = int(request.GET.get('month') or date.today().month)
    except (TypeError, ValueError):
        year, month = date.today().year, date.today().month
    period_start, period_end = _period_bounds('monthly', year, month)

    q = JournalLine.objects.filter(
        entry__company=company,
        entry__entry_date__lte=period_end,
    ).select_related('account')

    assets = {}
    liabilities = {}
    equity = {}
    for line in q:
        acc = line.account
        debit = line.debit or Decimal('0')
        credit = line.credit or Decimal('0')
        if acc.account_type == Account.TYPE_ASSET:
            bal = debit - credit
            assets.setdefault(acc, Decimal('0'))
            assets[acc] += bal
        elif acc.account_type == Account.TYPE_LIABILITY:
            bal = credit - debit
            liabilities.setdefault(acc, Decimal('0'))
            liabilities[acc] += bal
        elif acc.account_type == Account.TYPE_EQUITY:
            bal = credit - debit
            equity.setdefault(acc, Decimal('0'))
            equity[acc] += bal

    total_assets = sum(assets.values()) if assets else Decimal('0')
    total_liabilities = sum(liabilities.values()) if liabilities else Decimal('0')
    total_equity = sum(equity.values()) if equity else Decimal('0')

    context = {
        'error': '',
        'period_end': period_end,
        'year': year,
        'month': month,
        'assets': assets,
        'liabilities': liabilities,
        'equity': equity,
        'total_assets': total_assets,
        'total_liabilities': total_liabilities,
        'total_equity': total_equity,
    }
    return render(request, 'reports/balance_sheet.html', context)
