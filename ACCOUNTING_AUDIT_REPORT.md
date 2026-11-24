## Accounting App Audit Report

Date: 2026-03-09  
Scope: Existing `apps/accounting` app (views, models, forms, urls, templates, static, signals, admin, serializers, api_urls)

---

### 1. Existing Accounting Components (High-Level)

- **Core models**
  - `Transaction`: single-row income/expense records with tax/discount and `net_amount`; linked to `user` and `core.CompanyProfile` as `company`.
  - `Ledger`: **monthly summary** per company, year, month; totals income/expense, `net_profit`, outstanding invoices, pending receipts.
  - `Account`: simple chart-of-accounts style model (asset/liability/equity/revenue/expense) with `company`, `opening_balance`, `current_balance`.
  - `FinancialReport`: stores generated reports as JSON with PDF/Excel attachments, linked to `company` and `created_by`.

- **Views**
  - `accounting_dashboard`: HTML dashboard with charts, summary cards, and AJAX-driven refresh via `update_ledger_ajax`.
  - `transaction_list`: paginated list with filtering, exports (CSV/Excel/PDF), and some JS enhancements (not fully SPA/AJAX).
  - CRUD and state:
    - `add_transaction`, `edit_transaction`, `delete_transaction` (void), `reconcile_transaction`, `unreconcile_transaction`.
  - Reporting and export:
    - `ledger_summary`, `export_accounting_data`, `generate_report`, `view_report`, `export_report_pdf`.
  - Integrations/sync:
    - `sync_from_other_apps`, helpers `sync_ledgers_from_transactions`, `update_transactions_currency`, `update_accounting_currency`, `update_ledger_ajax`.

- **Forms**
  - `TransactionForm`, `TransactionFilterForm`, `AccountForm`, `FinancialReportForm`,
    `BulkTransactionForm`, `ReconciliationForm`, `ImportTransactionForm`.

- **URLs**
  - `urls.py`: HTML views under `/accounting/…` (dashboard, transactions, ledger, export, reports, sync, AJAX).
  - `api_urls.py`: DRF router present but **no registered viewsets or endpoints**.

- **Admin**
  - Account-scoped `ModelAdmin` for `Transaction`, `Ledger`, `Account`, `FinancialReport`, using `AccountScopedAdmin` with `company__account` scoping.

- **Signals & Integrations**
  - `signals.py`:
    - `Invoice` (paid) → creates `Transaction` (income).
    - `Receipt` (created) → creates `Transaction` (income).
    - `JobOrder` (approved) → creates `Transaction` (expense).
    - `Waybill` (delivered) → creates `Transaction` (income).
    - `post_delete(Transaction)` → recalculates `Ledger` for that month.
  - Commented-out integration for an `Expense` model (not currently active).

- **Templates**
  - `dashboard.html`, `transactions.html`, `transaction_form.html`, `transaction_confirm_delete.html`,
    `ledger_summary.html`, `generate_report.html`, `view_report.html`, `sync_from_other_apps.html`.
  - All are Bootstrap-based, support *some* AJAX (dashboard charts, partial actions in transactions).

- **Static**
  - `static/accounting/js/accounting.js`: rich client utilities for validation, calculations, "auto-refresh" of dashboard (non-DRF, HTML/JSON hybrid).
  - `static/accounting/css/accounting.css`: modern UI styling for dashboard, transactions, forms, ledger, etc.

- **Serializers & API**
  - `serializers.py`: only a comment placeholder; **no serializers implemented**.
  - `api_urls.py`: DRF router instantiated but **no viewsets or paths registered**.

---

### 2. Missing Required Accounting Models / Engine (Double-Entry)

Per the specification, the system must be **double-entry** with these models:

- `ChartOfAccount`
- `AccountCategory`
- `AccountType`
- `JournalEntry`
- `JournalEntryLine`
- `LedgerEntry`
- `AccountingTransaction`
- `FiscalPeriod`
- `Currency`

**Current state:**

