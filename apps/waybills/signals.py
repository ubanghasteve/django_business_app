# -*- coding: utf-8 -*-
from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
import json

from .models import Waybill, WaybillMovement


def _clear_waybill_cache(instance):
    if instance.account_id:
        cache.delete(f"waybill_list_{instance.account_id}")


def _deep_compare_dicts(old_dict, new_dict):
    """Properly compare two dictionaries including nested structures."""
    try:
        old_json = json.dumps(old_dict, sort_keys=True, default=str)
        new_json = json.dumps(new_dict, sort_keys=True, default=str)
        return old_json != new_json
    except (TypeError, ValueError):
        return str(old_dict or {}) != str(new_dict or {})


def _get_field_changed(old_val, new_val):
    """Check if a field value has changed."""
    if old_val is None and new_val is None:
        return False
    if old_val is None or new_val is None:
        return True
    return old_val != new_val


@receiver(pre_save, sender=Waybill)
def _capture_old_waybill_values(sender, instance, **kwargs):
    """Store previous values so post_save can create movements when relevant fields change."""
    if instance.pk:
        try:
            old = Waybill.objects.filter(pk=instance.pk).values(
                'total_quantity_input',
                'delivered_quantity_input',
                'total_quantity_value',
                'delivered_quantity_value',
                'remaining_quantity_value',
                'status',
                'is_approved',
                'notes',
                'custom_data',
            ).first()
            if old is not None:
                instance._movement_old_total_qty_input = old.get('total_quantity_input') or ''
                instance._movement_old_delivered_qty_input = old.get('delivered_quantity_input') or ''
                instance._movement_old_total_qty_value = float(old.get('total_quantity_value') or 0)
                instance._movement_old_delivered_qty_value = float(old.get('delivered_quantity_value') or 0)
                instance._movement_old_remaining_qty_value = float(old.get('remaining_quantity_value') or 0)
                instance._movement_old_status = old.get('status') or 'pending'
                instance._movement_old_is_approved = bool(old.get('is_approved'))
                instance._movement_old_notes = old.get('notes') or ''
                instance._movement_old_custom_data = old.get('custom_data') or {}
            else:
                instance._movement_old_total_qty_input = ''
                instance._movement_old_delivered_qty_input = ''
                instance._movement_old_total_qty_value = 0.0
                instance._movement_old_delivered_qty_value = 0.0
                instance._movement_old_remaining_qty_value = 0.0
                instance._movement_old_status = 'pending'
                instance._movement_old_is_approved = False
                instance._movement_old_notes = ''
                instance._movement_old_custom_data = {}
        except Exception as e:
            print(f"[WaybillMovement Signal Error] Failed to capture old values: {e}")
            instance._movement_old_total_qty_input = ''
            instance._movement_old_delivered_qty_input = ''
            instance._movement_old_total_qty_value = 0.0
            instance._movement_old_delivered_qty_value = 0.0
            instance._movement_old_remaining_qty_value = 0.0
            instance._movement_old_status = 'pending'
            instance._movement_old_is_approved = False
            instance._movement_old_notes = ''
            instance._movement_old_custom_data = {}
    else:
        instance._movement_old_total_qty_input = ''
        instance._movement_old_delivered_qty_input = ''
        instance._movement_old_total_qty_value = 0.0
        instance._movement_old_delivered_qty_value = 0.0
        instance._movement_old_remaining_qty_value = 0.0
        instance._movement_old_status = 'pending'
        instance._movement_old_is_approved = False
        instance._movement_old_notes = ''
        instance._movement_old_custom_data = {}


def _clean_movement_attrs(instance):
    attrs = (
        '_movement_old_total_qty_input',
        '_movement_old_delivered_qty_input',
        '_movement_old_total_qty_value',
        '_movement_old_delivered_qty_value',
        '_movement_old_remaining_qty_value',
        '_movement_old_status',
        '_movement_old_is_approved',
        '_movement_old_notes',
        '_movement_old_custom_data',
    )
    for attr in attrs:
        if hasattr(instance, attr):
            delattr(instance, attr)


