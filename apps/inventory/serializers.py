# -*- coding: utf-8 -*-
from rest_framework import serializers
from .models import Inventory, WasteLog


class InventorySerializer(serializers.ModelSerializer):
    """DRF serializer for Inventory; company isolation enforced in viewset."""
    remaining_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    actual_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    net_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True
    )
    waste_value = serializers.DecimalField(
        max_digits=16, decimal_places=2, read_only=True
    )
    created_by_display = serializers.SerializerMethodField()

    class Meta:
        model = Inventory
        fields = [
            'id', 'transaction_id', 'sn', 'product_name', 'category',
            'company', 'company_name', 'vendor', 'stock_location', 'phone_number',
            'quantity_in', 'quantity_out', 'waste', 'remaining_quantity', 'actual_quantity',
            'net_quantity', 'waste_value', 'unit_price',
            'total_amount', 'balance_quantity', 'low_stock_threshold',
            'stock_status', 'approval_status', 'workflow_status', 'remark',
            'created_by', 'created_by_display', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'transaction_id', 'sn', 'total_amount', 'balance_quantity',
            'stock_status', 'created_at', 'updated_at',
        ]

    def get_created_by_display(self, obj):
        if not obj.created_by:
            return ''
        return obj.created_by.get_full_name() or obj.created_by.email or str(obj.created_by)


class WasteLogSerializer(serializers.ModelSerializer):
    """DRF serializer for WasteLog; company isolation enforced in viewset."""
    inventory_name = serializers.CharField(source='inventory.product_name', read_only=True)
    reason_display = serializers.CharField(source='get_reason_display', read_only=True)
    created_by_display = serializers.SerializerMethodField()

    class Meta:
        model = WasteLog
        fields = [
            'id', 'inventory', 'inventory_name', 'quantity', 'unit_price',
            'total_value', 'reason', 'reason_display', 'description',
            'waste_date', 'created_by', 'created_by_display', 'created_at',
        ]
        read_only_fields = ['total_value', 'created_at']

    def get_created_by_display(self, obj):
        if not obj.created_by:
            return ''
        return obj.created_by.get_full_name() or obj.created_by.email or str(obj.created_by)
