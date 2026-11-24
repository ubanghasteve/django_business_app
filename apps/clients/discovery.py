# -*- coding: utf-8 -*-
"""
Auto-discover client information from all apps in the project.
Each provider yields (name, email, phone, record_url, app_label, record_label, record_id).
Sync merges into Client model without duplicating (dedupe by normalized email/phone/name).
New apps can register by adding a provider to CLIENT_PROVIDERS or by implementing
get_client_providers() in their app config (optional convention).
"""
from django.apps import apps as django_apps
from django.urls import reverse


def _normalize_email(email):
    if not email or not isinstance(email, str):
        return ''
    return email.strip().lower()


def _normalize_phone(phone):
    if not phone or not isinstance(phone, str):
        return ''
    return ''.join(c for c in phone if c.isdigit() or c == '+')[:32]


def _normalize_name(name):
    if not name or not isinstance(name, str):
        return ''
    return ' '.join(name.strip().split())[:255]


def _row(name, email, phone, record_url, app_label, record_label, record_id, created_at=None, created_by_name=''):
    """Build a client row dict. created_at: datetime or None; created_by_name: str."""
    return {
        'name': _normalize_name(name) or name,
        'email': _normalize_email(email),
        'phone': _normalize_phone(phone),
        'record_url': record_url or '',
        'app_label': app_label or '',
        'record_label': record_label or '',
        'record_id': str(record_id) if record_id is not None else '',
        'created_at': created_at,
        'created_by_name': (created_by_name or '').strip()[:255],
    }


def _creator_display(obj):
    """Return created_by display name from record (User FK)."""
    cb = getattr(obj, 'created_by', None)
    if cb:
        return (getattr(cb, 'get_full_name', lambda: '')() or getattr(cb, 'email', '') or '').strip()
    return ''


# ---------- Invoices ----------
def _provider_invoices(user, request, account_id):
    try:
        from apps.invoices.models import Invoice
        from apps.core.ownership import for_user_queryset
        qs = for_user_queryset(Invoice, user, request, account_lookup='account')
        rows = []
        for inv in qs.select_related('account', 'created_by').only(
            'id', 'invoice_number', 'client_name', 'client_email', 'client_phone', 'account_id', 'created_at', 'created_by_id'
        ):
            if not inv.client_name and not inv.client_email and not inv.client_phone:
                continue
            try:
                url = reverse('invoices:detail', args=[inv.id])
            except Exception:
                url = f'/invoices/{inv.id}/'
            rows.append(_row(
                inv.client_name or '—',
                getattr(inv, 'client_email', '') or '',
                getattr(inv, 'client_phone', '') or '',
                url,
                'Invoices',
                f'Invoice {inv.invoice_number}',
                inv.id,
                getattr(inv, 'created_at', None),
                _creator_display(inv),
            ))
        return rows
    except Exception:
        return []


# ---------- Receipts ----------
def _provider_receipts(user, request, account_id):
    try:
        from apps.receipts.models import Receipt
        from apps.core.ownership import for_user_queryset
        qs = for_user_queryset(Receipt, user, request, account_lookup='account')
        rows = []
        for rec in qs.select_related('created_by').only(
            'id', 'receipt_no', 'client_name', 'client_phone', 'account_id', 'created_at', 'created_by_id'
        ):
            if not rec.client_name and not getattr(rec, 'client_phone', None):
                continue
            try:
                url = reverse('receipts:detail', args=[rec.id])
            except Exception:
                url = f'/receipts/{rec.id}/'
            rows.append(_row(
                rec.client_name or '—',
                getattr(rec, 'client_email', '') or '',
                getattr(rec, 'client_phone', '') or '',
                url,
                'Receipts',
                f'Receipt {rec.receipt_no}',
                rec.id,
                getattr(rec, 'created_at', None),
                _creator_display(rec),
            ))
        return rows
    except Exception:
        return []


# ---------- Quotations (client FK) ----------
def _provider_quotations(user, request, account_id):
    try:
        from apps.quotations.models import Quotation
        from apps.core.ownership import for_user_queryset
        qs = for_user_queryset(Quotation, user, request, account_lookup='account')
        rows = []
        for q in qs.select_related('client', 'created_by').only(
            'id', 'quotation_number', 'client_id', 'created_at', 'created_by_id'
        ):
            if not q.client_id:
                continue
            c = q.client
            name = (c.name if c else '').strip() or '—'
            email = (getattr(c, 'email', None) or '').strip() or ''
            phone = (getattr(c, 'phone', None) or '').strip() or ''
            if not name and not email and not phone:
                continue
            try:
                url = reverse('quotations:quotation_detail', args=[q.id])
            except Exception:
                url = f'/quotations/{q.id}/'
            rows.append(_row(
                name, email, phone,
                url,
                'Quotations',
                f'Quotation {q.quotation_number}',
                q.id,
                getattr(q, 'created_at', None),
                _creator_display(q),
            ))
        return rows
    except Exception:
        return []