@receiver(post_save, sender=Waybill)
def _create_waybill_movement_on_change(sender, instance, created, **kwargs):
    """Create an immutable WaybillMovement when the waybill changes.
    
    Each movement row stores a SNAPSHOT of the waybill at that moment.
    For new waybills (created), we create an initial movement.
    For updates, we create a movement if any relevant field changed.
    """
    old_total_qty_input = getattr(instance, '_movement_old_total_qty_input', '')
    old_delivered_qty_input = getattr(instance, '_movement_old_delivered_qty_input', '')
    old_total_qty_value = getattr(instance, '_movement_old_total_qty_value', 0.0)
    old_delivered_qty_value = getattr(instance, '_movement_old_delivered_qty_value', 0.0)
    old_remaining_qty_value = getattr(instance, '_movement_old_remaining_qty_value', 0.0)
    old_status = getattr(instance, '_movement_old_status', 'pending')
    old_is_approved = getattr(instance, '_movement_old_is_approved', False)
    old_notes = getattr(instance, '_movement_old_notes', '')
    old_custom_data = getattr(instance, '_movement_old_custom_data', {})

    new_total_qty_input = instance.total_quantity_input or ''
    new_delivered_qty_input = instance.delivered_quantity_input or ''
    new_total_qty_value = float(instance.total_quantity_value or 0)
    new_delivered_qty_value = float(instance.delivered_quantity_value or 0)
    new_remaining_qty_value = float(instance.remaining_quantity_value or 0)
    new_status = instance.status or 'pending'
    new_is_approved = bool(instance.is_approved)
    new_notes = instance.notes or ''
    new_custom_data = instance.custom_data or {}

    if created:
        remark = 'Waybill created'
    else:
        changes = []
        if _get_field_changed(old_total_qty_input, new_total_qty_input):
            changes.append('total quantity')
        if _get_field_changed(old_delivered_qty_input, new_delivered_qty_input):
            changes.append('delivered quantity')
        if _get_field_changed(old_total_qty_value, new_total_qty_value):
            changes.append('total value')
        if _get_field_changed(old_delivered_qty_value, new_delivered_qty_value):
            changes.append('delivered value')
        if _get_field_changed(old_remaining_qty_value, new_remaining_qty_value):
            changes.append('remaining value')
        if _get_field_changed(old_status, new_status):
            changes.append('status')
        if _get_field_changed(old_is_approved, new_is_approved):
            changes.append('approval')
        if _get_field_changed(old_notes, new_notes):
            changes.append('notes')
        if _deep_compare_dicts(old_custom_data, new_custom_data):
            changes.append('custom data')
        
        if changes:
            remark = f'Updated: {", ".join(changes)}'
        else:
            remark = 'Waybill updated (no tracked fields changed)'

    try:
        WaybillMovement.objects.create(
            waybill=instance,
            total_quantity_input=new_total_qty_input,
            delivered_quantity_input=new_delivered_qty_input,
            total_quantity_value=new_total_qty_value,
            delivered_quantity_value=new_delivered_qty_value,
            remaining_quantity_value=new_remaining_qty_value,
            custom_data_snapshot=new_custom_data,
            status=new_status,
            is_approved=new_is_approved,
            notes=new_notes if new_notes else remark,
            created_by=instance.created_by,
        )
    except Exception as e:
        print(f"[WaybillMovement Signal Error] Failed to create movement: {e}")
    finally:
        _clean_movement_attrs(instance)


@receiver(post_save, sender=Waybill)
def clear_waybill_cache_on_save(sender, instance, **kwargs):
    _clear_waybill_cache(instance)


@receiver(post_delete, sender=Waybill)
def clear_waybill_cache_on_delete(sender, instance, **kwargs):
    _clear_waybill_cache(instance)
