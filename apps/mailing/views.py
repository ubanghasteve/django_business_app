from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import permission_required
from django.conf import settings
from email.utils import formataddr

from .api_views import get_initial_recipients_for_page
from apps.core.utils import get_company_profile_for_user
from apps.core.ownership import get_account_for_user


@login_required
@permission_required('mailing.use_bulk_mailing', raise_exception=True)
def bulk_send_page(request):
    """Bulk email/SMS page: select recipients and send. Recipients loaded server-side for instant display."""
    initial_recipients = get_initial_recipients_for_page(request)
    company = get_company_profile_for_user(request.user, request)
    if company:
        company.refresh_from_db(fields=['email', 'company_name'])
    company_email = (getattr(company, 'email', None) or '').strip() if company else ''
    company_name = (getattr(company, 'company_name', None) or '').strip() if company else ''
    default_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', '') or 'noreply@example.com'
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
        from_display = formataddr((company_name, sender_email))
    else:
        from_display = sender_email
    uses_company_email = (sender_email != default_email)
    email_host = (getattr(settings, 'EMAIL_HOST', None) or '').strip().lower()
    using_gmail_smtp = 'gmail' in email_host
    return render(request, 'mailing/bulk_send.html', {
        'mailing_active': True,
        'initial_recipients': initial_recipients,
        'mailing_from_display': from_display,
        'mailing_uses_company_email': uses_company_email,
        'mailing_app_email': default_email,
        'using_gmail_smtp': using_gmail_smtp,
    })
