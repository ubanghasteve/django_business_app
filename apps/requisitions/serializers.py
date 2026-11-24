from rest_framework import serializers
from .models import Requisition


class RequisitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Requisition
        fields = [
            'id', 'reference_number', 'organization_name', 'address', 'contact_number',
            'date', 'job_type', 'print_product', 'quantity', 'colors', 'size', 'micron',
            'other_info', 'signature', 'status', 'created_at', 'updated_at', 'created_by',
        ]
        read_only_fields = ['reference_number', 'created_at', 'updated_at']


class RequisitionCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Requisition
        fields = [
            'organization_name', 'address', 'contact_number', 'date', 'job_type',
            'print_product', 'quantity', 'colors', 'size', 'micron', 'other_info',
            'signature', 'status',
        ]
