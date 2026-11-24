"""
Smart Payroll Services
====================
Service functions for payroll records management.
"""

import hashlib
import secrets
from datetime import date, timedelta
from typing import Optional, Dict, Any

from django.db.models import Count, Sum, Q
from django.utils import timezone

from .models import (
    PayrollRecord,
    PayrollRecordAccessLog,
    PayrollRecordShare,
    PayrollNotification,
)


def create_notification(
    company,
    user,
    notification_type: str,
    title: str,
    message: str,
    record: Optional[PayrollRecord] = None,
    link: str = '',
    priority: str = 'normal'
) -> PayrollNotification:
    """
    Create a payroll notification for a user.
    
    Args:
        company: Company profile
        user: User to notify
        notification_type: Type of notification
        title: Notification title
        message: Notification message
        record: Related payroll record (optional)
        link: Link to navigate to
        priority: Priority level (low, normal, high, urgent)
    
    Returns:
        Created notification instance
    """
    notification = PayrollNotification.objects.create(
        account=company.account if hasattr(company, 'account') else None,
        company=company,
        user=user,
        notification_type=notification_type,
        title=title,
        message=message,
        record=record,
        link=link,
        priority=priority,
    )
    return notification


def log_access(
    request,
    record: PayrollRecord,
    action: str
) -> PayrollRecordAccessLog:
    """
    Log access to a payroll record.
    
    Args:
        request: HTTP request
        record: Payroll record being accessed
        action: Action performed (view, download, preview, etc.)
    
    Returns:
        Created access log instance
    """
    ip_address = None
    user_agent = ''
    session_id = ''
    
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = request.META.get('REMOTE_ADDR')
        
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:500]
        session_key = request.session.session_key
        if session_key:
            session_id = session_key
    
    access_log = PayrollRecordAccessLog.objects.create(
        account=record.account,
        company=record.company,
        user=request.user if request and hasattr(request, 'user') else None,
        record=record,
        action=action,
        ip_address=ip_address,
        user_agent=user_agent,
        session_id=session_id,
    )
    return access_log


def generate_share_link(
    record: PayrollRecord,
    shared_by,
    shared_with=None,
    shared_with_email: str = '',
    permission_view: bool = True,
    permission_download: bool = True,
    permission_print: bool = False,
    expires_in_days: Optional[int] = None,
    max_access_count: int = 0
) -> PayrollRecordShare:
    """
    Generate a share link for a payroll record.
    
    Args:
        record: Payroll record to share
        shared_by: User sharing the record
        shared_with: User to share with (optional)
        shared_with_email: Email to share with (optional)
        permission_view: Allow viewing
        permission_download: Allow downloading
        permission_print: Allow printing
        expires_in_days: Days until link expires (None for no expiration)
        max_access_count: Max number of times link can be accessed (0 for unlimited)
    
    Returns:
        Created share instance with token
    """
    token = secrets.token_urlsafe(32)
    
    expires_at = None
    if expires_in_days:
        expires_at = timezone.now() + timedelta(days=expires_in_days)
    
    share = PayrollRecordShare.objects.create(
        account=record.account,
        company=record.company,
        record=record,
        shared_by=shared_by,
        shared_with=shared_with,
        shared_with_email=shared_with_email,
        share_token=token,
        expires_at=expires_at,
        max_access_count=max_access_count,
        permission_view=permission_view,
        permission_download=permission_download,
        permission_print=permission_print,
    )
    return share


def calculate_record_stats(company) -> Dict[str, Any]:
    """
    Calculate statistics for payroll records using database aggregation.
    
    Args:
        company: Company profile
    
    Returns:
        Dictionary with statistics
    """
    records_qs = PayrollRecord.objects.filter(
        company=company, is_deleted=False
    )
    
    total_records = records_qs.count()
    
    total_size_agg = records_qs.aggregate(total=Sum('file_size'))
    total_size = total_size_agg['total'] or 0
    
    total_views_agg = records_qs.aggregate(total=Sum('view_count'))
    total_views = total_views_agg['total'] or 0
    
    total_downloads_agg = records_qs.aggregate(total=Sum('download_count'))
    total_downloads = total_downloads_agg['total'] or 0
    
    by_type = {}
    type_counts = records_qs.values('file_type').annotate(count=Count('id'))
    for item in type_counts:
        ft = item['file_type']
        label = dict(PayrollRecord.FILE_TYPE_CHOICES).get(ft, ft)
        by_type[ft] = {'label': label, 'count': item['count']}
    
    by_status = {}
    status_counts = records_qs.values('status').annotate(count=Count('id'))
    for item in status_counts:
        status = item['status']
        label = dict(PayrollRecord.STATUS_CHOICES).get(status, status)
        by_status[status] = {'label': label, 'count': item['count']}
    
    by_record_type = {}
    record_type_counts = records_qs.values('record_type').annotate(count=Count('id'))
    for item in record_type_counts:
        rt = item['record_type']
        label = dict(PayrollRecord.RECORD_TYPE_CHOICES).get(rt, rt)
        by_record_type[rt] = {'label': label, 'count': item['count']}
    
    starred_count = records_qs.filter(is_starred=True).count()
    archived_count = records_qs.filter(is_archived=True).count()
    public_count = records_qs.filter(is_public=True).count()
    
    recent_uploads = list(records_qs.order_by('-created_at')[:5])
    most_viewed = list(records_qs.order_by('-view_count')[:5])
    most_downloaded = list(records_qs.order_by('-download_count')[:5])
    
    return {
        'total_records': total_records,
        'total_size': total_size,
        'total_size_display': _format_file_size(total_size),
        'by_type': by_type,
        'by_status': by_status,
        'by_record_type': by_record_type,
        'starred_count': starred_count,
        'archived_count': archived_count,
        'public_count': public_count,
        'total_views': total_views,
        'total_downloads': total_downloads,
        'recent_uploads': recent_uploads,
        'most_viewed': most_viewed,
        'most_downloaded': most_downloaded,
    }