# ---------- Waybills (custom_data: receiver/sender) ----------
def _provider_waybills(user, request, account_id):
    try:
        from apps.waybills.models import Waybill
        from apps.core.ownership import for_user_queryset
        qs = for_user_queryset(Waybill, user, request, account_lookup='account')
        rows = []
        for wb in qs.select_related('created_by').only(
            'id', 'waybill_number', 'custom_data', 'created_at', 'created_by_id'
        ):
            cd = getattr(wb, 'custom_data', None) or {}
            # Try receiver_info then sender_info (flat keys: receiver_name, receiver_phone, etc.)
            rec = cd.get('receiver_info') or {}
            snd = cd.get('sender_info') or {}
            name = (rec.get('receiver_name') or snd.get('sender_name') or '').strip()
            phone = (rec.get('receiver_phone') or snd.get('sender_phone') or '').strip()
            if not name and not phone:
                continue
            email = (rec.get('receiver_email') or rec.get('receiver_address') or snd.get('sender_email') or '').strip()
            if isinstance(email, dict):
                email = ''
            try:
                url = reverse('waybills:detail', args=[wb.id])
            except Exception:
                url = f'/waybills/{wb.id}/'
            rows.append(_row(
                name or '—', email, phone,
                url,
                'Waybills',
                f'Waybill {wb.waybill_number}',
                wb.id,
                getattr(wb, 'created_at', None),
                _creator_display(wb),
            ))
        return rows
    except Exception:
        return []


# ---------- Requisitions (organization as client-like) ----------
def _provider_requisitions(user, request, account_id):
    try:
        from apps.requisitions.models import Requisition
        from apps.core.ownership import for_user_queryset
        qs = for_user_queryset(Requisition, user, request, account_lookup='account')
        rows = []
        for r in qs.select_related('created_by').only(
            'id', 'organization_name', 'contact_number', 'created_at', 'created_by_id'
        ):
            name = (r.organization_name or '').strip()
            if not name:
                continue
            phone = (getattr(r, 'contact_number', None) or '').strip()
            try:
                url = reverse('requisitions:detail', args=[r.id])
            except Exception:
                url = f'/requisitions/{r.id}/'
            org = r.organization_name or ''
            label = (org[:30] + '...') if len(org) > 30 else (org or f'#{r.id}')
            rows.append(_row(
                name,
                '',  # requisitions typically don't have email
                phone,
                url,
                'Requisitions',
                f'Requisition {label}',
                r.id,
                getattr(r, 'created_at', None),
                _creator_display(r),
            ))
        return rows
    except Exception:
        return []


# ---------- Expense (vendor as client-like) ----------
def _provider_expense(user, request, account_id):
    try:
        from apps.expense.models import Expense
        from apps.core.ownership import for_user_queryset
        qs = for_user_queryset(Expense, user, request, account_lookup='account')
        rows = []
        for exp in qs.select_related('created_by').only(
            'id', 'transaction_id', 'vendor', 'created_at', 'created_by_id'
        ):
            name = (exp.vendor or '').strip()
            if not name:
                continue
            try:
                url = reverse('expense:detail', args=[exp.id])
            except Exception:
                url = f'/expense/detail/{exp.id}/'
            rows.append(_row(
                name,
                '',
                '',
                url,
                'Expense',
                f'Expense {exp.transaction_id}',
                exp.id,
                getattr(exp, 'created_at', None),
                _creator_display(exp),
            ))
        return rows
    except Exception:
        return []


# ---------- Inventory (company_name, vendor as client-like) ----------
def _provider_inventory(user, request, account_id):
    try:
        from apps.inventory.models import Inventory
        from apps.core.ownership import for_user_queryset
        qs = for_user_queryset(Inventory, user, request, account_lookup='account')
        rows = []
        for inv in qs.select_related('created_by').only(
            'id', 'transaction_id', 'company_name', 'vendor', 'phone_number', 'created_at', 'created_by_id'
        ):
            name = (inv.company_name or inv.vendor or '').strip()
            if not name:
                continue
            phone = (inv.phone_number or '').strip()
            try:
                url = reverse('inventory:detail', args=[inv.id])
            except Exception:
                url = f'/inventory/detail/{inv.id}/'
            rows.append(_row(
                name,
                '',
                phone,
                url,
                'Inventory',
                f'Inventory {inv.transaction_id}',
                inv.id,
                getattr(inv, 'created_at', None),
                _creator_display(inv),
            ))
        return rows
    except Exception:
        return []


