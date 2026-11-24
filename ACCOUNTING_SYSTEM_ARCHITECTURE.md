## Accounting System Architecture

This document summarizes the final architecture of the `accounting` app after the double-entry upgrade and API/module completion.

---

### 1. Tenancy and Isolation

- **Tenant model**: `apps.core.models.Account` (tenant) with a single `CompanyProfile` per account.
- **Company profile**: `CompanyProfile` holds business identity and default financial settings (`currency_code`, `currency_symbol`, `default_tax`).
- **Tenant scoping in accounting**:
  - All accounting models reference `CompanyProfile` via `company = ForeignKey('core.CompanyProfile', ...)`.
  - Views use `get_company_profile_for_user(request.user, request)` plus `for_user_queryset(model, user, request, account_lookup='company__account')` for per-tenant, per-user visibility.
  - Admin uses `AccountScopedAdmin` with `account_scope_lookup = 'company__account'` to enforce tenant isolation in the admin UI.

This preserves the existing multi-tenant architecture and RBAC while adding double-entry capability.

---

### 2. Core Models

#### 2.1 Existing simplified models (backwards compatible)

- `Transaction`
  - Single-row income/expense entries with tax/discount and `net_amount`.
  - Linked to `user` and `company` and synchronized into `Ledger` for monthly summaries.
- `Ledger`
  - Monthly per-company aggregation of income, expense, and net profit.
  - Stores auxiliary metrics (outstanding invoices, pending receipts) for dashboards.
- `Account`
  - Legacy chart-of-accounts–style model (`account_type` as simple `CharField`).
  - Still used by older views/forms and admin; left intact.
- `FinancialReport`
  - Stores Income Statement / Balance Sheet report metadata, JSON payload, and exported files.

These remain unchanged so existing URLs and templates continue to work.

#### 2.2 Double-entry core (new)

- `AccountCategory`
  - Groups accounts into canonical types: `asset`, `liability`, `equity`, `income`, `expense`.
  - Tenant-scoped (`company` FK) with unique code per company.

- `AccountType`
  - Optional finer classification (e.g. "Current Asset", "Bank").
  - Linked to `AccountCategory`.

- `ChartOfAccount`
  - New, explicit chart of accounts model for double-entry.
  - Fields: `company`, `code`, `name`, `category`, optional `account_type`, optional `parent`, `is_active`, timestamps.
  - Hierarchical via `parent` FK; indexed by `(company, code)`.

- `FiscalPeriod`
  - Defines fiscal year/period for reporting and posting windows.
  - Fields: `company`, `name`, `start_date`, `end_date`, `is_closed`.

- `Currency`
  - Tenant-specific currency registry for the accounting engine.
  - Fields: `company`, `code`, `symbol`, `name`, `is_default`, `is_active`.

- `AccountingTransaction`
  - Cross-app transaction header for accounting events.
  - Fields: `company`, `reference`, `source_app`, `source_id`, `amount`, `currency`, `created_at`.
  - Each business event (Invoice paid, Expense recorded, etc.) maps to one `AccountingTransaction`.

- `JournalEntry`
  - Journal header for double-entry postings.
  - Fields: `company`, `transaction` (optional `AccountingTransaction`), `reference`, `description`, `date`, `period`, `created_by`, `approved_by`, `status` (`draft`, `posted`, `void`), timestamps.
  - Exposes computed properties `total_debit`, `total_credit`, `is_balanced`.

- `JournalEntryLine`
  - Individual debit/credit lines within a `JournalEntry`.
  - Fields: `journal`, `account` (`ChartOfAccount`), `description`, `debit`, `credit`.

- `LedgerEntry`
  - General ledger line: one row per account per journal line.
  - Fields: `company`, `account`, `journal_line`, `date`, `debit`, `credit`, `balance`, `transaction` (`AccountingTransaction`), `created_at`.
  - `balance` is the running balance for that account as of the entry, using a natural-sign rule.

These models form the foundation for Trial Balance, P&L, Balance Sheet, and future Cash Flow and AP/AR modules.

---

### 3. Service Layer (`apps/accounting/services/accounting_service.py`)

The service layer centralizes double-entry logic and reporting:

- `JournalLineInput`
  - Dataclass DTO for a journal line (account, debit, credit, description).

- `create_journal_entry(company, date, description, lines, source_app, source_id, reference, created_by)`
  - Validates that total debits == total credits.
  - Creates `AccountingTransaction` header for cross-app traceability.
  - Creates `JournalEntry` and `JournalEntryLine` records for the tenant.
  - Calls `post_to_ledger(journal)` to materialize ledger entries.