- Only partial equivalents:
  - `Account` partially overlaps with `ChartOfAccount` but:
    - Has no explicit category or type model (`account_type` is a `CharField`).
    - No parent/child hierarchy or code structure.
  - `Ledger` is an **aggregate monthly summary**, not a per-transaction ledger line.
  - `Transaction` is a **single-row**, non-double-entry record (stores income vs expense flag, not debits/credits).
  - There are no journal/ledger line models (`JournalEntry`, `JournalEntryLine`, `LedgerEntry`) and no transactional `AccountingTransaction` as a cross-app anchor.
  - There is no `FiscalPeriod` model; periods are implied via dates and `Ledger`’s `year`+`month`.
  - There is no dedicated `Currency` model; `Transaction.currency` and `CompanyProfile.currency_code/symbol` are strings.

**Conclusion:**  
The current implementation is **single-entry / summarized** and **does not implement required double-entry accounting** logic or models. All requested engine models will need to be introduced alongside, not replacing, the existing simplified models.

---

### 3. Broken / Missing Endpoints and URL Structure

**Existing HTML routes (`urls.py`):**

- `''` → `accounting_dashboard` (name `dashboard`)
- `transactions/`, `transactions/add/`, `<uuid>/edit/`, `<uuid>/delete/`, `<uuid>/reconcile/`, `<uuid>/unreconcile/`, `transactions/update_currencies/`
- `ledger/` → `ledger_summary`
- `export/` → `export_accounting_data`
- `reports/generate/`, `reports/<int:report_id>/`, `reports/<int:report_id>/export-pdf/`
- `sync/` → `sync_from_other_apps`
- `ajax/update-ledger/`, `ajax/update-currency/`

**Required URL structure (spec) – deficiencies:**

- **Dashboard**
  - Required: `path('', dashboard_view, name='accounting_dashboard')`
  - Current: `name='dashboard'` instead of `accounting_dashboard`. Functionally OK but naming inconsistent with spec.

- **Page-level routes**
  - Required:
    - `chart-of-accounts/`
    - `journal/`
    - `ledger/`
    - `trial-balance/`
    - `profit-loss/`
    - `balance-sheet/`
  - Current:
    - Only `ledger/` exists (as summary).
    - **No dedicated views/pages** for:
      - Chart of Accounts management.
      - Journal entries.
      - Trial balance.
      - Profit & Loss (although income statement logic exists in services/report views).
      - Balance Sheet page (only generated via `view_report`).

- **API endpoints**
  - Required examples:
    - `/accounting/api/chart-of-accounts/`
    - `/accounting/api/journal/create/`
    - `/accounting/api/journal/<id>/`
    - `/accounting/api/ledger/`
    - `/accounting/api/trial-balance/`
    - `/accounting/api/profit-loss/`
    - `/accounting/api/balance-sheet/`
    - `/accounting/api/accounts-payable/`
    - `/accounting/api/accounts-receivable/`
    - `/accounting/api/dashboard/`
    - `/accounting/api/transactions/`
  - Current:
    - No DRF viewsets, no API serializers, no `/api/...` `path()` declarations.
    - Only "AJAX" endpoints are:
      - `ajax/update-ledger/` (JSON)
      - `ajax/update-currency/` (JSON)
      - Reconcile/unreconcile and update-currencies in `transactions.html` (they call `/accounting/transactions/...` and expect JSON, but underlying views sometimes assume HTML redirects; not fully API-ized).

**Conclusion:**  
The project currently lacks a **proper REST/AJAX API surface** for the accounting engine. Required `/api/...` endpoints are missing and must be added without disrupting existing HTML views.

---

### 4. Templates: Missing vs Spec

**Existing templates:**

- `dashboard.html`
- `transactions.html`
- `transaction_form.html`
- `transaction_confirm_delete.html`
- `ledger_summary.html`
- `generate_report.html`
- `view_report.html`
- `sync_from_other_apps.html`

**Required template structure (spec):**

- `templates/accounting/dashboard.html` ✅ (exists, rich charts/AJAX)
- `templates/accounting/chart_of_accounts/`
  - `list.html`
  - `create.html`
  - `edit.html`
- `templates/accounting/journal/`
  - `list.html`
  - `create.html`
  - `view.html`
- `templates/accounting/ledger/ledger.html`
- `templates/accounting/reports/`
  - `trial_balance.html`
  - `profit_loss.html`
  - `balance_sheet.html`
  - `cash_flow.html`
