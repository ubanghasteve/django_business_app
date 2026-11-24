from rest_framework import serializers

from apps.hr_staff.models import Employee

from ..models import (
    PayrollStructure,
    EmployeePayrollProfile,
    PayrollPeriod,
    PayrollRun,
    PayrollItem,
    Payslip,
    BonusRule,
    EmployeeBonus,
    EmployeeLoan,
    LoanRepayment,
    SalaryAdvance,
    PayrollFile,
    FileCategory,
    PayrollTemplate,
    PayrollEntry,
)


class PayrollStructureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollStructure
        fields = "__all__"


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ["id", "employee_id", "first_name", "last_name", "full_name", "department", "monthly_salary"]


class EmployeePayrollProfileSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    employee_id = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(), source="employee", write_only=True
    )

    class Meta:
        model = EmployeePayrollProfile
        fields = [
            "id",
            "account",
            "company",
            "created_by",
            "created_at",
            "updated_at",
            "employee",
            "employee_id",
            "payroll_structure",
            "basic_salary",
            "allowance",
            "pension_enabled",
            "nhf_enabled",
        ]
        read_only_fields = ["account", "company", "created_by", "created_at", "updated_at"]


class PayrollPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollPeriod
        fields = "__all__"


class PayrollRunSerializer(serializers.ModelSerializer):
    period = PayrollPeriodSerializer(read_only=True)

    class Meta:
        model = PayrollRun
        fields = "__all__"


class PayrollItemSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    employee_id = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(), source="employee", write_only=True
    )

    class Meta:
        model = PayrollItem
        fields = "__all__"
        read_only_fields = ["account", "company", "created_by", "created_at", "updated_at"]


class PayslipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payslip
        fields = "__all__"


class BonusRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = BonusRule
        fields = "__all__"


class EmployeeBonusSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeBonus
        fields = "__all__"


class EmployeeLoanSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeLoan
        fields = "__all__"


class LoanRepaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoanRepayment
        fields = "__all__"


class SalaryAdvanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalaryAdvance
        fields = "__all__"


class FileCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = FileCategory
        fields = "__all__"


class PayrollFileSerializer(serializers.ModelSerializer):
    file_type_display = serializers.CharField(source="get_file_type_display", read_only=True)
    file_size_display = serializers.CharField(read_only=True)
    period_display = serializers.CharField(read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = PayrollFile
        fields = [
            "id", "account", "company", "created_by", "created_at", "updated_at",
            "file", "original_filename", "file_type", "file_type_display",
            "mime_type", "file_size", "file_size_display",
            "title", "description", "notes",
            "category", "category_name",
            "employee", "employee_name",
            "payroll_period", "payroll_run",
            "month", "year", "period_display",
            "tags",
            "is_starred", "is_archived", "is_public",
            "view_count", "download_count",
        ]
        read_only_fields = [
            "account", "company", "created_by", "created_at", "updated_at",
            "original_filename", "file_type", "mime_type", "file_size",
            "view_count", "download_count",
        ]

    def get_employee_name(self, obj):
        return str(obj.employee) if obj.employee else None


class ColumnSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    type = serializers.CharField()
    required = serializers.BooleanField(required=False, default=False)
    order = serializers.IntegerField(required=False)


class TemplateListSerializer(serializers.ModelSerializer):
    column_count = serializers.SerializerMethodField()

    class Meta:
        model = PayrollTemplate
        fields = [
            'id', 'name', 'description', 'column_count',
            'usage_count', 'created_at', 'updated_at'
        ]

    def get_column_count(self, obj):
        return len(obj.columns) if obj.columns else 0


class TemplateDetailSerializer(serializers.ModelSerializer):
    columns = ColumnSerializer(many=True, required=False)

    class Meta:
        model = PayrollTemplate
        fields = [
            'id', 'name', 'description', 'columns',
            'usage_count', 'created_at', 'updated_at'
        ]


class TemplateCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    columns = ColumnSerializer(many=True, required=False)

    def validate_columns(self, value):
        if value:
            for col in value:
                if 'key' not in col or 'label' not in col:
                    raise serializers.ValidationError(
                        "Each column must have 'key' and 'label' fields"
                    )
        return value


class EntryListSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source='template.name', read_only=True)
    period_display = serializers.SerializerMethodField()

    class Meta:
        model = PayrollEntry
        fields = [
            'id', 'title', 'template', 'template_name', 'period_month',
            'period_year', 'period_display', 'row_count', 'status',
            'created_at', 'updated_at'
        ]

    def get_period_display(self, obj):
        if obj.period_month and obj.period_year:
            return f"{obj.period_month}/{obj.period_year}"
        return None


class EntryDetailSerializer(serializers.ModelSerializer):
    template = TemplateDetailSerializer(read_only=True)
    columns = serializers.SerializerMethodField()
    rows = serializers.SerializerMethodField()

    class Meta:
        model = PayrollEntry
        fields = [
            'id', 'title', 'template', 'period_month',
            'period_year', 'row_count', 'status', 'data', 'columns',
            'rows', 'created_at', 'updated_at', 'created_by', 'updated_by'
        ]

    def get_columns(self, obj):
        if obj.data and 'columns' in obj.data:
            return obj.data['columns']
        return []

    def get_rows(self, obj):
        if obj.data and 'rows' in obj.data:
            return obj.data['rows']
        return []


class EntryCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    template_id = serializers.IntegerField()
    period_month = serializers.IntegerField(required=False, min_value=1, max_value=12)
    period_year = serializers.IntegerField(required=False)
    rows = serializers.ListField(child=serializers.DictField(), required=False)
    status = serializers.ChoiceField(
        choices=['draft', 'completed', 'archived'],
        default='draft'
    )

    def validate_template_id(self, value):
        if not PayrollTemplate.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Template not found")
        return value


class EntryUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255, required=False)
    period_month = serializers.IntegerField(required=False, min_value=1, max_value=12)
    period_year = serializers.IntegerField(required=False)
    rows = serializers.ListField(child=serializers.DictField(), required=False)
    status = serializers.ChoiceField(
        choices=['draft', 'completed', 'archived'],
        required=False
    )