- `post_to_ledger(journal)`
  - For each `JournalEntryLine`:
    - Determines the account’s natural sign (assets/expenses: debit-positive; others: credit-positive).
    - Pulls the last `LedgerEntry` for `(company, account)` to obtain the prior balance.
    - Computes new running `balance` based on `debit` and `credit`.
    - Inserts a `LedgerEntry` referencing `AccountingTransaction`.

- `calculate_trial_balance(company, start_date, end_date)`
  - Aggregates `LedgerEntry` rows by account over a date range.
  - Returns:
    - `accounts`: list of `{account_id, code, name, debit, credit, net}`.
    - `totals`: `{debit, credit}` and `balanced` flag.

- `generate_profit_loss(company, start_date, end_date)`
  - Summarizes `LedgerEntry` by `category_type` (`income`, `expense`).
  - Returns `income`, `expenses`, `net_profit`, and `period`.

- `generate_balance_sheet(company, as_of_date)`
  - For each account, obtains the latest `LedgerEntry` as of `as_of_date`.
  - Aggregates by `category_type`:
    - `assets`, `liabilities`, `equity`.
  - Returns:
    - `assets`, `liabilities`, `equity`, `total_assets`, `total_liabilities_and_equity`,
    - `equation_balanced`, and `balance_check` to detect discrepancies.

All service functions are tenant-safe (scoped by `company`) and used by the API layer and tests.

---

### 4. API Layer (`apps/accounting/api_urls.py` + JSON views)

The accounting APIs are built as Django function-based views returning `JsonResponse`, registered under `/accounting/api/`:

- **Chart of Accounts**
  - `GET /accounting/api/chart-of-accounts/` → `api_chart_of_accounts`
    - Returns list of tenant-scoped `ChartOfAccount` rows via `ChartOfAccountSerializer`.
  - `POST /accounting/api/chart-of-accounts/`
    - Creates a new `ChartOfAccount` for the current company.

- **Journal**
  - `POST /accounting/api/journal/create/` → `api_journal_create`
    - Accepts JSON payload with header info and lines, calls `create_journal_entry`.
  - `GET /accounting/api/journal/<id>/` → `api_journal_detail`
    - Returns `JournalEntry` plus `JournalEntryLine`s via `JournalEntrySerializer`.

- **Ledger / Trial Balance / P&L / Balance Sheet**
  - `GET /accounting/api/ledger/` → `api_ledger`
    - Returns `LedgerEntry` rows (filterable by `account_id`, `start_date`, `end_date`).
  - `GET /accounting/api/trial-balance/` → `api_trial_balance`
    - Returns trial balance aggregate from `calculate_trial_balance`.
  - `GET /accounting/api/profit-loss/` → `api_profit_loss`
    - Returns P&L summary from `generate_profit_loss`.
  - `GET /accounting/api/balance-sheet/` → `api_balance_sheet`
    - Returns Balance Sheet snapshot from `generate_balance_sheet`.

- **Accounts Receivable**
  - `GET /accounting/api/accounts-receivable/` → `api_accounts_receivable`
    - Aggregates unpaid/partial `Invoice.balance_due` for the tenant’s account.

- **Dashboard**
  - `GET /accounting/api/dashboard/` → `api_dashboard`
    - Mirrors `accounting_dashboard` but returns JSON only: totals, recent transactions, source breakdown, and currency info.

- **Transactions**
  - `GET /accounting/api/transactions/` → `api_transactions`
    - Returns visibility-scoped `Transaction` rows via `TransactionSerializer` with filters.

All JSON endpoints:

- Use `get_company_profile_for_user` + `for_user_queryset` for tenant and RBAC enforcement.
- Use `company_admin_or_permission_required` for permission checks.
- Return lightweight JSON suitable for AJAX/SPA-style frontends.

---

### 5. Page Views and Templates

New HTML shells were added for the required modules; each relies on the JSON APIs for data:

- **Chart of Accounts**
  - View: `accounting_chart_of_accounts_page`
  - URL: `/accounting/chart-of-accounts/`
  - Template: `templates/accounting/chart_of_accounts/list.html`
    - Uses `accounting/partials/account_table.html`.
    - Fetches and posts data via `/accounting/api/chart-of-accounts/`.

- **Journal**
  - View: `accounting_journal_page`
  - URL: `/accounting/journal/`
  - Template: `templates/accounting/journal/list.html`
    - Uses `accounting/partials/journal_rows.html`.
    - Posts journal data via `/accounting/api/journal/create/`.

