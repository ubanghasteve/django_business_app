# Multi-Tenant Business App – Full Architecture & Replication Documentation

This document is the **single source of truth** for multi-company tenancy, RBAC, permissions, data isolation, routing, modules, APIs, and production invariants.

**It is intentionally stack-agnostic.** Concepts map to any backend (Django, NestJS, Laravel, Rails, ASP.NET, Spring, Go, etc.). Where this repository’s current implementation uses a specific framework, that is noted only as a *reference implementation*, not a requirement.

**Nothing listed here should be skipped** when replicating the system on another technology.

---

## How to read this document

| Term in this doc | Meaning (any stack) | Example names in other stacks |
|------------------|---------------------|-------------------------------|
| **Tenant / Account** | The company boundary; all data and roles belong to one Account | `organizations`, `tenants`, `workspaces`, `companies` |
| **Company Profile** | Presentation/settings for one Account (logo, currency, address) | `company_settings`, `organization_profile` |
| **User** | Login identity; always belongs to exactly one Account | `users` with `account_id` / `tenant_id` |
| **Team Member (SubUser)** | Invited staff under an Account; own email/password; shares the company’s data space | `memberships`, `invites`, `staff_users` |
| **Linked User** | The real auth User behind a Team Member (so permission checks work the same way) | `membership.user_id` |
| **Role (AccountGroup)** | Named permission set **scoped to one Account** | `roles` with unique `(account_id, name)` |
| **Permission** | Atomic capability string `module.action_resource` | `invoices.view_invoice`, CASL abilities, policies |
| **Company Admin** | Account owner acting as themselves (not as a team member session) | `is_owner`, `org_admin` |
| **Request company context** | Resolved once per request: current Company Profile for the logged-in actor | middleware / interceptor / guard |
| **Visibility filter** | Second layer after tenant filter: admin/full-visibility vs `created_by = me` | repository scope, RLS policies, query middleware |
| **Full company visibility** | Role flag: see all rows in the Account (visibility only, not extra authority) | `roles.see_all_records` |
| **Elevated permissions** | Any business-module permission that proves “full product access” | used for approval / unlock gate |
| **Profile-only access** | Unapproved or non-elevated Account: only auth + company profile + dashboard shell | feature flag / middleware gate |

---

# PART A — Architecture blueprint (replicate on any stack)

## A1. Architecture overview (mental model)

```
Platform super-admin approves Account.is_approved
        ↓
Owner → Company Admin role (all permissions) + sees ALL rows for that Account
        ↓
Account ──1:1── CompanyProfile   (= request.company / currentCompany)
   │
   ├── User (owner + each team member’s linked user)
   │         every User.account_id = THIS Account
   ├── Role ──M2M── Permissions
   │         unique (account_id, role_name)
   │         never shared across Accounts
   └── TeamMember ──owned_by── Owner User
                  ──linked_user── User
                  session flag: acting_as_team_member_id
        ↓
Business rows: account_id and/or company_id + created_by_id
        ↓
Layer 1 TENANT:    WHERE account_id = current_account
Layer 2 VISIBILITY:
        - Company Admin            → all rows in tenant
        - full_company_visibility  → all rows in tenant (read visibility)
        - otherwise                → created_by_id = current_user
        - model without created_by → non-admin sees EMPTY (safe default)
```

### Product rules (non-negotiable)

| # | Rule |
|---|------|
| 1 | One User belongs to **exactly one** Account (no multi-company switcher in this design). |
| 2 | Company A and Company B are separate Accounts. They never share roles, teams, or business records. |
| 3 | Roles are always `(account_id, role_name)` unique. Role “Manager” in A ≠ “Manager” in B. |
| 4 | Team members are always queried under `account_owner.account_id = current account`. |
| 5 | Every list, detail-by-id, report, export, and API must apply tenant + visibility filters (prevents IDOR). |
| 6 | Authorization uses **permission codes**, never role **names**. |
| 7 | UI hiding is not security; every mutating endpoint re-checks permissions server-side. |

### Isolation strategy chosen

**Shared database, row-level tenancy** (not schema-per-tenant, not DB-per-tenant).

- Cheaper and simpler to operate.
- Requires absolute discipline: one isolation helper used everywhere.
- Optional hardening on other stacks: PostgreSQL RLS with `SET app.current_account_id`, or equivalent.

---

## A2. Development process (start → production)

Build in this order on **any** stack.

### Step 1 — Tenant identity

1. Create `accounts` table: `id`, `owner_user_id`, `name`, `is_active`, `is_approved` (default false), timestamps.
2. Create `company_profiles` table: 1:1 with `accounts`; branding, currency, address, logo, signature, theme colors.
3. Create `users` table: email unique, password hash, profile fields, **`account_id` required**.
4. On registration: create User → create Account (owner = user) → link `user.account_id` → assign default locked-down role.

### Step 2 — Approval / unlock gate (SaaS onboarding)

1. New Accounts start `is_approved = false`.
2. Middleware/interceptor: if Account does **not** have “full access”, allow only:
   - auth routes (`/auth/*`)
   - dashboard / company profile / bank accounts (`/dashboard/*`)
   - static/media/admin (platform)
   - **403** all business modules
3. Define `account_has_full_access(account)`:
   - `is_approved == true` AND
   - owner has at least one **elevated** (business) permission
4. When platform super-admin sets `is_approved = true`:
   - ensure **Company Admin** role exists for that Account
   - grant it **all** permission codes in the system
   - assign owner to Company Admin
   - clear any permission caches

### Step 3 — RBAC (roles are never global)

1. Maintain a catalog of permissions: `module.action_resource` (e.g. `invoices.view_invoice`, `invoices.print_invoice`).
2. Table `roles`: `account_id`, `role_name`, `full_company_visibility`, unique `(account_id, role_name)`.
3. Table `role_permissions`: role ↔ permission.
4. Table `user_roles`: user ↔ role; **enforce** `user.account_id == role.account_id` on every write (DB trigger or app invariant + unit tests).
5. Optional: store a globally unique role key like `acct-{account_id}:{role_name}` if your auth library requires unique group names.