- `templates/accounting/partials/`
  - `account_table.html`
  - `journal_rows.html`
  - `ledger_rows.html`

**Findings:**

- **Missing directories and templates**:
  - No `chart_of_accounts/`, `journal/`, `ledger/ledger.html`, `reports/` sub-templates, or `partials/` as specified.
  - Current ledger and report UIs are embedded in `ledger_summary.html`, `view_report.html`, `generate_report.html` rather than using reusable partials.
- **AJAX support**
  - `dashboard.html` uses strong AJAX/Chart.js patterns and JSON endpoint (`update_ledger_ajax`).
  - `transactions.html` uses some fetch-based actions (reconcile/unreconcile, update currencies) but **relies heavily on full-page reloads** for filtering, pagination, and CRUD; not yet a full AJAX/single-page module.
  - No existing templates specifically built to be refreshed via partial HTML snippets or dedicated `/api/...` JSON endpoints for the new modules (Chart of Accounts, Journal, Trial Balance, P&L, Balance Sheet, Cash Flow).

---

### 5. Financial Logic Review

**Transaction & Ledger calculations**

- `Transaction.save()`:
  - Derives `tax` and `discount` from `tax_type` / `tax_value` and `discount_type` / `discount_value`.
  - Computes `net_amount = amount + tax - discount`.
  - Calls `update_ledger()` **on every save**.
- `Transaction.update_ledger()`:
  - Uses `Ledger.objects.get_or_create(company, year, month)` then recalculates monthly `total_income`, `total_expense`, `net_profit` from all non-void transactions for that month.
  - Ignores `is_deleted` flag (filter only `is_void=False`), although other parts treat `is_deleted` as soft-delete.

**Ledger and dashboard**

- `Ledger.update_outstanding_amounts()` pulls outstanding invoices and sets `pending_receipts` (currently always 0).
- `accounting_dashboard`:
  - Uses `for_user_queryset(Transaction, ...)` to apply per-user visibility.
  - Builds last-12-month metrics from either `Ledger` or direct transaction aggregates.
  - Recomputes fallback "today" income/expense from last few transactions if there are no same-day records.

**Reporting services**

- `generate_income_statement(company, start_date, end_date, request=None)`:
  - Segregates `income` and `expense` by `Transaction.type`.
  - Takes net amounts (after tax/discount) and returns `income`, `expenses`, `net_income`.
  - Respects `for_user_queryset` if `request` is provided and user is not company admin.

- `generate_balance_sheet(company, as_of_date, request=None)`:
  - Totals `income` and `expense` to compute `retained_earnings`.
  - Computes:
    - `cash = retained_earnings`
    - `accounts_receivable` from `Invoice` balances (either account-scoped or company-wide).
    - `total_assets = cash + accounts_receivable`.
    - `accounts_payable` hard-coded as `0` (no AP integration).
    - `total_liabilities = accounts_payable`.
    - `owner_equity` back-calculated to satisfy the accounting equation; adjusted if negative.
  - Returns detailed breakdown and a `balance_check` to detect equation drift.

**Issues / Limitations:**

- **Single-entry, not double-entry**:
  - No clear Debit/Credit per account; `Transaction.type` is a coarse income/expense indicator.
  - No per-account postings or running balances at ledger line level.

- **Ledger summarization**:
  - Ledger is monthly aggregated, not a general ledger. Impossible to drill down per account or to support canonical double-entry reports (GL, TB) directly.

- **AP/AR modeling**:
  - AR is implicitly modeled via `Invoice.balance_due`; AP is not modeled.
  - `accounts_payable = 0` is a placeholder, so liabilities are underreported; Balance Sheet is incomplete.

- **Cash flow**:
  - No dedicated cash flow logic or model beyond the combined effects of `Transaction` records.

- **Soft delete handling**:
  - Some parts filter `is_deleted=False` (e.g. `sync_ledgers_from_transactions`, `update_ledger_ajax`, reporting).
  - `Transaction.update_ledger()` and `post_delete` ledger recalculation ignore `is_deleted`, potentially including soft-deleted records until they are hard-deleted.

