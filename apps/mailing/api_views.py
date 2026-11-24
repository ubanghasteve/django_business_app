"""
Bulk mailing API: recipients list and send email / send SMS.
Recipients are built from Clients, optional Team (User/SubUser), and optional Employees.
Email is sent sequentially in the main request thread so Django's SMTP backend delivers reliably.
"""
import json
import re

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives, get_connection
from email.mime.image import MIMEImage
from email.utils import formataddr
from html import escape as html_escape
import mimetypes
import os

from apps.clients.models import Client
from apps.core.ownership import for_user_queryset, get_account_for_user
from apps.core.utils import get_company_profile_for_user


def _require_mailing_access(request):
    """Require login and mailing.use_bulk_mailing."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    if not request.user.has_perm('mailing.use_bulk_mailing'):
        return JsonResponse({'error': 'You do not have permission to use bulk mailing'}, status=403)
    return None


def _normalize_phone(phone):
    """Return digits only for SMS; empty string if not valid."""
    if not phone or not isinstance(phone, str):
        return ''
    digits = re.sub(r'\D', '', phone.strip())
    return digits if len(digits) >= 10 else ''


def _is_valid_email(addr):
    """True if addr is a non-empty string that looks like an email (contains @)."""
    if not addr or not isinstance(addr, str):
        return False
    s = (addr or '').strip()
    return len(s) > 0 and '@' in s and s.index('@') > 0 and '.' in s.split('@')[-1]


def _is_valid_phone(phone):
    """True if phone has at least 10 digits (can be used for SMS)."""
    return bool(_normalize_phone(phone))


def _has_contact(r):
    """True if recipient has at least one of: valid email or valid phone."""
    email = (r.get('email') or '').strip()
    phone = (r.get('phone') or '').strip()
    return _is_valid_email(email) or _is_valid_phone(phone)


def _parse_additional_emails(raw_list, max_count=200):
    """
    Parse additional_emails: list of strings or newline/comma-separated string.
    Returns list of (email, '') for valid unique emails, up to max_count.
    """
    if not raw_list:
        return []
    if isinstance(raw_list, str):
        raw_list = [raw_list]
    if not isinstance(raw_list, (list, tuple)):
        return []
    seen = set()
    out = []
    email_re = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
    for item in raw_list:
        item = item if isinstance(item, str) else (str(item) if item is not None else '')
        if not item:
            continue
        for part in re.split(r'[\s,;]+', item.strip()):
            part = part.strip()
            if not part or len(out) >= max_count:
                continue
            if email_re.match(part) and part.lower() not in seen:
                seen.add(part.lower())
                out.append((part, ''))
    return out


def _parse_additional_phones(raw_list, max_count=100):
    """
    Parse additional_phones: list of strings or newline/comma-separated string.
    Returns list of (normalized_digits, '') for valid unique phones, up to max_count.
    """
    if not raw_list:
        return []
    if isinstance(raw_list, str):
        raw_list = [raw_list]
    if not isinstance(raw_list, (list, tuple)):
        return []
    seen = set()
    out = []
    for item in raw_list:
        item = item if isinstance(item, str) else (str(item) if item is not None else '')
        if not item:
            continue
        for part in re.split(r'[\s,;]+', item.strip()):
            digits = _normalize_phone(part)
            if not digits or digits in seen or len(out) >= max_count:
                continue
            seen.add(digits)
            out.append((digits, ''))
    return out


def _collect_recipients(request, include_team=None, include_employees=None):
    """
    Build unified recipient list: clients + optional team users + optional employees.
    Each item: { "type": "client"|"user"|"employee", "id": int, "name": str, "email": str, "phone": str }.
    If include_team/include_employees are passed, they override request.GET (for initial page load).
    """
    company = get_company_profile_for_user(request.user, request)
    account = get_account_for_user(request.user)
    if not account:
        return []

    recipients = []
    if include_team is None:
        include_team = request.GET.get('include_team', 'false').lower() == 'true'
    if include_employees is None:
        include_employees = request.GET.get('include_employees', 'false').lower() == 'true'

    # Clients (tenant-scoped, visibility-aware)
    clients_qs = for_user_queryset(Client, request.user, request, account_lookup='company__account')
    for c in clients_qs.only('id', 'name', 'email', 'phone'):
        recipients.append({
            'type': 'client',
            'id': c.id,
            'name': (c.name or '').strip() or '(No name)',
            'email': (c.email or '').strip(),
            'phone': (c.phone or '').strip(),
            'source_app': 'Clients',
        })

    # Team: users in same account (owner + SubUsers as team members); dedupe by user id
    if include_team and request.user.has_perm('accounts.view_subuser'):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        from apps.accounts.models import SubUser
        added_user_ids = set()
        # Account owner (as User)
        if account.owner_id:
            u = User.objects.filter(pk=account.owner_id).first()
            if u and u.is_active and u.id not in added_user_ids:
                added_user_ids.add(u.id)
                recipients.append({
                    'type': 'user',
                    'id': u.id,
                    'name': (u.get_full_name() or u.email or '').strip() or '(No name)',
                    'email': (u.email or '').strip(),
                    'phone': (getattr(u, 'phone') or '').strip(),
                    'source_app': 'Team',
                })
        # SubUsers (team members): linked_user => type 'user', else type 'subuser'
        for sub in SubUser.objects.filter(account_owner_id=account.owner_id, is_active=True).select_related('linked_user'):
            if sub.linked_user_id:
                u = sub.linked_user
                if u.id not in added_user_ids:
                    added_user_ids.add(u.id)
                    recipients.append({
                        'type': 'user',
                        'id': u.id,
                        'name': (u.get_full_name() or u.email or '').strip() or (sub.full_name or '').strip() or '(No name)',
                        'email': (u.email or sub.email or '').strip(),
                        'phone': (getattr(u, 'phone') or '').strip(),
                        'source_app': 'Team',
                    })
            else:
                recipients.append({
                    'type': 'subuser',
                    'id': sub.id,
                    'name': (sub.full_name or sub.email or '').strip() or '(No name)',
                    'email': (sub.email or '').strip(),
                    'phone': (getattr(sub, 'phone', '') or '').strip(),
                    'source_app': 'Team',
                })

    # Employees (HR)
    if include_employees and company and request.user.has_perm('hr_staff.view_employee'):
        from apps.hr_staff.models import Employee
        from apps.hr_staff.querysets import get_employee_queryset_for_user
        emp_qs = get_employee_queryset_for_user(request.user, request, account_lookup='account')
        for e in emp_qs.only('id', 'first_name', 'last_name', 'email', 'phone'):
            name = f'{e.first_name or ""} {e.last_name or ""}'.strip() or (e.email or '(No name)')
            recipients.append({
                'type': 'employee',
                'id': e.id,
                'name': name,
                'email': (e.email or '').strip(),
                'phone': (e.phone or '').strip(),
                'source_app': 'HR Staff',
            })

    # Invoices app: client contact from each invoice (account-scoped)
    try:
        from apps.invoices.models import Invoice as InvoiceModel
        inv_qs = for_user_queryset(InvoiceModel, request.user, request, account_lookup='account')
        for inv in inv_qs.only('id', 'client_name', 'client_email', 'client_phone'):
            email = (inv.client_email or '').strip()
            phone = (inv.client_phone or '').strip()
            name = (inv.client_name or '').strip() or '(No name)'
            if _is_valid_email(email) or _is_valid_phone(phone):
                recipients.append({
                    'type': 'invoice',
                    'id': inv.id,
                    'name': name,
                    'email': email,
                    'phone': phone,
                    'source_app': 'Invoices',
                })
    except Exception:
        pass

    # Receipts app: client contact from each receipt (account-scoped; receipts often have phone, not email)
    try:
        from apps.receipts.models import Receipt as ReceiptModel
        rec_qs = for_user_queryset(ReceiptModel, request.user, request, account_lookup='account')
        for rec in rec_qs.only('id', 'client_name', 'client_phone'):
            phone = (rec.client_phone or '').strip()
            name = (rec.client_name or '').strip() or '(No name)'
            if _is_valid_phone(phone):
                recipients.append({
                    'type': 'receipt',
                    'id': rec.id,
                    'name': name,
                    'email': '',
                    'phone': phone,
                    'source_app': 'Receipts',
                })
    except Exception:
        pass

    # Job Orders app: customers from waybills/receipts/invoices (created_by in current account)
    try:
        from apps.job_orders.models import Customer as JobCustomer
        from apps.job_orders.models import Waybill as JobWaybill
        from apps.job_orders.models import Receipt as JobReceipt
        from apps.job_orders.models import Invoice as JobInvoice
        account_user_ids = set()
        if account.owner_id:
            account_user_ids.add(account.owner_id)
        from apps.accounts.models import SubUser
        for sub in SubUser.objects.filter(account_owner_id=account.owner_id, is_active=True).values_list('linked_user_id', flat=True):
            if sub:
                account_user_ids.add(sub)
        customer_ids = set()
        for wb in JobWaybill.objects.filter(created_by_id__in=account_user_ids).values_list('customer_id', flat=True).distinct():
            if wb:
                customer_ids.add(wb)
        for r in JobReceipt.objects.filter(created_by_id__in=account_user_ids).values_list('customer_id', flat=True).distinct():
            if r:
                customer_ids.add(r)
        for inv in JobInvoice.objects.filter(created_by_id__in=account_user_ids).values_list('customer_id', flat=True).distinct():
            if inv:
                customer_ids.add(inv)
        for c in JobCustomer.objects.filter(id__in=customer_ids).only('id', 'name', 'email', 'phone'):
            email = (c.email or '').strip()
            phone = (c.phone or '').strip()
            name = (c.name or '').strip() or '(No name)'
            if _is_valid_email(email) or _is_valid_phone(phone):
                recipients.append({
                    'type': 'job_customer',
                    'id': c.id,
                    'name': name,
                    'email': email,
                    'phone': phone,
                    'source_app': 'Job Orders',
                })
    except Exception:
        pass

    # Inventory app: vendor/supplier phone (account-scoped)
    try:
        from apps.inventory.models import Inventory as InventoryModel
        inv_qs = for_user_queryset(InventoryModel, request.user, request, account_lookup='account')
        for rec in inv_qs.only('id', 'company_name', 'vendor', 'phone_number'):
            phone = (rec.phone_number or '').strip()
            name = (rec.vendor or rec.company_name or '').strip() or '(No name)'
            if _is_valid_phone(phone):
                recipients.append({
                    'type': 'inventory',
                    'id': rec.id,
                    'name': name,
                    'email': '',
                    'phone': phone,
                    'source_app': 'Inventory',
                })
    except Exception:
        pass

    # Only include recipients that have at least one contact: valid email or valid phone (10+ digits)
    with_contact = [r for r in recipients if _has_contact(r)]

    # Deduplicate: same person can appear from Clients, Invoices, Job Orders, etc. Keep one row per identity and list all source apps in "From app".
    identity_to_index = {}  # email_lower or phone_norm -> index in deduped
    deduped = []
    for r in with_contact:
        email_raw = (r.get('email') or '').strip()
        email_lower = email_raw.lower() if email_raw else ''
        phone_norm = _normalize_phone(r.get('phone') or '')
        new_app = (r.get('source_app') or '').strip()
        idx = None
        if email_lower and email_lower in identity_to_index:
            idx = identity_to_index[email_lower]
        elif phone_norm and phone_norm in identity_to_index:
            idx = identity_to_index[phone_norm]
        if idx is not None:
            # Merge: add this app to the existing row's "From app" list
            existing = (deduped[idx].get('source_app') or '').strip()
            apps = [x.strip() for x in existing.split(',') if x.strip()]
            if new_app and new_app not in apps:
                apps.append(new_app)
            deduped[idx]['source_app'] = ', '.join(apps)
            continue
        # First occurrence of this identity: add row and register email/phone
        row = dict(r)
        if new_app:
            row['source_app'] = new_app
        deduped.append(row)
        if email_lower:
            identity_to_index[email_lower] = len(deduped) - 1
        if phone_norm:
            identity_to_index[phone_norm] = len(deduped) - 1
    return deduped


def get_initial_recipients_for_page(request):
    """Return recipients for the bulk send page initial load (one DB round-trip, no extra API call)."""
    if not request.user.is_authenticated or not request.user.has_perm('mailing.use_bulk_mailing'):
        return []
    return _collect_recipients(request, include_team=True, include_employees=False)


@login_required
@require_http_methods(['GET'])
def recipients_api(request):
    """GET /api/mailing/recipients/ - list all recipients (clients + optional team + employees)."""
    err = _require_mailing_access(request)
    if err:
        return err
    recipients = _collect_recipients(request)
    return JsonResponse({'recipients': recipients})


def _normalize_recipients_payload(recipients):
    """
    Ensure recipients is always a list of { type, id } dicts.
    If the client sends a single object { type, id }, wrap it in a list so all are processed.
    """
    if not recipients:
        return []
    if isinstance(recipients, dict) and ('type' in recipients or 'id' in recipients):
        return [recipients]
    if isinstance(recipients, list):
        return [r for r in recipients if isinstance(r, dict) and (r.get('type') is not None or r.get('id') is not None)]
    return []


def _resolve_recipients_to_emails(request, recipients_payload):
    """
    recipients_payload: list of { "type": "client"|"user"|"employee", "id": int }.
    Returns list of (email, name) for each valid recipient with non-empty email.
    Deduplicates by lowercase email so the same mailbox is not sent twice.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    seen_emails_lower = set()
    out = []
    for r in recipients_payload:
        typ = (r.get('type') or 'client').lower()
        rid = r.get('id')
        if rid is None:
            continue
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            continue
        email = None
        name = ''
        if typ == 'client':
            qs = for_user_queryset(Client, request.user, request, account_lookup='company__account')
            obj = qs.filter(pk=rid).first()
            if obj:
                email = (obj.email or '').strip()
                name = (obj.name or '').strip()
        elif typ == 'user':
            acc = get_account_for_user(request.user)
            if acc:
                u = User.objects.filter(pk=rid, account=acc).first()
                if u and u.is_active:
                    email = (u.email or '').strip()
                    name = (u.get_full_name() or '').strip()
        elif typ == 'subuser':
            from apps.accounts.models import SubUser
            acc = get_account_for_user(request.user)
            if acc:
                sub = SubUser.objects.filter(account_owner_id=acc.owner_id, id=rid).first()
                if sub:
                    email = (sub.email or '').strip()
                    name = (sub.full_name or '').strip()
        elif typ == 'employee':
            if request.user.has_perm('hr_staff.view_employee'):
                from apps.hr_staff.models import Employee
                from apps.hr_staff.querysets import get_employee_queryset_for_user
                qs = get_employee_queryset_for_user(request.user, request, account_lookup='account')
                obj = qs.filter(pk=rid).first()
                if obj:
                    email = (obj.email or '').strip()
                    name = f'{obj.first_name or ""} {obj.last_name or ""}'.strip()
        elif typ == 'invoice':
            from apps.invoices.models import Invoice as InvoiceModel
            inv_qs = for_user_queryset(InvoiceModel, request.user, request, account_lookup='account')
            obj = inv_qs.filter(pk=rid).only('client_email', 'client_name').first()
            if obj:
                email = (obj.client_email or '').strip()
                name = (obj.client_name or '').strip()
        elif typ == 'job_customer':
            from apps.job_orders.models import Customer as JobCustomer
            from apps.job_orders.models import Waybill as JobWaybill
            from apps.job_orders.models import Receipt as JobReceipt
            from apps.job_orders.models import Invoice as JobInvoice
            account = get_account_for_user(request.user)
            if account:
                account_user_ids = {account.owner_id} if account.owner_id else set()
                from apps.accounts.models import SubUser
                for uid in SubUser.objects.filter(account_owner_id=account.owner_id, is_active=True).values_list('linked_user_id', flat=True):
                    if uid:
                        account_user_ids.add(uid)
                allowed = (JobWaybill.objects.filter(customer_id=rid, created_by_id__in=account_user_ids).exists() or
                           JobReceipt.objects.filter(customer_id=rid, created_by_id__in=account_user_ids).exists() or
                           JobInvoice.objects.filter(customer_id=rid, created_by_id__in=account_user_ids).exists())
                if allowed:
                    obj = JobCustomer.objects.filter(pk=rid).only('email', 'name').first()
                    if obj:
                        email = (obj.email or '').strip()
                        name = (obj.name or '').strip()
        if email and '@' in email:
            email_lower = email.lower()
            if email_lower not in seen_emails_lower:
                seen_emails_lower.add(email_lower)
                out.append((email, name))
    return out