### Step 4 — Team members

1. Table `team_members`: `account_owner_user_id`, `linked_user_id`, email, full_name, password_hash, is_active.
2. On create: create/sync `linked_user` with **same `account_id` as owner**; assign chosen role.
3. Login: authenticate User **or** TeamMember credentials; if TeamMember, return/session the `linked_user` and set `session.acting_as_team_member_id`.
4. Company context for team members always resolves to the **owner’s** Company Profile (same logo/currency).

### Step 5 — Two-layer data isolation (mandatory)

1. Every business table: `account_id` and/or `company_id` + `created_by_id`.
2. Central function `records_visible_to(user, request, Model)`:
   - filter by tenant
   - then apply visibility rules (admin / full visibility / own rows)
3. Wire **every** list, get-by-id, update, delete, report, export, admin panel, and API through it.
4. On create: set `account_id` from `user.account_id` (or company→account) and `created_by_id` from current actor.

### Step 6 — Privilege escalation boundaries

1. When creating/editing a role, a non-superuser may only attach permissions **they already have**.
2. Never allow non-superusers to assign “manage permissions / manage roles catalog” meta-permissions (would allow self-escalation).
3. When assigning a role to a user, ensure that role’s permissions ⊆ assigner’s permissions (except approved Account owner / platform super-admin).
4. After any role/permission change: invalidate permission caches for affected users.

### Step 7 — Navigation + UI context

1. Map each nav item → required view permission(s).
2. Inject request-wide context: current company, is_company_admin, can_manage_users, is_read_only, show_created_by column, CTAs for “request full access”.
3. Role UI shows human labels for permissions; **never rename** stored permission codes.

### Step 8 — Production hardening checklist

- [ ] Detail-by-id uses same tenant+visibility filter (no `find(id)` alone).
- [ ] Cross-tenant role assignment throws / 403.
- [ ] Company A cannot read Company B’s records with guessed IDs.
- [ ] Team member without `full_company_visibility` cannot see coworker rows.
- [ ] Removing a team member clears their role memberships.
- [ ] New modules’ permissions auto-sync onto Company Admin (migration hook / job).
- [ ] Audit log rows store `account_id`.
- [ ] Document numbers / unique business keys scoped per company where needed.

---

## A3. Data model (generic schema)

### A3.1 `accounts` (Tenant)

| Field | Type | Notes |
|-------|------|-------|
| id | PK | Tenant id |
| owner_user_id | FK → users, nullable on delete SET NULL | Company Admin identity |
| name | string | Display name |
| is_active | bool | Soft disable |
| is_approved | bool default false | Gates full product access |
| created_at / updated_at | datetime | |

### A3.2 `company_profiles`

| Field | Type | Notes |
|-------|------|-------|
| id | PK | |
| account_id | FK → accounts, unique | One profile per tenant |
| user_id | FK → users, unique | Legacy/owner link |
| company_name, email, phone, website | | |
| address_line_1/2, city, state, postal_code, country | | |
| business_type, tax_id, registration_number | | |
| currency_code, currency_symbol, default_tax | | |
| logo, signature | file | |
| show_bank_details, show_signature | bool | |
| primary_color, secondary_color, accent_color, text_color | | Theme |
| created_at / updated_at | | |

### A3.3 `bank_accounts`

| Field | Notes |
|-------|-------|
| company_id | FK → company_profiles |
| bank_name, account_name, account_number, account_type | |
| routing_number, swift_code, iban | optional |
| is_default, is_active | only one default per company (enforce on save) |
| **unique** | `(company_id, account_number)` |

### A3.4 `users`

| Field | Notes |
|-------|-------|
| email | unique; login identifier |
| password_hash | |
| account_id | FK → accounts (**required** for normal users) |
| first_name, last_name, phone, profile fields | |
| is_active, is_platform_staff, is_superuser | platform flags ≠ tenant roles |
| force_password_change | e.g. HR-created portal accounts |
| date_joined | |

### A3.5 `team_members` (SubUser)

| Field | Notes |
|-------|-------|
| account_owner_user_id | FK → users (the Account owner) |
| linked_user_id | unique FK → users (RBAC identity) |
| email | unique login |
| full_name | |
| password_hash | |
| is_active | |
| is_staff | **legacy only**; do not use for authorization |

### A3.6 `roles` (AccountGroup)

| Field | Notes |
|-------|-------|
| account_id | FK → accounts |
| role_name | human name within account |
| full_company_visibility | bool: see all company rows |
| **unique** | `(account_id, role_name)` |

### A3.7 `permissions` (catalog)

| Field | Notes |
|-------|-------|
| code | e.g. `invoices.view_invoice` (stable; never rename) |
| module | for UI grouping |
| label | human-readable for Role Create/Edit UI |

Standard pattern per resource: `view_`, `add_`, `change_`, `delete_`, plus custom `print_`, `download_`, `can_approve_*`, dashboard perms, etc.

### A3.8 `role_permissions` / `user_roles`

- M2M role ↔ permission  
- M2M user ↔ role  
- Invariant on assign: `user.account_id == role.account_id`

### A3.9 `user_sessions` / `user_activities` (security)

- Session: user, optional team_member, device, IP, geo, login/logout, is_active  
- Activity: **account_id**, user, team_member, type (LOGIN, CREATE, UPDATE, DELETE, PERMISSION_CHANGE, …), object refs, changes JSON, deleted_data JSON  

### A3.10 Business entity pattern (every module)

```text
id
account_id          # and/or company_id → company_profiles → accounts
created_by_id       # FK users — required for team-member row isolation
...domain fields...
created_at / updated_at

Indexes: (account_id, created_at DESC), (account_id, created_by_id), ...
```

On save if missing: set `account_id` from actor’s account; set `created_by_id` from actor.