**Conclusion:**  
Current financial logic is reasonably robust for a **lightweight, single-entry analytics layer** but **does not satisfy rigorous double-entry accounting requirements** (per-account debits/credits, GL, TB, P&L, BS derived strictly from postings).

---

### 6. AJAX / API Behavior and Gaps

- **Implemented JSON/AJAX endpoints**
  - `update_ledger_ajax`:
    - POST body JSON (`month`, `year`, `include_charts`).
    - Returns JSON with totals, charts, source breakdown, recent transactions.
    - Well-scoped to `for_user_queryset` and `company`.
  - `update_accounting_currency`, `update_transaction_currencies`:
    - POST JSON/CSRF, update company and transaction currencies, return JSON.
  - `reconcile_transaction` / `unreconcile_transaction`:
    - Decorated with `@require_POST` and `@csrf_exempt`, return `JsonResponse`.
    - Called via `fetch` in `transactions.html`.

- **Non-AJAX or partially-AJAX operations**
  - `add_transaction`, `edit_transaction`, `delete_transaction`:
    - standard Django form posts, full-page redirects on success.
    - templates and `static/accounting/js/accounting.js` suggest some offline/queueing hooks, but the backend views return HTML, not consistent JSON.
  - Filtering, pagination, exports in `transactions.html`:
    - Performed via GET navigation (non-AJAX), though there is JS to show loading states.

- **Required AJAX standard (spec)**
  - All forms should submit via AJAX to JSON endpoints without page reloads (e.g. `/accounting/api/journal/create/` etc.).
  - Frontend JS should consume JSON responses and update tables/partials incrementally.

**Conclusion:**  
Some strong infrastructure for AJAX/JSON exists, particularly on the dashboard and for currency/reconciliation, but the system **does not yet conform to an API-first, AJAX-only pattern** for all accounting operations. Additional DRF and JSON views will be needed and wired into existing front-end flows.

---

### 7. Validations and Data Integrity

- **TransactionForm**
  - Cleans `amount`, `tax`, `discount` robustly:
    - Strips currency symbols and commas.
    - Auto-detects percentage forms (`"5%"`) and sets type accordingly.
    - Rejects non-positive `amount`.
  - Uses `user.company_profile.currency_code` as default currency when available.

- **TransactionFilterForm**
  - Supports date range, type, source, amount range, search text, reconciled status.
  - `created_by` `ModelChoiceField` is admin-only; queryset is correctly set in view using company/team-scoped helper.

- **AccountForm**
  - Enforces uniqueness of `account_number` at form level (on top of model uniqueness).

- **FinancialReportForm**
  - Validates that `start_date` ≤ `end_date`.

- **ImportTransactionForm**
  - Validates file extension and max size; supports multiple date formats.

**Gaps:**

- **No explicit validation** that:
  - Transactions align with a Chart of Accounts or account posting requirements (because double-entry is missing).
  - Cross-app sync (Invoice/Receipt/JobOrder/Waybill) results obey business rules like idempotency under concurrent saves (currently uses a naive "if not existing transaction" condition).
  - Fiscal periods (once introduced) are open/closed before posting.

---

### 8. Permissions, RBAC, and Tenant Isolation

**RBAC and permissions**

- Views use:
  - `@login_required`
  - `@company_admin_or_permission_required('accounting.view_transaction' / 'add_transaction' / 'change_transaction' / 'delete_transaction', raise_exception=True)`
  - This integrates with central `apps.core.permissions`.
- Reporting:
  - `view_report` and `export_report_pdf`:
    - Enforce **per-creator** visibility for non-admins:
      - Non-admins can only see/export `FinancialReport` where `created_by == request.user`.
- Admin:
  - Uses `AccountScopedAdmin` with `account_scope_lookup = 'company__account'` and overrides foreign-key querysets to restrict `company` and `user` fields to the current account.

**Tenant / data isolation**

- The global architecture uses **`CompanyProfile` + `account`** as the tenant concept.
  - `Transaction.company = ForeignKey('core.CompanyProfile', …)`.
  - Most queries scope by:
    - `company = get_company_profile_for_user(user, request)`, or
    - `for_user_queryset(Model, request.user, request, account_lookup='company__account')`.
