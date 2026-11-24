from rest_framework import serializers
from .models import StaffOffenceRegister, StaffOffenceEntry


class StaffOffenceEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffOffenceEntry
        fields = [
            'id', 'uuid', 'register', 'date', 'description', 'amount',
            'created_by', 'created_at', 'updated_at', 'is_deleted',
        ]
        read_only_fields = ['uuid', 'created_at', 'updated_at']


class StaffOffenceRegisterSerializer(serializers.ModelSerializer):
    month_label = serializers.ReadOnlyField()
    offence_count = serializers.SerializerMethodField()
    monthly_total = serializers.SerializerMethodField()
    entries = StaffOffenceEntrySerializer(many=True, read_only=True)

    class Meta:
        model = StaffOffenceRegister
        fields = [
            'id', 'uuid', 'reference_number', 'staff_name',
            'department_name', 'year', 'month', 'month_label',
            'offence_count', 'monthly_total', 'entries',
            'authorized_signature', 'authorized_signatory_name', 'payment_status',
            'created_by', 'created_at', 'updated_at', 'is_deleted',
        ]
        read_only_fields = ['reference_number', 'uuid', 'created_at', 'updated_at']

    def get_offence_count(self, obj):
        return obj.offence_count()

    def get_monthly_total(self, obj):
        return obj.monthly_total()


class StaffOffenceRegisterCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffOffenceRegister
        fields = ['staff_name', 'department_name', 'year', 'month']
