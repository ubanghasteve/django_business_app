from rest_framework import serializers

from .models import (
    Transaction,
    ChartOfAccount,
    JournalEntry,
    JournalEntryLine,
    LedgerEntry,
)


class ChartOfAccountSerializer(serializers.ModelSerializer):
    category_type = serializers.CharField(
        source="category.category_type",
        read_only=True,
    )

    class Meta:
        model = ChartOfAccount
        fields = [
            "id",
            "code",
            "name",
            "category",
            "category_type",
            "account_type",
            "parent",
            "is_active",
        ]
        read_only_fields = ["id"]


class JournalEntryLineSerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = JournalEntryLine
        fields = [
            "id",
            "account",
            "account_code",
            "account_name",
            "description",
            "debit",
            "credit",
        ]
        read_only_fields = ["id", "account_code", "account_name"]


class JournalEntrySerializer(serializers.ModelSerializer):
    lines = JournalEntryLineSerializer(many=True)

    class Meta:
        model = JournalEntry
        fields = [
            "id",
            "reference",
            "description",
            "date",
            "status",
            "total_debit",
            "total_credit",
            "lines",
        ]
        read_only_fields = ["id", "total_debit", "total_credit", "status"]


class LedgerEntrySerializer(serializers.ModelSerializer):
    account_code = serializers.CharField(source="account.code", read_only=True)
    account_name = serializers.CharField(source="account.name", read_only=True)

    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "date",
            "account",
            "account_code",
            "account_name",
            "debit",
            "credit",
            "balance",
        ]
        read_only_fields = ["id", "balance", "account_code", "account_name"]


class TransactionSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    source_app_display = serializers.CharField(
        source="get_source_app_display", read_only=True
    )

    class Meta:
        model = Transaction
        fields = [
            "id",
            "type",
            "type_display",
            "title",
            "description",
            "amount",
            "currency",
            "tax",
            "discount",
            "net_amount",
            "source_app",
            "source_app_display",
            "reference_id",
            "reference_model",
            "transaction_date",
            "created_at",
            "is_reconciled",
            "is_void",
        ]
        read_only_fields = [
            "id",
            "net_amount",
            "created_at",
            "is_reconciled",
            "is_void",
            "type_display",
            "source_app_display",
        ]