- Examples:
  - `accounting_dashboard`, `transaction_list`, `ledger_summary`, `generate_report`, `view_report`, `export_accounting_data` all:
    - Resolve `company` via `get_company_profile_for_user`.
    - Use `for_user_queryset` for per-account/per-user visibility where appropriate.

**Risks vs explicit requirement**

- The specification requires **explicit `tenant = ForeignKey(Tenant, …)` on every model and `.filter(tenant=request.user.tenant)` on every query**.
  - Current accounting models **do not have a `tenant` field**; instead they use `company` linked to `account`.
  - `for_user_queryset` and `AccountScopedAdmin` likely enforce tenant isolation centrally, but this is architectural, not per-model `tenant` FK as described.
- Some queries in signals and helpers:
  - `sync_invoice_to_accounting`, `sync_receipt_to_accounting`, `sync_job_order_to_accounting`, `sync_waybill_to_accounting`:
    - Use `get_company_profile_for_user(instance.user or created_by)` which should map correctly to the user’s company/tenant.
    - They do **not** explicitly guard against cross-tenant injection via misconfigured relationships, but are consistent with central utils.
  - `Ledger.update_outstanding_amounts()`:
    - Uses `Invoice.objects.filter(user=self.company.user, …)` which couples invoices to `company.user` instead of using `account_id`; this may be brittle for multi-user accounts.

**Conclusion:**  
RBAC integration is **strong and consistent**. Tenant isolation is enforced via `CompanyProfile` + `account` and central utilities rather than explicit `tenant` FKs and filters as specified. There is a **design mismatch** with the requested explicit-tenant pattern and a few queries that could leak / mis-scope if `CompanyProfile`–`user` relationships are misaligned.

---

### 9. Missing Required Modules / Features (Per Spec)

The following modules are explicitly required but either missing or only partially present:

- **Dashboard**  
  - ✅ Implemented and rich (charts, cards, AJAX, source breakdown).

- **Chart of Accounts**
  - `Account` model and `AccountForm` exist, but:
    - No dedicated views or pages for:
      - listing accounts,
      - creating/editing accounts,
      - managing hierarchy or codes.
    - No AJAX endpoints or templates (`chart_of_accounts/list.html`, etc.).

- **Journal Entries**
  - ❌ No `JournalEntry` / `JournalEntryLine` models.
  - ❌ No views, forms, or templates for journal entry creation/listing.

- **General Ledger**
  - `Ledger` provides monthly summary by company, not a GL by account.
  - ❌ No per-account ledger lines or drill-down ledger screens.

- **Trial Balance**
  - ❌ No model, service, or template for trial balance.

- **Profit & Loss**
  - `generate_income_statement` + reporting views/HTML provide **basic P&L**.
  - ❌ No dedicated module page or `/api/trial-balance`/`/api/profit-loss` endpoints; UI integrated into generic reporting instead.

- **Balance Sheet**
  - `generate_balance_sheet` + `view_report` implement **balance sheet logic**.
  - ❌ No standalone balance-sheet page with filters/AJAX; only via generated `FinancialReport`.

- **Cash Flow**
  - ❌ No dedicated Cash Flow report or model/service.

- **Accounts Payable**
  - ❌ Not implemented (AP = 0 in balance sheet).

- **Accounts Receivable**
  - ✅ Partially implemented via `Invoice.balance_due` as AR in balance sheet.
  - ❌ No dedicated AR module UI or API endpoints.

- **Tax Summary**
  - ❌ No dedicated tax summary module; taxes are stored on `Transaction` but not summarized by tax type/period.

- **Bank Accounts**
  - ❌ No bank account model or reconciliation module beyond `ReconciliationForm` placeholder.

- **Payments**
  - Payments are implied via `Receipt` and `Invoice` integration, but:
    - ❌ No dedicated payments module or double-entry postings interface.

- **Expenses**
  - Partial via `Transaction` type `expense` and JobOrder sync.
  - Commented-out integration with an `Expense` model; no active expense app integration in accounting.

- **Financial Reports**
  - ✅ `FinancialReport` model and basic Income Statement / Balance Sheet generation exist.
  - ❌ No dedicated Trial Balance, Cash Flow, or tax reports.

---

### 10. Performance Considerations

