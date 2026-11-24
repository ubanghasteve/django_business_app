from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence

from django.db import transaction as db_transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.models import CompanyProfile
from apps.accounting.models import (
    AccountingTransaction,
    ChartOfAccount,
    JournalEntry,
    JournalEntryLine,
    LedgerEntry,
)


@dataclass
class JournalLineInput:
    """
    Simple DTO representing a journal line to be created.

    Attributes:
        account: ChartOfAccount instance to post against.
        debit: Decimal debit amount (>= 0).
        credit: Decimal credit amount (>= 0).
        description: Optional line description.
    """

    account: ChartOfAccount
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    description: str = ""


def _normalize_amount(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@db_transaction.atomic
def create_journal_entry(
    *,
    company: CompanyProfile,
    date,
    description: str,
    lines: Sequence[JournalLineInput],
    source_app: Optional[str] = None,
    source_id: Optional[str] = None,
    reference: Optional[str] = None,
    created_by=None,
) -> JournalEntry:
    """
    Create a balanced journal entry and corresponding ledger entries.

    This function:
      1. Validates that total debits == total credits.
      2. Creates an AccountingTransaction header (optional but recommended).
      3. Creates a JournalEntry with JournalEntryLine rows.
      4. Calls post_to_ledger() to materialize LedgerEntry records.

    It is tenant-safe: all created objects are scoped to the provided company.
    """

    if not lines:
        raise ValueError("At least one journal line is required.")

    debits = sum(_normalize_amount(l.debit) for l in lines)
    credits = sum(_normalize_amount(l.credit) for l in lines)

    if debits != credits:
        raise ValueError(
            f"Journal entry is not balanced: debits={debits}, credits={credits}"
        )

    currency_code = getattr(company, "currency_symbol", "₦")

    accounting_txn = AccountingTransaction.objects.create(
        company=company,
        reference=reference or description[:100] or "Journal Entry",
        source_app=source_app or "manual",
        source_id=source_id,
        amount=debits,
        currency=currency_code,
    )

    journal = JournalEntry.objects.create(
        company=company,
        transaction=accounting_txn,
        reference=reference or f"JE-{accounting_txn.id}",
        description=description,
        date=date,
        created_by=created_by,
        status="posted",
    )

    for line in lines:
        JournalEntryLine.objects.create(
            journal=journal,
            account=line.account,
            description=line.description or description,
            debit=_normalize_amount(line.debit),
            credit=_normalize_amount(line.credit),
        )

    post_to_ledger(journal)
    return journal


def _account_natural_sign(account: ChartOfAccount) -> int:
    """
    Determine the natural sign for an account category.

    Returns +1 when a debit increases the balance (assets, expenses),
    and -1 when a credit increases the balance (liabilities, equity, income).
    """
    category_type = getattr(account.category, "category_type", None)
    if category_type in ("asset", "expense"):
        return 1
    return -1


@db_transaction.atomic
def post_to_ledger(journal: JournalEntry) -> List[LedgerEntry]:
    """
    Materialize LedgerEntry rows from a posted JournalEntry.

    For each JournalEntryLine this:
      - Looks up the last LedgerEntry for the same company+account.
      - Computes a new running balance based on natural sign.
      - Inserts a new LedgerEntry tied back to AccountingTransaction.
    """
    if journal.status != "posted":
        # Only posted entries affect the ledger
        return []

    company = journal.company
    txn = journal.transaction
    created_entries: List[LedgerEntry] = []

    for line in journal.lines.select_related("account", "journal"):
        account = line.account
        debit = _normalize_amount(line.debit)
        credit = _normalize_amount(line.credit)

        last_entry = (
            LedgerEntry.objects.filter(company=company, account=account)
            .order_by("-date", "-id")
            .first()
        )
        last_balance = last_entry.balance if last_entry else Decimal("0")

        natural_sign = _account_natural_sign(account)
        movement = natural_sign * (debit - credit)
        new_balance = last_balance + movement

        created_entries.append(
            LedgerEntry.objects.create(
                company=company,
                account=account,
                journal_line=line,
                date=journal.date,
                debit=debit,
                credit=credit,
                balance=new_balance,
                transaction=txn,
            )
        )

    return created_entries


def calculate_trial_balance(
    *,
    company: CompanyProfile,
    start_date=None,
    end_date=None,
) -> dict:
    """
    Calculate a trial balance for the given period.

    Returns a dict with:
      - accounts: list of {account, code, name, debit, credit, net}
      - totals: {debit, credit}
    """
    entries = LedgerEntry.objects.filter(company=company)
    if start_date:
        entries = entries.filter(date__gte=start_date)
    if end_date:
        entries = entries.filter(date__lte=end_date)

    aggregates = (
        entries.values("account_id", "account__code", "account__name")
        .annotate(
            debit_total=Sum("debit"),
            credit_total=Sum("credit"),
        )
        .order_by("account__code")
    )

    account_rows = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    for row in aggregates:
        debit = row["debit_total"] or Decimal("0")
        credit = row["credit_total"] or Decimal("0")
        account_rows.append(
            {
                "account_id": row["account_id"],
                "code": row["account__code"],
                "name": row["account__name"],
                "debit": float(debit),
                "credit": float(credit),
                "net": float(debit - credit),
            }
        )
        total_debit += debit
        total_credit += credit

    return {
        "accounts": account_rows,
        "totals": {
            "debit": float(total_debit),
            "credit": float(total_credit),
        },
        "balanced": total_debit == total_credit,
    }


def generate_profit_loss(
    *,
    company: CompanyProfile,
    start_date,
    end_date,
) -> dict:
    """
    Generate a Profit & Loss summary using double-entry ledger data.

    This uses LedgerEntry + ChartOfAccount.category.category_type to distinguish
    income vs expense accounts.
    """
    entries = LedgerEntry.objects.filter(
        company=company,
        date__gte=start_date,
        date__lte=end_date,
    ).select_related("account", "account__category")

    income_total = Decimal("0")
    expense_total = Decimal("0")

    for e in entries:
        category_type = getattr(e.account.category, "category_type", None)
        if category_type == "income":
            income_total += e.credit - e.debit
        elif category_type == "expense":
            expense_total += e.debit - e.credit

    net_profit = income_total - expense_total

    return {
        "income": float(income_total),
        "expenses": float(expense_total),
        "net_profit": float(net_profit),
        "period": f"{start_date} to {end_date}",
    }


def generate_balance_sheet(
    *,
    company: CompanyProfile,
    as_of_date,
) -> dict:
    """
    Generate a Balance Sheet snapshot using LedgerEntry balances as of a date.

    It aggregates account balances by category_type:
      - Assets
      - Liabilities
      - Equity

    and returns a structure suitable for JSON APIs and templates.
    """
    entries = (
        LedgerEntry.objects.filter(company=company, date__lte=as_of_date)
        .select_related("account", "account__category")
        .order_by("account__code", "date", "id")
    )

    latest_by_account = {}
    for e in entries:
        latest_by_account[e.account_id] = e

    assets = Decimal("0")
    liabilities = Decimal("0")
    equity = Decimal("0")

    for e in latest_by_account.values():
        category_type = getattr(e.account.category, "category_type", None)
        bal = e.balance
        if category_type == "asset":
            assets += bal
        elif category_type == "liability":
            liabilities += bal
        elif category_type == "equity":
            equity += bal

    total_assets = assets
    total_liabilities = liabilities
    total_equity = equity
    balance_check = total_assets - (total_liabilities + total_equity)

    return {
        "assets": float(assets),
        "liabilities": float(liabilities),
        "equity": float(equity),
        "total_assets": float(total_assets),
        "total_liabilities_and_equity": float(total_liabilities + total_equity),
        "as_of_date": as_of_date.strftime("%Y-%m-%d"),
        "equation_balanced": abs(balance_check) < Decimal("0.01"),
        "balance_check": float(balance_check),
    }