---

## A4. Request pipeline (middleware / interceptors)

Implement as middleware, Nest guards/interceptors, Laravel middleware, Rails around_action, ASP.NET middleware, etc. **Order matters.**

| Order | Concern | Behavior |
|-------|---------|----------|
| 1 | Canonical host (dev) | Optional: unify localhost vs 127.0.0.1 for cookies |
| 2 | Compression / CORS / security headers | Standard |
| 3 | Session | Cookie/JWT session establishment |
| 4 | CSRF (cookie sessions) | If using cookie auth for browsers |
| 5 | Authentication | Resolve current User |
| 6 | Session invalidation | If session row force-deleted → logout + redirect login `?reason=admin_logout` |
| 7 | **Company context** | `request.company = resolveCompanyProfile(user, session)` |
| 8 | **Account approval gate** | If not full access → allowlist paths only; else 403 |
| 9 | Messages / flash | Optional |
| 10 | Permission audit logging | Log 403s; optionally log grants on sensitive paths |
| 11 | Cache-control for dynamic lists | no-store for mutating business UIs |
| 12 | Activity tracking | Audit significant actions |

### Company context resolution (SSOT)

```pseudo
resolveCompanyProfile(user, request):
  if not authenticated: return null
  // 1. Owner direct profile
  if user.company_profile: return it
  // 2. Via account (works for owners AND team linked users)
  if user.account.company_profile: return it
  if user.account.owner.company_profile: return it  // legacy
  // 3. Via session team_member_id → owner.account.company_profile
  return null only if account truly has no profile
```

### Approval allowlist (profile-only Accounts)

Allowed prefixes when `account_has_full_access` is false:

- `/admin/` (platform)
- `/auth/`
- `/dashboard/` (company profile, bank accounts, shell APIs)
- `/static/`, `/media/`, favicon, service worker

Everything else → **HTTP 403** with message that company has profile-only access until platform unlocks full access.

### Full access predicate

```pseudo
account_has_full_access(account):
  if account is null: treat as true (edge) or false — pick one and test
  if not account.is_approved: return false
  owner = account.owner
  if not owner: return true  // legacy fallback — prefer false in new builds
  return owner.hasAnyPermission(ELEVATED_PERMISSIONS)
```

`ELEVATED_PERMISSIONS` = union of all business nav view permissions (clients, invoices, quotations, receipts, job orders, waybills, requisitions, inventory, expense, finance, accounting, messaging, mailing, team/roles, activity, HR, attendance, payroll, documents, notifications, reports, dashboard, video calls, …). **Not** only `core.view_companyprofile`.

---

## A5. Data isolation algorithm (copy this verbatim into any stack)

### Who is company admin?

```pseudo
is_company_admin(user, request):
  if not authenticated: return false
  if not user.account_id: return false
  if request.session.acting_as_team_member_id: return false   // critical
  account = load Account(user.account_id)
  if not account: return false
  if account.owner_id is null:
    set owner_id = user.id   // backfill once
    return true
  return account.owner_id == user.id
```

### Visibility

```pseudo
visible_to(queryset_already_tenant_filtered, user, request, model):
  if not authenticated: return empty
  if is_company_admin(user, request): return queryset
  if is_read_only_or_full_visibility(user): return queryset
  if model has no created_by field: return empty   // SAFE DEFAULT
  return queryset.filter(created_by_id = user.id)
```

### Full visibility / read-only helpers

```pseudo
has_full_company_visibility(user):
  return user has any Role where role.account_id = user.account_id
         AND role.full_company_visibility = true

user_has_only_view_permissions(user):
  perms = all permission codes on user's roles
  if empty: return false
  every code starts with view_ OR print_ OR download_

is_read_only_user(user):
  return has_full_company_visibility(user) OR user_has_only_view_permissions(user)
```

Mutation block (POST/PUT/PATCH/DELETE): only when `has_full_company_visibility` **AND** `user_has_only_view_permissions`. If admin assigned add/change/delete to that role, allow mutations.

### Tenant + visibility entry points (implement all three)

| Surface | Function |
|---------|----------|
| Web controllers / handlers | `for_user_queryset(Model, user, request, account_lookup)` |
| Class-based / resource controllers | mixin that overrides `get_queryset` |
| REST APIs | `filter_queryset_for_user(qs, request, account_lookup)` |
| Admin / back-office | account-scoped admin base class |

`account_lookup`:

- `'account'` / `account_id` — Invoice, Receipt, Requisition, Waybill, Product, Inventory, Expense, Conversation, …  
- `'company__account'` / join company → account — Client, Accounting Transaction, Document, …  

```pseudo
for_user_queryset(Model, user, request, account_lookup='account'):
  account = get_account_for_user(user)
  if not account: return empty
  qs = Model.filter(account_lookup → account)
  return visible_to(qs, user, request, Model)
```

```pseudo
get_account_for_user(user):
  if user.account: return it
  if user.account_id: load by id
  if user.linked_team_member.account_owner.account: return that
  return null
```

---

## A6. RBAC system (generic)

### Default roles

| Role name | Permissions | When |
|-----------|-------------|------|
| **Company Profile Viewer** | only `core.view_companyprofile` | Every new registration |
| **Company Admin** | **all** permission codes in catalog | When Account approved; kept in sync on migrations |
| Custom roles | Exactly what Account admin assigns | Owner/admins create under `/auth/security/roles/` |
| Roles with `full_company_visibility=true` | Whatever perms assigned; see all rows | e.g. “Company Read Only”, “Finance Viewer” |

Do **not** authorize by role name. Authorize by permission codes. `full_company_visibility` is the only special role **flag** (visibility).

### Permission check patterns

| Guard | Behavior |
|-------|----------|
| `require_login` | Unauthenticated → login redirect / 401 |
| `require_permission(code)` | Must have code → else 403 |
| `company_admin_OR_permission(code)` | Company admin bypass OR has code |
| `company_admin_OR_any(codes[])` | Admin OR any of list |
| `require_not_read_only` | Block mutating methods for view-only full-visibility users |
| REST method map | GET→view, POST→add, PUT/PATCH→change, DELETE→delete |

