# -*- coding: utf-8 -*-
from rest_framework import serializers
from .models import Expense


class ExpenseSerializer(serializers.ModelSerializer):
    remaining_quantity = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    total_purchase_value = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    stock_value_remaining = serializers.DecimalField(max_digits=16, decimal_places=2, read_only=True)
    low_stock_alert = serializers.BooleanField(read_only=True)
    created_by_display = serializers.SerializerMethodField()
    approved_by_display = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            'id', 'transaction_id', 'sn', 'expense_date', 'expense_category', 'department',
            'vendor', 'po_number', 'description', 'product_id', 'product_name', 'product_category',
            'product_description', 'unit_of_measurement', 'quantity_purchased', 'quantity_out',
            'remaining_quantity', 'unit_price', 'total_purchase_value', 'stock_value_remaining',
            'quantity_threshold', 'low_stock_alert', 'subtotal', 'tax', 'discount', 'total_amount',
            'payment_method', 'payment_date', 'receipt_upload', 'status',
            'approved_by', 'approved_by_display', 'created_by', 'created_by_display',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'transaction_id', 'sn', 'total_amount', 'created_at', 'updated_at',
        ]

    def get_created_by_display(self, obj):
        if not obj.created_by:
            return ''
        return obj.created_by.get_full_name() or obj.created_by.email or str(obj.created_by)

    def get_approved_by_display(self, obj):
        if not obj.approved_by:
            return ''
        return obj.approved_by.get_full_name() or obj.approved_by.email or str(obj.approved_by)