# ---------- Job Orders (Product.organization_name as client-like) ----------
def _provider_job_orders(user, request, account_id):
    try:
        from apps.job_orders.models import Product
        from apps.core.ownership import for_user_queryset
        qs = for_user_queryset(Product, user, request, account_lookup='account')
        rows = []
        for p in qs.select_related('created_by').only(
            'id', 'job_order', 'organization_name', 'address', 'contact_number', 'date_created', 'created_by_id'
        ):
            name = (p.organization_name or '').strip()
            if not name:
                continue
            phone = (p.contact_number or '').strip()
            try:
                url = reverse('job_orders:product_detail', args=[p.id])
            except Exception:
                url = f'/job-orders/{p.id}/'
            rows.append(_row(
                name,
                '',
                phone,
                url,
                'Job Orders',
                f'Job Order {p.job_order}',
                p.id,
                getattr(p, 'date_created', None) or getattr(p, 'created_at', None),
                _creator_display(p),
            ))
        return rows
    except Exception:
        return []


# ---------- Dynamic discovery: any app can expose get_client_providers() ----------
def _get_providers_from_app_configs():
    """Yield (provider_callable, app_label) from app configs that define get_client_providers()."""
    for config in django_apps.get_app_configs():
        get_providers = getattr(config, 'get_client_providers', None)
        if get_providers and callable(get_providers):
            for item in get_providers():
                if callable(item):
                    yield (item, config.label)
                elif isinstance(item, (list, tuple)) and len(item) >= 2 and callable(item[0]):
                    yield (item[0], item[1] if len(item) > 1 else config.label)


# Built-in registry: (provider_func, app_label). Provider signature: (user, request, account_id) -> list of row dicts.
CLIENT_PROVIDERS = [
    (_provider_invoices, 'invoices'),
    (_provider_receipts, 'receipts'),
    (_provider_quotations, 'quotations'),
    (_provider_waybills, 'waybills'),
    (_provider_requisitions, 'requisitions'),
    (_provider_expense, 'expense'),
    (_provider_inventory, 'inventory'),
    (_provider_job_orders, 'job_orders'),
]


def get_all_provider_rows(user, request, account_id):
    """Run all registered providers and return a single list of client rows (with app_label, etc.)."""
    rows = []
    for provider, app_label in CLIENT_PROVIDERS:
        try:
            rows.extend(provider(user, request, account_id))
        except Exception:
            continue
    for provider, app_label in _get_providers_from_app_configs():
        try:
            # Dynamic providers may take (user, request) and return list; support both
            result = provider(user, request, account_id) if _arity(provider) >= 3 else provider(user, request)
            if result:
                for r in result:
                    if isinstance(r, dict) and 'app_label' not in r:
                        r['app_label'] = app_label
                rows.extend(result)
        except Exception:
            continue
    return rows


def _arity(f):
    try:
        return f.__code__.co_argcount
    except Exception:
        return 0