Positive aspects:

- `Transaction` and `Ledger` define multiple `Index`es for common fields (`user`, `type`, `company`, `transaction_date`, `source_app`, etc.).
- Views that operate on larger querysets use:
  - `select_related('created_by')` in `transaction_list`.
  - `select_related('company', 'user')` or `select_related('company')` in admin.
  - `Paginator` for transaction list.

Potential issues / improvements:

- `Transaction.save()`:
  - Recomputes monthly ledger by re-aggregating **all** transactions for the month every time a transaction is saved. This can be heavy for tenants with many transactions; might require optimization or moving to background tasks.
- Signals:
  - `post_save` signals on `Invoice`, `Receipt`, `JobOrder`, `Waybill` do `Transaction.objects.filter(...).first()` per event; acceptable, but may need indexing (some indexes exist) and idempotent patterns.
- Reporting:
  - Income Statement / Balance Sheet recompute aggregates on each call; acceptable but may benefit from caching for large tenants.
- Trial balance / GL (once implemented) will need careful use of `select_related`, `prefetch_related`, and indexes on `journal`, `account`, `date` to avoid bottlenecks.

---

### 11. Security Review

Strengths:

- Views are protected with `@login_required` and strong permission decorators (`company_admin_or_permission_required`).
- Export endpoints and report generation use company-scoped filters and per-creator restrictions.
- AJAX JSON endpoints check company existence and user ownership via `get_company_profile_for_user` and `for_user_queryset`.
- Delete/void and reconciliation are POST-only and CSRF-aware (manually or via `@csrf_exempt` plus explicit header).

Weaknesses / risks:

- Some AJAX endpoints are marked `@csrf_exempt` and rely solely on manual CSRF headers (acceptable but increases risk if front-end is misconfigured).
- URL-level patterns for some AJAX operations (e.g. `/accounting/transactions/<id>/reconcile/`) do not include explicit tenant id; security relies entirely on `for_user_queryset` and `get_object_or_unauthorized` (which is appropriate but increases importance of those helpers being correct).
- The lack of explicit `tenant` fields may make static code analysis for isolation harder; isolation is expressed implicitly via account/company relationships.

---

### 12. Summary of Key Gaps to Address in Next Phases

1. **Double-entry core missing**  
   - Need to introduce `ChartOfAccount`, `AccountCategory`, `AccountType`, `JournalEntry`, `JournalEntryLine`, `LedgerEntry`, `AccountingTransaction`, `FiscalPeriod`, `Currency` models and services while preserving existing `Transaction`/`Ledger` for backward compatibility.

2. **API surface insufficient**  
   - Need DRF serializers and viewsets / function-based JSON views for all required `/accounting/api/...` endpoints (chart of accounts, journal, ledger, trial balance, P&L, balance sheet, AP/AR, dashboard, transactions).

3. **Modules incomplete or absent**  
   - Chart of Accounts UI, Journal UI, General Ledger, Trial Balance, Cash Flow, Accounts Payable, Tax Summary, Bank Accounts, Payments, and richer Expenses integration are missing.

4. **Templates and AJAX pages incomplete**  
   - Need to add the specified template structure (`chart_of_accounts/`, `journal/`, `reports/`, `partials/`) with AJAX-based listing/filters/pagination/search for all modules.

5. **Tenant isolation design mismatch**  
   - Current design uses `CompanyProfile` + `account` instead of explicit `tenant` FK; new models and queries must be carefully designed to respect and integrate with the existing multi-tenant pattern without regression.

6. **Report engine only partially aligned with spec**  
   - Income Statement and Balance Sheet are present but require alignment with double-entry postings; Trial Balance and Cash Flow need to be added.

7. **Performance & scalability**  
   - Need to avoid N^2 aggregations (e.g., in `Transaction.save()` ledger recomputation) once data volume grows, especially after adding more detailed ledger lines.

This audit completes **Phase 1**. Subsequent phases will:

- Introduce the double-entry core engine models and services alongside existing models.
- Build the requested API endpoints and templates.
- Ensure robust tenant isolation and RBAC for new functionality.
- Add tests (`tests/test_accounting.py`) to verify journal entry creation, ledger posting, trial balance, and report accuracy.