### Privilege boundaries when editing roles

```pseudo
permissions_user_may_assign(assigner):
  if assigner.is_superuser: return ALL
  return assigner's permissions
         MINUS meta "manage permission catalog / manage global groups" codes

role_permissions_are_subset_of_user(role, assigner):
  every permission on role ∈ assigner's permissions

roles_assigner_may_assign(account, assigner):
  if superuser OR (approved account owner): all roles in account
  else: roles where role_permissions_are_subset_of_user
```

Non-delegatable meta permissions (never assignable by non-superuser in role UI):

- manage permission definitions (add/change/delete/view permission catalog)
- manage global auth groups (add/change/delete/view group) when those would escalate

### Role services (required operations)

| Operation | Invariants |
|-----------|------------|
| `create_role(account, name, perm_codes[], full_visibility?)` | unique name per account; attach only allowed perms |
| `update_role_permissions(role, perm_codes[])` | exact replace; no auto-adding “dependency” perms |
| `assign_user_to_role(user, role)` | `user.account_id == role.account_id` or throw |
| `set_user_single_role(user, role\|null)` | remove all roles of that account, then add one |
| `delete_role(role)` | remove from all users → delete role + mappings |
| `get_or_create_default_viewer_role(account)` | Company Profile Viewer |
| `get_or_create_company_admin_role(account)` | all perms |
| `sync_all_permissions_to_company_admins()` | after migrations / new modules |

### Auth login for team members

```pseudo
authenticate(email, password):
  user = find User by email
  if user and password ok and active: return user
  team = find TeamMember by email and active
  if team and password ok:
    linked = ensure_linked_user(team)  // same account as owner
    return linked
  return null

on_login_success(user, session):
  clear session.acting_as_team_member_id
  if user has linked_team_member:
    session.acting_as_team_member_id = that id
    force user.account_id = owner.account_id
  create security session row + LOGIN activity (with account_id)
```

---

## A7. Lifecycle flows (end-to-end)

### Flow 1 — Company registers

1. `POST /auth/register/` creates User.  
2. Hook: create Account(owner=user), set user.account_id, create Company Profile Viewer role, assign user.  
3. User can log in but business modules blocked until approval + elevated owner perms.

### Flow 2 — Platform approves Account

1. Super-admin sets `accounts.is_approved = true`.  
2. Hook: create/update Company Admin with ALL permissions; assign owner; clear caches.  
3. Owner sees full nav; can create custom roles and invite team.

### Flow 3 — Owner creates roles

Routes under `/auth/security/roles/` (see Part B). Always scoped:

```pseudo
account = request.company.account OR request.user.account
roles = Role.where(account_id = account.id)
get role by id MUST include account_id = account.id else 404
```

### Flow 4 — Owner adds team member

1. Requires at least one assignable role.  
2. Create TeamMember under `account.owner`; create linked User with same account_id; `set_user_single_role`.  
3. List always: `TeamMember.where(account_owner.account_id = account.id)`.

### Flow 5 — Team member works

1. Logs in with own email; session marks team member.  
2. `is_company_admin` = false → sees only own rows (unless full_company_visibility).  
3. Features gated by role permissions.  
4. Company logo/currency from owner’s Company Profile.

---

## A8. Conditions matrix (every critical gate)

| # | Condition | Effect |
|---|-----------|--------|
| 1 | No `user.account_id` | Empty querysets; forbid team/role management |
| 2 | Account not approved OR owner lacks elevated perms | Profile-only middleware |
| 3 | `session.acting_as_team_member_id` set | Not company admin for visibility/bypass |
| 4 | `user.id == account.owner_id` and no team session | Admin: all rows + admin-OR-perm bypass |
| 5 | Role has `full_company_visibility` | See all tenant rows |
| 6 | Full visibility + only view/print/download | Mutations → 403 |
| 7 | Team member, no full visibility | Only `created_by = me` |
| 8 | Model without `created_by` | Non-admin → empty |
| 9 | Assign user to foreign Account’s role | Error / 403 |
| 10 | Role id outside current account | 404 |
| 11 | Assign permission you don’t have | Validation error |
| 12 | Team CRUD without matching account scope | 403 / not found |
| 13 | Cannot delete Account owner as team member | Error |
| 14 | Unique business keys | Scoped per company/account |

---

## A9. Porting guide (same design, other stacks)

| Concern | Generic approach | Examples |
|---------|------------------|----------|
| Tenant column | `account_id` on every business table | Prisma, Eloquent, ActiveRecord, EF, TypeORM |
| Isolation | Repository method / global query scope / RLS | Nest interceptor, Laravel global scope, Rails default_scope (careful), Postgres RLS |
| Permissions | Policy classes or CASL/CASBIN/Spatie | `@RequirePermission`, Gates, Pundit, Policy |
| Roles per tenant | `roles.account_id` + unique name | Spatie teams, custom Role model |
| Request company | Middleware sets `req.company` | Express/Nest middleware, Laravel, Rails |
| Approval gate | Middleware allowlist | Same |
| Team login | Dual credential lookup → linked user | Passport strategy, Laravel guard, Devise |
| Admin panel | Scope querysets by account | ActiveAdmin, Filament, Django Admin equivalent |
| Realtime | Channels/WebSockets scoped by account membership | Socket.io rooms `account:{id}` |
| Tests | Cross-tenant IDOR tests mandatory | Integration suite |

**Reference implementation in this repo (optional):** Django + custom User + AccountGroup wrapping auth Groups. You do **not** need Django Groups; any role↔permission tables work if invariants hold.

---

# PART B — Module catalog, routing, APIs (full inventory)

## B1. System overview