def _format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def get_record_by_hash(file_hash: str, company) -> Optional[PayrollRecord]:
    """
    Get payroll record by file hash.
    
    Args:
        file_hash: SHA256 hash of file
        company: Company profile
    
    Returns:
        PayrollRecord if found, None otherwise
    """
    try:
        return PayrollRecord.objects.get(
            company=company,
            file_hash=file_hash,
            is_deleted=False
        )
    except PayrollRecord.DoesNotExist:
        return None


def check_duplicate_file(file_hash: str, company) -> Optional[PayrollRecord]:
    """
    Check if a file with the same hash already exists.
    
    Args:
        file_hash: SHA256 hash of file
        company: Company profile
    
    Returns:
        Existing PayrollRecord if duplicate found, None otherwise
    """
    return get_record_by_hash(file_hash, company)


def bulk_archive_records(record_ids: list, company) -> int:
    """
    Archive multiple payroll records.
    
    Args:
        record_ids: List of record IDs
        company: Company profile
    
    Returns:
        Number of records archived
    """
    count = PayrollRecord.objects.filter(
        id__in=record_ids,
        company=company,
        is_deleted=False
    ).update(
        is_archived=True,
        status='archived',
        updated_at=timezone.now()
    )
    return count


def bulk_delete_records(record_ids: list, company) -> int:
    """
    Soft delete multiple payroll records.
    
    Args:
        record_ids: List of record IDs
        company: Company profile
    
    Returns:
        Number of records deleted
    """
    count = PayrollRecord.objects.filter(
        id__in=record_ids,
        company=company,
        is_deleted=False
    ).update(
        is_deleted=True,
        updated_at=timezone.now()
    )
    return count


def cleanup_expired_shares() -> int:
    """
    Clean up expired share links.
    
    Returns:
        Number of shares deactivated
    """
    count = PayrollRecordShare.objects.filter(
        is_active=True,
        is_deleted=False
    ).exclude(
        expires_at__isnull=True
    ).filter(
        expires_at__lt=timezone.now()
    ).update(
        is_active=False,
        updated_at=timezone.now()
    )
    return count


def get_user_unread_notifications(user) -> list:
    """
    Get unread notifications for a user.
    
    Args:
        user: User instance
    
    Returns:
        List of unread notifications
    """
    return list(PayrollNotification.objects.filter(
        user=user,
        is_read=False,
        is_deleted=False
    ).order_by('-created_at')[:20])


def mark_notification_as_read(notification_id: int, user) -> bool:
    """
    Mark a notification as read.
    
    Args:
        notification_id: Notification ID
        user: User instance
    
    Returns:
        True if marked as read, False otherwise
    """
    try:
        notification = PayrollNotification.objects.get(
            id=notification_id,
            user=user
        )
        notification.mark_as_read()
        return True
    except PayrollNotification.DoesNotExist:
        return False


def get_access_summary(record: PayrollRecord) -> Dict[str, Any]:
    """
    Get access summary for a payroll record.
    
    Args:
        record: PayrollRecord instance
    
    Returns:
        Dictionary with access summary
    """
    logs = PayrollRecordAccessLog.objects.filter(record=record)
    
    total_views = logs.filter(action='view').count()
    total_downloads = logs.filter(action='download').count()
    total_previews = logs.filter(action='preview').count()
    
    unique_users = logs.values('user').distinct().count()
    
    recent_logs = logs.order_by('-created_at')[:10]
    
    return {
        'total_views': total_views,
        'total_downloads': total_downloads,
        'total_previews': total_previews,
        'unique_users': unique_users,
        'recent_logs': recent_logs,
    }
