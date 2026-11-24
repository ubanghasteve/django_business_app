from rest_framework import serializers

from .models import Waybill


class WaybillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Waybill
        fields = "__all__"
        read_only_fields = [
            "id",
            "uuid",
            "created_at",
            "updated_at",
            "account",
            "waybill_number",
        ]