| Item | Value |
|------|-------|
| App type | Multi-tenant business / operations platform |
| Tenancy | Shared DB, Account-scoped rows |
| Auth | Email + password; User or Team Member credentials |
| Login path | `/auth/login/` |
| Post-login | `/dashboard/` |
| Landing | `/` → `/dashboard/landing/` |
| Logout redirect | `/dashboard/landing/` |
| Platform admin | `/admin/` |
| 403 handler | Role-aware message (owner vs team member) |

### Modules (logical apps)

| Module | Purpose |
|--------|---------|
| **accounts** | Users, team members, roles, security, sessions, activity |
| **core** | Dashboard, company profile, bank accounts, tenant, isolation helpers, summaries |
| **invoices** | Invoices + templates |
| **receipts** | Receipts linked to invoices |
| **requisitions** | Requisitions + approval workflow |
| **waybills** | Waybills + templates |
| **job_orders** | Products/job orders, orders, customers, stores, leaves |
| **quotations** | Quotations + templates, convert to invoice |
| **inventory** | Stock in/out, balances, approval |
| **store** | Store / waste / layouts (related inventory domain) |
| **expense** | Expenses + approval |
| **clients** | Clients (company-scoped) |
| **accounting** | Transactions, ledger, reports, sync |
| **messaging** | Conversations, messages, presence, calls (WebSocket) |
| **mailing** | Bulk email campaigns |
| **hr_staff** | HR employees, departments, leave, etc. |
| **payroll** | Payroll records / offline sync |
| **notifications** | In-app notifications |
| **sync_api** | Offline-first sync under `/api/v1/` |
| **smart_attendance** | Biometric devices, push, live logs |
| **documents** | Document upload + AI pipeline |
| **extraction** | OCR / PDF extraction |
| **ai_engine** | NLP structured fields from text |
| **finance_engine** | Financial transactions from AI |
| **tax_engine** | Tax computation |
| **reports** | Tax dashboards + PDF export |
| **videocalls** | Video call rooms / recordings |

---

## B2. Root URL routing (complete)

| Path | Module / purpose |
|------|------------------|
| `sw.js`, `service-worker.js` | PWA / offline SW |
| `admin/` | Platform admin |
| `` (empty) | Redirect → `/dashboard/landing/` |
| `auth/` | Accounts: login, register, profile, security, roles, team |
| `dashboard/` | Core dashboard, company profile, bank accounts, summary APIs |
| `api/invoices/` | Invoice REST API |
| `api/requisitions/` | Requisition REST API |
| `api/core/` | Core dashboard/realtime/currency APIs |
| `api/receipts/` | Receipts API |
| `api/waybills/` | Waybills API |
| `api/job-orders/` | Job orders API |
| `quotations/` | Quotations web |
| `api/clients/` | Clients API |
| `api/mailing/` | Mailing API |
| `api/inventory/` | Inventory API |
| `api/store/` | Store API |
| `api/expense/` | Expense API |
| `accounting/api/` | Accounting API |
| `invoices/` | Invoices web |
| `receipts/` | Receipts web |
| `requisitions/` | Requisitions web |
| `waybills/` | Waybills web |
| `job-orders/` | Job orders web |
| `clients/` | Clients web |
| `inventory/` | Inventory web |
| `store/` | Store web |
| `expense/` | Expense web |
| `accounting/` | Accounting web |
| `messaging/` | Messaging web + messaging APIs |
| `mailing/` | Mailing web |
| `hr-staff/` | HR web |
| `api/hr-staff/` | HR API |
| `api/v1/` | Sync API |
| `documents/` | Documents web |
| `reports/` | Tax reports web |
| `api/documents/` | Documents API |
| `api/extraction/` | Extraction API |
| `api/ai/` | AI analyze API |
| `api/finance/` | Finance extract API |
| `api/tax/` | Tax API |
| `api/reports/` | Reports API |
| `payroll/` | Payroll web |
| `api/payroll/` | Payroll API (+ offline-sync) |
| `notifications/` | Notifications web |
| `attendance/` | Smart attendance web |
| `api/biometric/push`, `.../batch` | ZKTeco push gateway |
| `api/devices`, `api/devices/discover` | Device list / discovery |
| `api/attendance/*` | live, realtime, logs, report, today, employee, device-status, last-punch, push-offline |
| `videocalls/` | Video calls web |

Media/static served at configured MEDIA/STATIC URLs.

---

## B3. Accounts module — routing & logic

### Auth

| Path | Action |
|------|--------|
| `/auth/login/` | Login (User or Team Member) |
| `/auth/logout/` | Logout; clear team session flag |
| `/auth/register/` | Register → Account + default Viewer role |
| `/auth/password_reset/` … `/auth/reset/complete/` | Password reset |
| `/auth/password-change-required/` | Forced password change |

### Profile

| Path | Action |
|------|--------|
| `/auth/profile/` | View profile + role names |
| `/auth/profile/edit/` | Edit profile |
| `/auth/dashboard/` | Accounts dashboard helper |

### Security / team

| Path | Required permission | Isolation |
|------|---------------------|-----------|
| `/auth/security/` | login + security hub perms | account |
| `/auth/security/team/` | `accounts.view_subuser` | `team_members` where owner.account = current |
| `/auth/security/team/add/` | `accounts.add_subuser` | role must be same account + assignable |
| `/auth/security/team/<id>/edit/` | `accounts.change_subuser` | id + same account |
| `/auth/security/team/<id>/delete/` | `accounts.delete_subuser` | same; cannot delete owner |

### Security / roles

| Path | Required permission | Isolation |
|------|---------------------|-----------|
| `/auth/security/roles/` | `auth.view_group` (or `roles.view`) | roles for current account only |
| `/auth/security/roles/add/` | `auth.add_group` | create under current account |
| `/auth/security/roles/<id>/edit/` | `auth.change_group` | id + account |
| `/auth/security/roles/<id>/delete/` | `auth.delete_group` | remove members then delete |
| `/auth/security/roles/<id>/members/` | `auth.change_group` | members limited to owner + active team linked users |