- **Trial Balance**
  - View: `accounting_trial_balance_page`
  - URL: `/accounting/trial-balance/`
  - Template: `templates/accounting/reports/trial_balance.html`
    - Uses `accounting/partials/ledger_rows.html`.
    - Loads data via `/accounting/api/trial-balance/`.

- **Profit & Loss**
  - View: `accounting_profit_loss_page`
  - URL: `/accounting/profit-loss/`
  - Template: `templates/accounting/reports/profit_loss.html`
    - Uses `/accounting/api/profit-loss/`.

- **Balance Sheet**
  - View: `accounting_balance_sheet_page`
  - URL: `/accounting/balance-sheet/`
  - Template: `templates/accounting/reports/balance_sheet.html`
    - Uses `/accounting/api/balance-sheet/`.

Existing templates for dashboard, transactions, ledger summary, sync, and report generation remain intact and continue to function.

All new pages are AJAX-first: forms submit via `fetch` and update tables and metrics in-place without full page reloads.

---

### 6. Permissions and RBAC

- Views are decorated with:
  - `@login_required`
  - `@company_admin_or_permission_required('<app_label>.<perm>', raise_exception=True)`
- Permissions used include:
  - `accounting.view_transaction`, `add_transaction`, `change_transaction`, `delete_transaction`
  - `accounting.view_ledger`, `view_account`, `add_journalentry`, `view_journalentry`
- Report views (`view_report`, `export_report_pdf`) and APIs enforce:
  - Company scoping via `company` FK.
  - Per-creator isolation for non-admins: only company admins or `created_by` can view/export a given `FinancialReport`.

This keeps the double-entry engine fully aligned with existing RBAC and tenant isolation semantics.

---

### 7. Tests

File: `apps/accounting/tests/test_accounting.py`

Covered scenarios:

- **Journal entry creation and ledger posting**
  - Creates a tenant (`Account`, `CompanyProfile`), categories, and accounts (cash, revenue).
  - Uses `create_journal_entry` with balanced debit/credit lines.
  - Asserts that the journal is balanced and that `post_to_ledger` produces the expected number of `LedgerEntry` rows.

- **Trial balance and high-level reports**
  - Creates a tenant, categories, and accounts (bank, office expense).
  - Posts an expense journal.
  - Asserts:
    - Trial balance from `calculate_trial_balance` is balanced.
    - P&L from `generate_profit_loss` shows the correct expense.
    - Balance sheet from `generate_balance_sheet` satisfies the accounting equation (Assets ≈ Liabilities + Equity).

These tests validate the double-entry engine independently of the older `Transaction`/`Ledger` analytics path.

---

### 8. Integrations with Other Apps

The existing signal-based integrations remain and now have the option to be bridged into the double-entry engine:

- `apps/accounting/signals.py` listens to:
  - `Invoice` (`status=paid`) → creates `Transaction` of type `income`.
  - `Receipt` creation → creates `Transaction` of type `income`.
  - `JobOrder` approved → creates `Transaction` of type `expense`.
  - `Waybill` delivered → creates `Transaction` of type `income`.

Future work (optional) can map these `Transaction` events into `AccountingTransaction` + `JournalEntry` via the service layer, enabling full double-entry integration for:

- `invoices`, `receipts`, `inventory`, `expense`, and `tax_engine`.

---

### 9. Performance Considerations

- Core models use appropriate `Index`es (on `company`, date fields, and key identifiers) to support efficient multi-tenant queries.
- Service-layer operations work with bulk aggregates (`Sum`) and limited slices (`[:2000]` on ledger lists, `[:500]` on transaction lists) to avoid unbounded responses on large tenants.
- Legacy `Transaction.save()` ledger updates remain untouched; the new ledger engine (`LedgerEntry`) is separate and optimized for analytical queries (Trial Balance, P&L, Balance Sheet).

---

### 10. Summary

The accounting app is now structured as:

- A **backwards-compatible single-entry analytics path** (`Transaction` + monthly `Ledger` + `FinancialReport`).
- A fully-fledged **double-entry core engine** (Chart of Accounts, Journal, LedgerEntry, trial balance, P&L, Balance Sheet).
- A JSON-first **API layer** for all key operations, powering modern AJAX-based templates.
- Strong **tenant isolation** and **RBAC** via the existing multi-tenant and permission framework.

This architecture makes the accounting subsystem production-ready, extensible, and safe for multi-tenant deployments with proper financial controls.

