"""
Activity Tracking Mixin and Utilities for Enhanced Audit Logging.

This module provides:
- ActivityTrackingMixin: A mixin for Django models to automatically track changes
- Helper functions for logging CRUD operations with detailed change tracking
- URL generation for linking activities to actual objects

Usage:
    class Invoice(ActivityTrackingMixin, models.Model):
        # ... your fields ...
        
        class Meta:
            # Optional: customize tracking
            activity_app_name = 'invoices'
            activity_model_name = 'Invoice'
"""

import json
import logging
from decimal import Decimal
from datetime import date, datetime
from django.db import models
from django.urls import reverse, NoReverseMatch
from django.forms.models import model_to_dict
from uuid import UUID

logger = logging.getLogger(__name__)


def serialize_value(value):
    """
    Serialize a value to a JSON-compatible format.
    Handles common Django field types.
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, models.Model):
        return str(value)
    if hasattr(value, '__iter__') and not isinstance(value, (str, bytes)):
        return [serialize_value(v) for v in value]
    return str(value)


def get_model_dict(instance, exclude_fields=None):
    """
    Convert a model instance to a dictionary with serializable values.
    
    Args:
        instance: Django model instance
        exclude_fields: List of field names to exclude
        
    Returns:
        dict: Serialized model data
    """
    exclude_fields = exclude_fields or []
    # Default fields to exclude (sensitive/internal)
    default_exclude = ['password', 'last_login', 'date_joined', '_state']
    exclude_fields.extend(default_exclude)
    
    data = {}
    for field in instance._meta.get_fields():
        if field.name in exclude_fields:
            continue
        
        # Skip reverse relations
        if field.one_to_many or field.many_to_many:
            continue
            
        try:
            if hasattr(field, 'attname'):
                value = getattr(instance, field.attname, None)
            else:
                value = getattr(instance, field.name, None)
            data[field.name] = serialize_value(value)
        except Exception:
            pass
    
    return data


def get_changes(old_data, new_data, tracked_fields=None):
    """
    Compare old and new data to find changes.
    
    Args:
        old_data: Dict of original values
        new_data: Dict of new values
        tracked_fields: Optional list of fields to track (None = all fields)
        
    Returns:
        dict: Changes in format {"field": {"old": val, "new": val}}
    """
    changes = {}
    
    all_fields = set(old_data.keys()) | set(new_data.keys())
    if tracked_fields:
        all_fields = all_fields & set(tracked_fields)
    
    for field in all_fields:
        old_val = old_data.get(field)
        new_val = new_data.get(field)
        
        # Convert to same type for comparison
        old_str = serialize_value(old_val)
        new_str = serialize_value(new_val)
        
        if old_str != new_str:
            changes[field] = {
                'old': old_str,
                'new': new_str
            }
    
    return changes


def get_object_url(instance):
    """
    Try to generate a URL to view the object.
    
    Attempts common URL patterns:
    - {app}:{model}_detail
    - {app}:{model}-detail
    - {app}:view_{model}
    - {app}:{model}
    """
    if not instance or not instance.pk:
        return ''
    
    model_name = instance._meta.model_name.lower()
    app_label = instance._meta.app_label.lower()
    
    # Common URL patterns to try
    patterns = [
        f'{app_label}:{model_name}_detail',
        f'{app_label}:{model_name}-detail',
        f'{app_label}:view_{model_name}',
        f'{app_label}:{model_name}',
        f'{app_label}:{model_name}_view',
        f'{app_label}:detail_{model_name}',
    ]
    
    for pattern in patterns:
        try:
            # Try with pk
            return reverse(pattern, kwargs={'pk': instance.pk})
        except NoReverseMatch:
            pass
        
        try:
            # Try with id
            return reverse(pattern, kwargs={'id': instance.pk})
        except NoReverseMatch:
            pass
        
        try:
            # Try with slug if available
            if hasattr(instance, 'slug') and instance.slug:
                return reverse(pattern, kwargs={'slug': instance.slug})
        except NoReverseMatch:
            pass
    
    return ''


class ActivityTrackingMixin:
    """
    A mixin for Django models to automatically track changes.
    
    Features:
    - Tracks original state when loaded from database
    - Detects field changes on save
    - Logs detailed activity with old/new values
    - Stores complete record data on delete
    
    Usage:
        class Invoice(ActivityTrackingMixin, models.Model):
            # ... your fields ...
            
            # Optional: Customize tracked fields
            TRACKED_FIELDS = ['invoice_number', 'total_amount', 'status']
            
            # Optional: Fields to exclude from tracking
            EXCLUDED_FIELDS = ['updated_at', 'modified_by']
    """
    
    # Store original data for comparison
    _original_data = None
    _is_new = True
    
    @classmethod
    def from_db(cls, db, field_names, values):
        """Called when an instance is loaded from the database."""
        instance = super().from_db(db, field_names, values)
        instance._is_new = False
        instance._capture_original_state()
        return instance
    
    def _capture_original_state(self):
        """Capture the current state as the original state."""
        exclude = getattr(self, 'EXCLUDED_FIELDS', [])
        self._original_data = get_model_dict(self, exclude_fields=exclude)
    
    def get_tracked_changes(self):
        """
        Get changes between original state and current state.
        
        Returns:
            dict: Changes in format {"field": {"old": val, "new": val}}
        """
        if self._original_data is None:
            return {}
        
        exclude = getattr(self, 'EXCLUDED_FIELDS', [])
        current_data = get_model_dict(self, exclude_fields=exclude)
        tracked_fields = getattr(self, 'TRACKED_FIELDS', None)
        
        return get_changes(self._original_data, current_data, tracked_fields)
    
    def get_activity_app_name(self):
        """Get the app name for activity logging."""
        return getattr(self._meta, 'activity_app_name', self._meta.app_label)
    
    def get_activity_model_name(self):
        """Get the model name for activity logging."""
        return getattr(self._meta, 'activity_model_name', self._meta.model_name.title())
    
    def get_activity_object_repr(self):
        """Get a string representation of this object for activity logging."""
        return str(self)
    
    def get_activity_object_url(self):
        """Get the URL to view this object."""
        return get_object_url(self)
    
    def get_deletion_data(self):
        """Get all data for this object (used when deleting)."""
        exclude = getattr(self, 'EXCLUDED_FIELDS', [])
        return get_model_dict(self, exclude_fields=exclude)


def log_model_activity(instance, activity_type, user=None, request=None, 
                       changes=None, extra_description=''):
    """
    Log an activity for a model instance.
    
    Args:
        instance: The model instance
        activity_type: 'CREATE', 'UPDATE', or 'DELETE'
        user: The user performing the action
        request: The HTTP request (optional, for IP/user agent)
        changes: Dict of changes (for UPDATE)
        extra_description: Additional description text
    """
    from .models import UserActivity, UserSession
    from .security_utils import get_client_ip
    
    # Get app and model info
    app_name = instance._meta.app_label
    model_name = instance._meta.model_name.title()
    
    # Use mixin methods if available
    if hasattr(instance, 'get_activity_app_name'):
        app_name = instance.get_activity_app_name()
    if hasattr(instance, 'get_activity_model_name'):
        model_name = instance.get_activity_model_name()
    
    # Get object representation
    object_repr = str(instance)
    if hasattr(instance, 'get_activity_object_repr'):
        object_repr = instance.get_activity_object_repr()
    
    # Get object URL
    object_url = get_object_url(instance)
    if hasattr(instance, 'get_activity_object_url'):
        object_url = instance.get_activity_object_url()
    
    # Build description
    if activity_type == 'CREATE':
        description = f"Created {model_name}: {object_repr}"
    elif activity_type == 'UPDATE':
        changed_fields = list(changes.keys()) if changes else []
        if changed_fields:
            description = f"Updated {model_name}: {object_repr} (changed: {', '.join(changed_fields)})"
        else:
            description = f"Updated {model_name}: {object_repr}"
    elif activity_type == 'DELETE':
        description = f"Deleted {model_name}: {object_repr}"
    else:
        description = f"{activity_type} {model_name}: {object_repr}"
    
    if extra_description:
        description += f" - {extra_description}"
    
    # Get request details
    ip_address = None
    user_agent = ''
    url_path = ''
    http_method = ''
    session = None
    
    if request:
        ip_address = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        url_path = request.path
        http_method = request.method
        
        # Get security session
        session_id = request.session.get('security_session_id')
        if session_id:
            try:
                session = UserSession.objects.get(id=session_id)
            except UserSession.DoesNotExist:
                pass
    
    # Get SubUser if team member is logged in
    sub_user = None
    if request and request.session.get('sub_user_id') and user:
        from .models import SubUser
        try:
            sub_user = SubUser.objects.get(id=request.session['sub_user_id'], linked_user=user)
        except (SubUser.DoesNotExist, ValueError):
            pass

    # Tenant: prefer request.company.account, then user.account, then derive from instance
    account = None
    if request:
        from .security_utils import get_account_for_activity
        account = get_account_for_activity(request=request, user=user)
    if account is None and user and getattr(user, 'account_id', None):
        account = user.account
    if account is None and instance and hasattr(instance, 'user') and getattr(instance.user, 'account_id', None):
        account = instance.user.account
    if account is None and instance and hasattr(instance, 'account_id') and instance.account_id:
        account = instance.account
    
    # Get deleted data if applicable
    deleted_data = {}
    if activity_type == 'DELETE' and hasattr(instance, 'get_deletion_data'):
        deleted_data = instance.get_deletion_data()
    
    # Log the activity
    return UserActivity.log_activity(
        user=user,
        session=session,
        sub_user=sub_user,
        account=account,
        activity_type=activity_type,
        description=description,
        app_name=app_name,
        model_name=model_name,
        object_id=str(instance.pk) if instance.pk else '',
        object_repr=object_repr,
        url_path=url_path or object_url,
        http_method=http_method,
        ip_address=ip_address,
        user_agent=user_agent,
        changes=changes or {},
        deleted_data=deleted_data,
        object_url=object_url,
    )


# Thread-local storage for current request
import threading
_thread_locals = threading.local()


def set_current_request(request):
    """Set the current request in thread-local storage."""
    _thread_locals.request = request


def get_current_request():
    """Get the current request from thread-local storage."""
    return getattr(_thread_locals, 'request', None)


def set_current_user(user):
    """Set the current user in thread-local storage."""
    _thread_locals.user = user


def get_current_user():
    """Get the current user from thread-local storage."""
    return getattr(_thread_locals, 'user', None)