### Security / sessions & activity

| Path | Notes |
|------|-------|
| `/auth/security/sessions/` | Session history (account-scoped) |
| `/auth/security/session/<uuid>/` | Detail |
| `/auth/security/session/<uuid>/terminate/` | Terminate one |
| `/auth/security/sessions/terminate-all/` | Terminate all |
| `/auth/security/activities/` | Activity log (`view_activity_log` / `view_useractivity`) |
| `/auth/security/activity/<uuid>/` | Detail with changes / deleted_data |
| `/auth/security/admin/` | Platform staff overview |
| `/auth/security/admin/user/<id>/` | Per-user activities |
| `/auth/security/admin/live-users/` | Live users |

### Account resolution helper (all security views)

```pseudo
get_request_account(request):
  if request.company?.account_id: return request.company.account
  return request.user.account
```

---

## B4. Core / dashboard — routing

| Path | Purpose |
|------|---------|
| `/dashboard/` | Main dashboard |
| `/dashboard/landing/` | Landing |
| `/dashboard/company-profile/` | View/edit company (perms: view/change companyprofile) |
| `/dashboard/bank-accounts/` | List bank accounts |
| `/dashboard/bank-accounts/<pk>/edit/` | Edit |
| `/dashboard/bank-accounts/<pk>/delete/` | Delete |
| `/dashboard/bank-accounts/<pk>/set-default/` | Set default |
| `/dashboard/update-currency/` | Update currency |
| `/dashboard/api/dashboard/stats\|charts\|actions\|tips/` | Dashboard widgets |
| `/dashboard/api/core/num2words/` | Number to words |
| `/dashboard/api/summaries/dashboard\|invoices\|receipts\|quotations\|job-orders\|waybills/` | **Must use tenant+visibility filter** |

### API `/api/core/`

- `num2words/`, `my-ip/`
- `dashboard/stats|charts|actions|tips/`
- `dashboard/realtime|notifications|activity|inventory-alerts|system-health/`
- `update-currency/`, `currency-status/`

---

## B5. Business modules — routing, permissions, isolation

### B5.1 Invoices

**Web:** `/invoices/` list; `create/`, `create/dynamic/`; `<pk>/`, `edit/`, `delete/`, `delete-ajax/`; `pdf/`, `print/`; `export/excel|pdf/`; `templates/` CRUD + duplicate + apply-to-all; `api/templates/`, `<pk>/update-status/`, `toggle-payment/`.

**API:** `api/invoices/` — list/create/retrieve/update/destroy; tenant+visibility.

**Model keys:** `account_id`, `created_by_id` (+ template, client fields, status, bank/signature flags).

**Permissions:** `invoices.view|add|change|delete_invoice`, `print_invoice`, `download_invoice`, `can_approve_invoice`; template CRUD. Use `admin_OR_perm` for change/delete/print/download/approve.

**Isolation:** `account_lookup = account`.

---

### B5.2 Receipts

**Web:** `/receipts/` list; `create/`, `create/<invoice_id>/`; `<id>/` detail/edit/delete/print/pdf/email; export excel/pdf.

**API:** `api/receipts/`.

**Keys:** `account_id`, `created_by_id`, link to invoice.

**Permissions:** `receipts.view|add|change|delete_receipt`, `print_receipt`, `download_receipt`; admin_OR_perm for mutations/print/download.

---

### B5.3 Requisitions

**Web:** `/requisitions/` list; `modal/`; `create/`; `<pk>/` detail/edit/delete/print/pdf/`update-status/`.

**API:** `api/requisitions/`.

**Keys:** `account_id`, `created_by_id`, `approved_by`, `company_id`, workflow status.

**Permissions:** view/add/change/delete/print/download + `can_approve_requisition` for status approve/reject.

**Isolation:** `account`.

---

### B5.4 Waybills

**Web:** `/waybills/` list; multiple create variants; `<pk>/` CRUD/print/`update-status/`; exports; templates CRUD; APIs for template fields, form-content, preview, company-profile.

**Keys:** `account_id`, `created_by_id`, optional `company_id`.

**Permissions:** waybill CRUD + print/download + `can_approve_waybill`; template CRUD.

---

### B5.5 Job orders

**Web:** `/job-orders/` products list; create; `<pk>/` detail/print/edit/delete; product-view; approve; update-delivery; production status; exports; customers/stores/orders/leaves CRUD; update-currency.

**Keys:** Product `account_id`, `created_by_id`.

**Permissions:** product/order CRUD; templates; `print_product`, `download_product`, `can_approve_jobs`, `can_view_all_jobs`, `can_manage_production`, `view_dashboard`, leave perms, export perms.

**Isolation:** `account` on Product (and related).

---

### B5.6 Quotations

**Web:** `/quotations/` full CRUD; duplicate/preview; pdf/print; exports; update-status; send-email; convert-to-invoice (also needs `invoices.add_invoice`); bulk-actions; ajax line items/totals/draft; templates.

**Keys:** `account_id`, `created_by_id`, `company_id`.

**Permissions:** quotation CRUD + print/download (+ approve if used); template CRUD.

---

### B5.7 Inventory

**Web:** `/inventory/` list; list print/pdf; dashboard; create/update/delete/detail/print/pdf; ajax field/status; dashboard-stats.

**API:** `api/inventory/`.

**Keys:** `account_id`, `company_id`, `created_by_id`.

**Permissions:** inventory CRUD + print/download + `can_approve_inventory`.

---

### B5.8 Expense

**Web:** `/expense/` (same pattern as inventory).

**API:** `api/expense/`.

**Keys:** `account_id`, `company_id`, `created_by_id`.

**Permissions:** expense CRUD + print/download + `can_approve_expense`.

---

### B5.9 Clients

**Web:** `/clients/` list/create/`<pk>/` detail/edit/delete.

**API:** `api/clients/<id>/`.

**Keys:** `company_id`, `created_by_id`.

