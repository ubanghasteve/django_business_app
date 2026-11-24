"""Notification list page - full view with View more."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def notification_list_page(request):
    """Full notification page with all notifications."""
    return render(request, 'notifications/notification_list.html', {
        'page_title': 'Notifications',
        'breadcrumb': 'Notifications',
    })