def sync_discovered_clients(user, request):
    """
    Discover clients from all apps, merge into Client model (by company), dedupe by email/phone/name.
    Returns (clients_queryset, stats_dict). Uses get_company_profile_for_user for company/account.
    """
    from apps.core.utils import get_company_profile_for_user
    from apps.clients.models import Client

    from apps.core.ownership import for_user_queryset

    company = get_company_profile_for_user(user, request)
    if not company:
        return Client.objects.none(), {'synced': 0, 'created': 0, 'updated': 0}

    account_id = getattr(company, 'account_id', None) or getattr(company.account, 'id', None)
    if not account_id:
        return for_user_queryset(Client, user, request, account_lookup='company__account'), {'synced': 0, 'created': 0, 'updated': 0}

    rows = get_all_provider_rows(user, request, account_id)
    created = 0
    updated = 0

    def key_for(r):
        ne = (r.get('email') or '').strip().lower()
        np = _normalize_phone(r.get('phone') or '')
        nn = _normalize_name(r.get('name') or '')
        return (ne or None, np or None, nn or None)

    # Group by identity: prefer email, then phone, then name
    by_key = {}
    for r in rows:
        k = key_for(r)
        if not k[0] and not k[1] and not k[2]:
            continue
        if k not in by_key:
            by_key[k] = []
        by_key[k].append(r)

    for key, group in by_key.items():
        if not group:
            continue
        first = group[0]
        name = (first.get('name') or '').strip() or '—'
        email = (first.get('email') or '').strip()
        phone = (first.get('phone') or '').strip()[:32]

        # Find existing client by same identity (email or phone or name) for this company
        existing = None
        if email:
            existing = Client.objects.filter(company_id=company.id).filter(email__iexact=email).first()
        if not existing and phone:
            existing = Client.objects.filter(company_id=company.id).filter(phone=phone).first()
        if not existing and name and name != '—':
            existing = Client.objects.filter(company_id=company.id).filter(name__iexact=name).first()

        def _serialize_dt(dt):
            if dt is None:
                return None
            if hasattr(dt, 'isoformat'):
                return dt.isoformat()
            return str(dt) if dt else None

        # Build entries for all rows; prefer as primary one that has a creator so "Created by" is shown when possible
        entries = []
        for r in group:
            entry = {
                'app': r.get('app_label', ''),
                'label': r.get('record_label', ''),
                'url': r.get('record_url', ''),
                'record_id': r.get('record_id', ''),
                'created_at': _serialize_dt(r.get('created_at')),
                'created_by': (r.get('created_by_name', '') or r.get('created_by', '') or '').strip(),
            }
            entries.append(entry)
        # Prefer primary = first entry that has created_by set so source_record_created_by is populated
        primary = next((e for e in entries if (e.get('created_by') or '').strip()), None) or (entries[0] if entries else None)
        other_sources = [e for e in entries if e is not primary]

        if existing:
            if existing.other_sources is None:
                existing.other_sources = []
            # Preserve "Clients" for manual clients: if they had no source, record that they came from Clients app before applying discovered primary
            if not existing.source_record_url and not existing.source_app:
                clients_entry = {'app': 'Clients', 'label': '', 'url': ''}
                has_clients = any((s.get('app') or '').strip() == 'Clients' for s in existing.other_sources)
                if not has_clients:
                    existing.other_sources.append(clients_entry)
                    updated += 1
            seen_urls = {existing.source_record_url} if existing.source_record_url else set()
            for s in existing.other_sources:
                u = s.get('url') or ''
                if u:
                    seen_urls.add(u)
            for s in other_sources:
                u = s.get('url') or ''
                if u and u not in seen_urls:
                    existing.other_sources.append(s)
                    seen_urls.add(u)
                    updated += 1
            if primary and primary.get('url') and primary['url'] not in seen_urls:
                if not existing.source_record_url:
                    existing.source_app = primary.get('app', '')
                    existing.source_record_id = str(primary.get('record_id', '') or first.get('record_id', ''))
                    existing.source_record_url = primary.get('url', '')
                    existing.source_record_label = primary.get('label', '')
                    ca = primary.get('created_at')
                    if hasattr(ca, 'year'):  # datetime
                        existing.source_record_created_at = ca
                    elif isinstance(ca, str) and ca:
                        from django.utils.dateparse import parse_datetime
                        existing.source_record_created_at = parse_datetime(ca)
                    existing.source_record_created_by = primary.get('created_by', '') or ''
                    updated += 1
                else:
                    existing.other_sources.insert(0, primary)
                    updated += 1
            # Backfill source_record_created_by when empty but we have creator in any source
            if not (existing.source_record_created_by or '').strip():
                fill = (primary.get('created_by', '') or '').strip() if primary else ''
                if not fill and (existing.other_sources or []):
                    for s in existing.other_sources:
                        fill = (s.get('created_by') or s.get('created_by_name') or '').strip()
                        if fill:
                            break
                if fill:
                    existing.source_record_created_by = fill
                    updated += 1
            existing.save()
            continue

        # Create new client
        ca = primary.get('created_at') if primary else None
        created_at_dt = None
        if ca and hasattr(ca, 'year'):
            created_at_dt = ca
        elif ca and isinstance(ca, str):
            from django.utils.dateparse import parse_datetime
            created_at_dt = parse_datetime(ca)
        client = Client(
            company=company,
            name=name,
            email=email,
            phone=phone,
            source_app=primary.get('app', '') if primary else '',
            source_record_id=str(primary.get('record_id', '') or (first.get('record_id', '') if first else '')),
            source_record_url=primary.get('url', '') if primary else '',
            source_record_label=primary.get('label', '') if primary else '',
            source_record_created_at=created_at_dt,
            source_record_created_by=(primary.get('created_by', '') or '') if primary else '',
            other_sources=other_sources,
        )
        client.save()
        created += 1

    qs = for_user_queryset(Client, user, request, account_lookup='company__account')
    return qs, {'synced': len(rows), 'created': created, 'updated': updated}