**Permissions:** `clients.view|add|change|delete_client`.

**Isolation:** `company → account` (`company__account`).

---

### B5.10 Accounting

**Web:** `/accounting/` dashboard; transactions list/add/`<uuid>/` edit/delete/reconcile/unreconcile; update_currencies; export; reports generate/detail/export-pdf; sync; ajax ledger/currency.

**Keys:** Transaction `company_id`, `created_by_id`.

**Permissions:** transaction CRUD; ledger view; chart/account CRUD; financial report CRUD.

**Isolation:** `company__account`.

---

### B5.11 Messaging

**Web:** `/messaging/` inbox; `/messaging/conversation/<id>/` chat.

**API (under `/messaging/api/`):** csrf; account-users; conversations CRUD; messages list/send/upload/delete/mark-read; call start/status/end; members add/remove; leave/rejoin; rename; typing; presence; message-file.

**Keys:** Conversation `account_id`, `created_by_id`; membership by user within account.

**Permissions:** conversation/message/etc. view/add/change/delete; nav: `messaging.view_conversation`.

**Isolation:** account-scoped conversations; only members see messages.

---

### B5.12 Documents / AI / tax / reports

**Web:** `/documents/` list/upload/`<pk>/` detail/delete/reprocess/status/processing-status; `/reports/dashboard|monthly|quarterly|annual/`; `/reports/export/pdf/`.

