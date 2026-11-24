import datetime
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.core.models import Account as TenantAccount, CompanyProfile
from apps.accounting.models import (
    AccountCategory,
    ChartOfAccount,
)
from apps.accounting.services import (
    create_journal_entry,
    post_to_ledger,
    calculate_trial_balance,
    generate_profit_loss,
    generate_balance_sheet,
)


@pytest.mark.django_db
def test_journal_entry_creation_and_ledger_posting(django_user_model):
    user = django_user_model.objects.create(username="acct_test")
    tenant = TenantAccount.objects.create(owner=user, name="Test Co")
    company = CompanyProfile.objects.create(user=user, account=tenant, company_name="Test Co")

    asset_cat = AccountCategory.objects.create(
        company=company,
        code="100",
        name="Assets",
        category_type="asset",
    )
    income_cat = AccountCategory.objects.create(
        company=company,
        code="400",
        name="Income",
        category_type="income",
    )

    cash = ChartOfAccount.objects.create(
        company=company,
        code="1000",
        name="Cash",
        category=asset_cat,
    )
    revenue = ChartOfAccount.objects.create(
        company=company,
        code="4000",
        name="Sales Revenue",
        category=income_cat,
    )

    from apps.accounting.services.accounting_service import JournalLineInput

    today = timezone.now().date()
    journal = create_journal_entry(
        company=company,
        date=today,
        description="Test sale",
        lines=[
            JournalLineInput(account=cash, debit=Decimal("100.00")),
            JournalLineInput(account=revenue, credit=Decimal("100.00")),
        ],
        source_app="test",
        source_id="1",
        reference="TEST-JE-1",
        created_by=user,
    )

    assert journal.is_balanced
    ledger_entries = post_to_ledger(journal)
    assert len(ledger_entries) == 2


@pytest.mark.django_db
def test_trial_balance_and_reports(django_user_model):
    user = django_user_model.objects.create(username="acct_report")
    tenant = TenantAccount.objects.create(owner=user, name="Report Co")
    company = CompanyProfile.objects.create(user=user, account=tenant, company_name="Report Co")

    asset_cat = AccountCategory.objects.create(
        company=company,
        code="100",
        name="Assets",
        category_type="asset",
    )
    expense_cat = AccountCategory.objects.create(
        company=company,
        code="500",
        name="Expenses",
        category_type="expense",
    )

    bank = ChartOfAccount.objects.create(
        company=company,
        code="1010",
        name="Bank",
        category=asset_cat,
    )
    expense = ChartOfAccount.objects.create(
        company=company,
        code="5000",
        name="Office Expense",
        category=expense_cat,
    )

    from apps.accounting.services.accounting_service import JournalLineInput

    date = datetime.date(2026, 1, 1)
    create_journal_entry(
        company=company,
        date=date,
        description="Pay office expense",
        lines=[
            JournalLineInput(account=expense, debit=Decimal("50.00")),
            JournalLineInput(account=bank, credit=Decimal("50.00")),
        ],
        source_app="test",
        source_id="2",
        reference="TEST-JE-2",
        created_by=user,
    )

    tb = calculate_trial_balance(company=company, start_date=date, end_date=date)
    assert tb["balanced"] is True

    pl = generate_profit_loss(company=company, start_date=date, end_date=date)
    assert pl["expenses"] == 50.0

    bs = generate_balance_sheet(company=company, as_of_date=date)
    assert abs(bs["assets"] - (bs["liabilities"] + bs["equity"])) < 0.01

