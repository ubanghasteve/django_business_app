from rest_framework import serializers

from .models import Product


class JobOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = "__all__"
        read_only_fields = [
            "id",
            "uuid",
            "date_created",
            "updated_at",
            "account",
            "job_order",
            "submission_id",
        ]