**API:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/documents/upload/` | Upload + run pipeline |
| GET | `/api/documents/<id>/status/` | Processing status |
| POST | `/api/extraction/run/` | OCR/PDF only |
| POST | `/api/ai/analyze/` | Structured fields |
| POST | `/api/finance/extract/` | Create financial txs |
| GET | `/api/tax/compute/`, `/api/tax/list/` | Tax records |
| GET | `/api/reports/dashboard/` | Period totals JSON |

**Pipeline:** extraction → AI → finance transactions → tax compute (monthly) → store preview + JSON on document.

**Tax formulas:** profit = revenue − expenses; corporate_tax = profit × 0.30; vat_payable = output_vat − input_vat.

**Keys:** all `company_id`; access via `request.company`.

**Permissions:** documents CRUD; `documents.view_tax_report` for reports/tax APIs; admin_OR_perm.

---

### B5.13 Mailing

**Web/API:** `/mailing/`, `api/mailing/`. Company-scoped From address + logo from Company Profile.

---

### B5.14 HR Staff

**Web/API:** `/hr-staff/`, `api/hr-staff/`. Company-scoped employees/departments/leave/etc.

**Nav perms include:** `hr_staff.view_hr_dashboard`, `view_own_hr_dashboard`, department/employee/leave/… view perms.

---

### B5.15 Payroll

**Web/API:** `/payroll/`, `api/payroll/`, `api/payroll/offline-sync`. Tenant-scoped payroll records.

---

### B5.16 Notifications

**Web:** `/notifications/`. In-app notifications (user/account scoped).

---

### B5.17 Sync API

**Path:** `/api/v1/`. Offline-first sync; must still enforce auth + tenant on every resource.

---

### B5.18 Smart attendance

**Web:** `/attendance/` dashboard; `/attendance/devices/`; `/attendance/devices/register/`.

**API:** biometric push (+ batch); devices; attendance live/realtime/logs/report/today/employee/device-status/last-punch/push-offline.

**Isolation:** devices and logs company/account-scoped; push verifies device secret.

---

### B5.19 Video calls

**Web:** `/videocalls/`. Rooms, invitations, recordings; permission-gated; account-aware.

---

### B5.20 Store

**Web/API:** `/store/`, `api/store/`. Store entities company/account-scoped; Company Admin sync includes store permissions.

---

## B6. APIs quick reference

| Prefix | Content |
|--------|---------|
| `api/invoices/` | Invoice resource CRUD |
| `api/requisitions/` | Requisition resource CRUD |
| `api/receipts/`, `api/waybills/`, `api/job-orders/` | Domain APIs |
| `api/core/` | Dashboard, realtime, currency, health |
| `api/clients/<id>/` | Client detail |
| `api/inventory/`, `api/store/`, `api/expense/` | Inventory/store/expense |
| `accounting/api/` | Accounting API |
| `dashboard/api/...` | Stats, charts, summaries (tenant+visibility) |
| `messaging/api/...` | Chat, presence, calls |
| `api/mailing/` | Campaigns |
| `api/documents/`, `api/extraction/`, `api/ai/`, `api/finance/`, `api/tax/`, `api/reports/` | AI tax analyzer |
| `api/hr-staff/`, `api/payroll/` | HR / payroll |
| `api/v1/` | Offline sync |
| `api/biometric/*`, `api/devices*`, `api/attendance/*` | Attendance |
| `videocalls/` | Video |

**All authenticated APIs:** apply tenant + visibility (or membership) filters. Never trust client-supplied `account_id`.

---

## B7. Feature → navigation permissions

Nav item visible only if user has **any** of the mapped view permissions (and Account has full access where gated).

| Nav key | Example required permissions |
|---------|------------------------------|
| clients | `clients.view_client` |
| invoices | `invoices.view_invoice` |
| quotations | `quotations.view_quotation` |
| receipts | `receipts.view_receipt` |
| job_orders | `job_orders.view_product` / `view_order` |
| waybills | `waybills.view_waybill` |
| requisitions | `requisitions.view_requisition` |
| inventory | `inventory.view_inventory` |
| expense | `expense.view_expense` |
| accounting | `accounting.view_transaction` (and related) |
| messaging | `messaging.view_conversation` |
| mailing | mailing use/view perms |
| team_and_roles | `accounts.view_subuser` OR `accounts.view_accountgroup` |
| company_profile | `core.view_companyprofile` OR `change_companyprofile` |
| activity | `accounts.view_useractivity` OR `view_activity_log` |
| hr_staff | `hr_staff.view_hr_dashboard` OR `view_own_hr_dashboard` |
| smart_attendance | `smart_attendance.view_attendance_dashboard` |
| payroll | `payroll.view_payrollrecord` / `view_payroll` |
| documents | `documents.view_document` |
| notifications | `notifications.view_notification` |
| reports | `reports.view_tax_report` OR `documents.view_tax_report` |
| dashboard | `core.view_dashboard` |
| video_calls / recordings | videocalls view perms |

`ELEVATED_PERMISSIONS` = union of the above business nav perms (used for full-access unlock).

UI context flags to expose globally: `user_can_manage_users`, `user_can_access_company_profile`, `is_company_admin`, `is_read_only_user`, `show_created_by`, `show_request_full_access_cta`, `show_approved_assign_role_notice`, company theme/currency.

---

## B8. Permissions catalog (by module)

Format: `module.codename`. Labels are display-only.

- **Job orders:** view/add/change/delete product & order; jobordertemplate CRUD; print/download product; `can_approve_jobs`, `can_view_all_jobs`, `can_export_*`, `can_manage_production`, `view_dashboard`, leave manage/export; customer/employeeprofile as used  
- **Invoices:** invoice CRUD; print/download; `can_approve_invoice`; invoicetemplate CRUD  
- **Receipts:** receipt CRUD; print/download  
- **Quotations:** quotation CRUD; print/download; (`can_approve_quotation` if used); template CRUD  
- **Waybills:** waybill CRUD; print/download; `can_approve_waybill`; template CRUD  
- **Requisitions:** requisition CRUD; print/download; `can_approve_requisition`  
- **Inventory:** inventory CRUD; print/download; `can_approve_inventory`  
- **Expense:** expense CRUD; print/download; `can_approve_expense`  
- **Clients:** client CRUD  
- **Messaging:** conversation, conversationmember, message, messagehiddenforuser, callsession, userpresence, typingindicator CRUD as applicable  
- **Accounting:** transaction CRUD; view_ledger; account CRUD; financialreport CRUD  
- **Core:** companyprofile CRUD; bankaccount CRUD; view_dashboard  
- **Accounts:** user CRUD; subuser (team) CRUD; accountgroup (role) CRUD; usersession view/change; useractivity / `view_activity_log`  
- **Auth/meta:** group/permission management — **non-delegatable** in tenant role UI  
- **Documents:** document CRUD; `view_tax_report`  
- **HR / payroll / attendance / mailing / videocalls / notifications / store / finance_engine:** module view/add/change/delete + custom dashboard/approve perms as registered in the permission catalog  

Human-readable labels and module order for Role UI belong in a single permission-labels map (do not change stored codes).

---

## B9. UI screens (logical; any frontend)

Implement equivalent screens (SPA, server templates, mobile):

- Auth: login, register, password reset/confirm/complete, forced password change  
- Profile view/edit  
- Security hub; team list/form; role list/form/members; sessions; activity list/detail  
- Dashboard / landing; company profile; bank accounts  
- Per module: list, detail, create/edit form, confirm delete, print, PDF/export, dashboards where listed  
- Messaging inbox/chat  
- Documents list/upload/detail/processing; tax reports  
- Attendance dashboard/devices/register  
- Base layout with permission-gated side nav  

---

## B10. RBAC summary (short)

1. Authorize with permission codes only.  
2. Map features → permissions for nav and guards.  
3. Company admin (owner, not acting as team member) may bypass via `admin_OR_permission`.  
4. `full_company_visibility` = see all tenant rows; mutation still needs add/change/delete.  
5. Delegation: assign only perms you have; block meta escalation perms.  
6. Clear permission caches after role changes.  
7. Keep Company Admin synced when new permissions appear.

---

## B11. Data isolation summary (short)

1. Every business row belongs to an Account (directly or via Company).  
2. Company admin sees all tenant rows.  
3. Team members see own `created_by` rows unless `full_company_visibility`.  
4. Central filter on lists, get-by-id, reports, exports, APIs, admin.  
5. `account` vs `company→account` lookup depending on model.  
6. Safe default: no `created_by` field → non-admin sees nothing.

---

## B12. Anti-leak / production test plan

| Test | Expect |
|------|--------|
| User A lists invoices | Only Account A |
| User A GET invoice id from B | 404/403 |
| Team member without full visibility | Only own created rows |
| Team member with full visibility + view-only | Sees all; POST create → 403 |
| Assign role from Account B to User A | Rejected |
| Create role “Admin” on A and B | Two distinct roles; no shared membership |
| Unapproved account hits `/invoices/` | 403 |
| After approve | Owner has Company Admin; business routes work |
| Delete team member | Linked user roles cleared; cannot login as team |
| Report/export endpoints | Same filters as list |
| Messaging | Cannot open other account’s conversation id |

---

## B13. Reference mapping (this repository only)

If you are reading this while working **inside this Django codebase**, the concepts map as:

| Generic | This repo |
|---------|-----------|
| Account | `core.Account` |
| Company Profile | `core.CompanyProfile` |
| User | `accounts.User` |
| Team Member | `accounts.SubUser` |
| Role | `accounts.AccountGroup` + `auth.Group` |
| Isolation SSOT | `apps.core.ownership` |
| Company middleware | `CompanyContextMiddleware` |
| Approval middleware | `AccountApprovalMiddleware` |
| Permission labels | `apps.accounts.permission_labels` |
| Feature/nav map | `apps.core.feature_permissions` |
| Role services | `apps.accounts.services` |
| Boundaries | `apps.accounts.permission_boundaries` |
| Default roles | `apps.accounts.default_role` |

You can delete or ignore this section when using the document as a **pure** cross-stack blueprint.

---

# End

This document lists the multi-tenant model, RBAC, isolation algorithms, conditions, lifecycle, middleware, full routing, module inventory, APIs, permission catalog, UI surfaces, porting guidance, and test plan from beginning to end so the same system can be rebuilt on any programming stack without skipping a layer.