def _resolve_recipients_to_phones(request, recipients_payload):
    """
    Same payload format. Returns list of (phone_digits, name) for valid SMS.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    seen_phones = set()
    out = []
    for r in recipients_payload:
        typ = (r.get('type') or 'client').lower()
        rid = r.get('id')
        if rid is None:
            continue
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            continue
        phone = ''
        name = ''
        if typ == 'client':
            qs = for_user_queryset(Client, request.user, request, account_lookup='company__account')
            obj = qs.filter(pk=rid).first()
            if obj:
                phone = _normalize_phone(obj.phone)
                name = (obj.name or '').strip()
        elif typ == 'user':
            acc = get_account_for_user(request.user)
            if acc and User.objects.filter(pk=rid, account=acc).exists():
                u = User.objects.filter(pk=rid).first()
                if u and u.is_active:
                    phone = _normalize_phone(getattr(u, 'phone', None))
                    name = (u.get_full_name() or '').strip()
        elif typ == 'subuser':
            from apps.accounts.models import SubUser
            acc = get_account_for_user(request.user)
            if acc:
                sub = SubUser.objects.filter(account_owner_id=acc.owner_id, id=rid).first()
                if sub:
                    phone = _normalize_phone(getattr(sub, 'phone', None))
                    name = (sub.full_name or '').strip()
        elif typ == 'employee':
            if request.user.has_perm('hr_staff.view_employee'):
                from apps.hr_staff.models import Employee
                from apps.hr_staff.querysets import get_employee_queryset_for_user
                qs = get_employee_queryset_for_user(request.user, request, account_lookup='account')
                obj = qs.filter(pk=rid).first()
                if obj:
                    phone = _normalize_phone(obj.phone)
                    name = f'{obj.first_name or ""} {obj.last_name or ""}'.strip()
        elif typ == 'invoice':
            from apps.invoices.models import Invoice as InvoiceModel
            inv_qs = for_user_queryset(InvoiceModel, request.user, request, account_lookup='account')
            obj = inv_qs.filter(pk=rid).only('client_phone', 'client_name').first()
            if obj:
                phone = _normalize_phone(obj.client_phone)
                name = (obj.client_name or '').strip()
        elif typ == 'receipt':
            from apps.receipts.models import Receipt as ReceiptModel
            rec_qs = for_user_queryset(ReceiptModel, request.user, request, account_lookup='account')
            obj = rec_qs.filter(pk=rid).only('client_phone', 'client_name').first()
            if obj:
                phone = _normalize_phone(obj.client_phone)
                name = (obj.client_name or '').strip()
        elif typ == 'job_customer':
            from apps.job_orders.models import Customer as JobCustomer
            from apps.job_orders.models import Waybill as JobWaybill
            from apps.job_orders.models import Receipt as JobReceipt
            from apps.job_orders.models import Invoice as JobInvoice
            account = get_account_for_user(request.user)
            if account:
                account_user_ids = {account.owner_id} if account.owner_id else set()
                from apps.accounts.models import SubUser
                for uid in SubUser.objects.filter(account_owner_id=account.owner_id, is_active=True).values_list('linked_user_id', flat=True):
                    if uid:
                        account_user_ids.add(uid)
                allowed = (JobWaybill.objects.filter(customer_id=rid, created_by_id__in=account_user_ids).exists() or
                           JobReceipt.objects.filter(customer_id=rid, created_by_id__in=account_user_ids).exists() or
                           JobInvoice.objects.filter(customer_id=rid, created_by_id__in=account_user_ids).exists())
                if allowed:
                    obj = JobCustomer.objects.filter(pk=rid).only('phone', 'name').first()
                    if obj:
                        phone = _normalize_phone(obj.phone)
                        name = (obj.name or '').strip()
        elif typ == 'inventory':
            from apps.inventory.models import Inventory as InventoryModel
            inv_qs = for_user_queryset(InventoryModel, request.user, request, account_lookup='account')
            obj = inv_qs.filter(pk=rid).only('phone_number', 'vendor', 'company_name').first()
            if obj:
                phone = _normalize_phone(obj.phone_number)
                name = (obj.vendor or obj.company_name or '').strip()
        if phone and phone not in seen_phones:
            seen_phones.add(phone)
            out.append((phone, name))
    return out


@login_required
@require_http_methods(['POST'])
def send_bulk_email_api(request):
    """
    POST /api/mailing/send-email/
    Body (JSON): {
      "recipients": [ { "type": "client", "id": 1 }, ... ],
      "subject": "...",
      "message": "...",
      "additional_emails": ["a@b.com"] or "a@b.com, b@c.com"  (optional)
    }
    Only the selected recipients (ids in recipients) plus additional_emails receive the message.
    """
    err = _require_mailing_access(request)
    if err:
        return err
    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    recipients = _normalize_recipients_payload(body.get('recipients') or [])
    subject = (body.get('subject') or '').strip()
    message = (body.get('message') or '').strip()
    additional_emails_raw = body.get('additional_emails')
    if not subject:
        return JsonResponse({'success': False, 'error': 'Subject is required'}, status=400)
    if not message:
        return JsonResponse({'success': False, 'error': 'Message is required'}, status=400)

    # Resolve every selected recipient (table) + additional emails into one deduplicated list
    email_list = _resolve_recipients_to_emails(request, recipients)
    additional = _parse_additional_emails(additional_emails_raw, max_count=200)
    seen = {e[0].lower() for e in email_list}
    for email, _ in additional:
        if email and isinstance(email, str) and email.lower() not in seen:
            seen.add(email.lower())
            email_list.append((email, ''))
    if len(email_list) > 200:
        email_list = email_list[:200]
    if not email_list:
        return JsonResponse({
            'success': False,
            'error': 'No recipients. Select at least one recipient and/or add additional email addresses.',
        }, status=400)

    # Per-account company profile: recipients see company name and company email in From, not the app's.
    company = get_company_profile_for_user(request.user, request)
    if company:
        company.refresh_from_db(fields=['email', 'company_name'])  # ensure we use latest saved Company Profile email
    company_email = (getattr(company, 'email', None) or '').strip() if company else ''
    company_name = (getattr(company, 'company_name', None) or '').strip() if company else ''
    default_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', '') or 'noreply@example.com'
    # Prefer company email so the address in angle brackets is the company's, not the app's.
    # Fallback: if Company Profile has no email set, use account owner's email so the bracket still shows the account's email.
    sender_email = default_email
    if company_email and '@' in company_email:
        sender_email = company_email
    else:
        account = get_account_for_user(request.user)
        if account and getattr(account, 'owner_id', None):
            from django.contrib.auth import get_user_model
            User = get_user_model()
            owner = User.objects.filter(pk=account.owner_id).only('email').first()
            if owner and (getattr(owner, 'email', None) or '').strip() and '@' in (owner.email or ''):
                sender_email = (owner.email or '').strip()
    if company_name:
        from_email = formataddr((company_name, sender_email))
    else:
        from_email = sender_email
    reply_to = [company_email] if (company_email and '@' in company_email) else None

    # Build HTML body with company branding: logo, name, and contact details (address, phone, email) in a clear block, then the message.
    # Prefer embedding the logo as inline attachment (cid:) so it displays in email clients that block remote images.
    logo_url = None
    logo_inline_attachment = None  # MIMEImage with Content-ID for cid:companylogo
    company_address = ''
    company_phone = ''
    company_website = ''
    company_email_display = company_email
    primary_color = '#e65c00'  # fallback orange for company name
    if company:
        if getattr(company, 'logo', None) and company.logo:
            try:
                logo_file = company.logo
                if hasattr(logo_file, 'path') and os.path.isfile(logo_file.path):
                    with open(logo_file.path, 'rb') as f:
                        logo_bytes = f.read()
                    ext = os.path.splitext(logo_file.name or '')[1].lower() or '.png'
                    subtype = (mimetypes.types_map.get(ext) or 'image/png').split('/')[-1]
                    if subtype == 'jpeg':
                        subtype = 'jpeg'
                    img = MIMEImage(logo_bytes, _subtype=subtype)
                    img.add_header('Content-Disposition', 'inline', filename='company-logo')
                    img.add_header('Content-ID', '<companylogo>')
                    logo_inline_attachment = img
                else:
                    logo_url = request.build_absolute_uri(company.logo.url)
            except Exception:
                try:
                    logo_url = request.build_absolute_uri(company.logo.url)
                except Exception:
                    logo_url = None
        company_address = (getattr(company, 'address', None) or '').strip() or ''
        if not company_address and any([
            getattr(company, 'address_line_1', None),
            getattr(company, 'city', None),
            getattr(company, 'country', None),
        ]):
            parts = []
            for f in ('address_line_1', 'address_line_2', 'city', 'state', 'postal_code', 'country'):
                v = (getattr(company, f, None) or '').strip()
                if v:
                    parts.append(v)
            company_address = ', '.join(parts)
        company_phone = (getattr(company, 'phone', None) or '').strip()
        company_website = (getattr(company, 'website', None) or '').strip()
        if not company_email_display and company:
            company_email_display = (company.email or '').strip()
        primary_color = (getattr(company, 'primary_color', None) or '').strip() or primary_color
        if primary_color and not primary_color.startswith('#'):
            primary_color = '#' + primary_color

    has_branding = bool(company_name or logo_url or logo_inline_attachment or company_address or company_phone or company_website or company_email_display)
    if has_branding:
        # Layout: logo left, company name + contact details right; then a line; then the message.
        # Use cid:companylogo when logo is embedded (so it shows in clients that block remote images).
        logo_cell = ''
        if logo_inline_attachment:
            logo_cell = (
                '<td style="vertical-align:top;padding-right:16px;">'
                '<img src="cid:companylogo" alt="%s" style="max-height:60px;max-width:140px;height:auto;display:block;" />'
                '</td>'
            ) % html_escape(company_name or 'Logo')
        elif logo_url:
            logo_cell = (
                '<td style="vertical-align:top;padding-right:16px;">'
                '<img src="%s" alt="%s" style="max-height:60px;max-width:140px;height:auto;display:block;" />'
                '</td>'
            ) % (html_escape(logo_url), html_escape(company_name or 'Logo'))
        contact_lines = []
        if company_name:
            contact_lines.append(
                '<p style="margin:0 0 6px 0;font-weight:bold;font-size:1.1em;text-transform:uppercase;color:%s;">%s</p>'
                % (html_escape(primary_color), html_escape(company_name))
            )
        if company_address:
            contact_lines.append(
                '<p style="margin:0 0 2px 0;font-size:0.9em;color:#666666;">%s</p>'
                % html_escape(company_address))
        if company_phone:
            contact_lines.append(
                '<p style="margin:0 0 2px 0;font-size:0.9em;color:#666666;">%s</p>'
                % html_escape(company_phone))
        if company_email_display and '@' in company_email_display:
            contact_lines.append(
                '<p style="margin:0 0 2px 0;font-size:0.9em;color:#666666;">%s</p>'
                % html_escape(company_email_display))
        if company_website:
            # Ensure URL has a scheme so it is clickable
            website_url = company_website.strip()
            if website_url and not any(website_url.startswith(p) for p in ('http://', 'https://')):
                website_url = 'https://' + website_url
            contact_lines.append(
                '<p style="margin:0 0 2px 0;font-size:0.9em;color:#666666;"><a href="%s" style="color:#666666;">%s</a></p>'
                % (html_escape(website_url), html_escape(company_website)))
        contact_cell = '<td style="vertical-align:top;">%s</td>' % ''.join(contact_lines) if contact_lines else ''
        if not contact_cell and logo_cell:
            contact_cell = '<td style="vertical-align:top;"></td>'
        brand_block = (
            '<table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:12px;"><tr>'
            + logo_cell
            + contact_cell
            + '</tr></table>'
            + '<hr style="border:none;border-top:1px solid #dddddd;margin:0 0 16px 0;" />'
        )
        body_html = (
            '<div style="font-family:sans-serif;max-width:600px;">'
            + brand_block
            + '<div style="white-space:pre-wrap;">%s</div></div>' % html_escape(message)
        )
    else:
        body_html = None

    sent = 0
    failed = 0
    conn = None
    try:
        conn = get_connection(fail_silently=True)
        for to_addr, _ in email_list:
            if not to_addr or '@' not in to_addr:
                failed += 1
                continue
            try:
                if body_html:
                    msg = EmailMultiAlternatives(
                        subject=subject,
                        body=message,
                        from_email=from_email,
                        to=[to_addr],
                        reply_to=reply_to,
                    )
                    msg.attach_alternative(body_html, 'text/html')
                    if logo_inline_attachment:
                        msg.attach(logo_inline_attachment)
                else:
                    msg = EmailMessage(
                        subject=subject,
                        body=message,
                        from_email=from_email,
                        to=[to_addr],
                        reply_to=reply_to,
                    )
                n = conn.send_messages([msg])
                if n:
                    sent += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
                # Reopen connection so one failure does not break the rest
                try:
                    if conn is not None:
                        conn.close()
                except Exception:
                    pass
                conn = get_connection(fail_silently=True)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return JsonResponse({
        'success': True,
        'sent': sent,
        'failed': failed,
        'total': len(email_list),
    })


@login_required
@require_http_methods(['POST'])
def send_bulk_sms_api(request):
    """
    POST /api/mailing/send-sms/
    Body (JSON): {
      "recipients": [ { "type": "client", "id": 1 }, ... ],
      "message": "...",
      "additional_phones": ["+1234567890"] or "1234567890, 0987654321"  (optional)
    }
    Only the selected recipients (ids in recipients) plus additional_phones receive the message.
    """
    err = _require_mailing_access(request)
    if err:
        return err

    twilio_account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None) or getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    twilio_auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', None) or getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    twilio_from = getattr(settings, 'TWILIO_PHONE_NUMBER', None) or getattr(settings, 'TWILIO_FROM', '')
    if not twilio_account_sid or not twilio_auth_token or not twilio_from:
        return JsonResponse({
            'success': False,
            'error': 'SMS is not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER in settings.',
        }, status=503)

    try:
        body = json.loads(request.body) if request.body else {}
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    recipients = _normalize_recipients_payload(body.get('recipients') or [])
    message = (body.get('message') or '').strip()
    additional_phones_raw = body.get('additional_phones')
    if not message:
        return JsonResponse({'success': False, 'error': 'Message is required'}, status=400)

    # Resolve every selected recipient (table) + additional phones into one deduplicated list
    phone_list = _resolve_recipients_to_phones(request, recipients)
    additional = _parse_additional_phones(additional_phones_raw, max_count=100)
    seen = {p[0] for p in phone_list}
    for phone, _ in additional:
        if phone and phone not in seen:
            seen.add(phone)
            phone_list.append((phone, ''))
    if len(phone_list) > 100:
        phone_list = phone_list[:100]
    if not phone_list:
        return JsonResponse({
            'success': False,
            'error': 'No recipients. Select at least one recipient and/or add additional phone numbers.',
        }, status=400)

    try:
        from twilio.rest import Client as TwilioClient
    except ImportError:
        return JsonResponse({'success': False, 'error': 'Twilio package not installed. Run: pip install twilio'}, status=503)

    client = TwilioClient(twilio_account_sid, twilio_auth_token)
    sent = 0
    failed = 0
    last_error = None
    for phone_digits, _ in phone_list:
        if not phone_digits or not isinstance(phone_digits, str):
            failed += 1
            continue
        phone_digits = (phone_digits or '').strip().lstrip('+')
        if len(phone_digits) < 10:
            failed += 1
            continue
        to_number = '+' + phone_digits
        try:
            client.messages.create(body=message, from_=twilio_from, to=to_number)
            sent += 1
        except Exception as e:
            failed += 1
            last_error = str(e)

    payload = {
        'success': True,
        'sent': sent,
        'failed': failed,
        'total': len(phone_list),
    }
    if failed and last_error:
        payload['last_error'] = last_error
    return JsonResponse(payload)
