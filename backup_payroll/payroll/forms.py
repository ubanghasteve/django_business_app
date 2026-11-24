from django import forms

from .models import (
    PayrollStructure, EmployeePayrollProfile, EmployeeLoan, SalaryAdvance, 
    BonusRule, PayrollFile, FileCategory
)


class PayrollStructureForm(forms.ModelForm):
    class Meta:
        model = PayrollStructure
        fields = ["name", "description", "enable_thirteenth_salary", "is_active"]


class EmployeePayrollProfileForm(forms.ModelForm):
    class Meta:
        model = EmployeePayrollProfile
        fields = [
            "employee",
            "payroll_structure",
            "basic_salary",
            "allowance",
            "pension_enabled",
            "nhf_enabled",
        ]


class EmployeeLoanForm(forms.ModelForm):
    class Meta:
        model = EmployeeLoan
        fields = [
            "employee",
            "principal_amount",
            "outstanding_balance",
            "monthly_repayment_amount",
            "start_date",
            "status",
        ]


class SalaryAdvanceForm(forms.ModelForm):
    class Meta:
        model = SalaryAdvance
        fields = ["employee", "amount", "status"]


class BonusRuleForm(forms.ModelForm):
    class Meta:
        model = BonusRule
        fields = ["name", "bonus_type", "percentage_of_basic", "is_active"]


class PayrollFileUploadForm(forms.ModelForm):
    class Meta:
        model = PayrollFile
        fields = [
            "title", "description", "category", "employee", "payroll_period",
            "month", "year", "tags", "is_public"
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "Auto-generated from filename if empty"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "employee": forms.Select(attrs={"class": "form-select"}),
            "payroll_period": forms.Select(attrs={"class": "form-select"}),
            "month": forms.Select(attrs={"class": "form-select"}),
            "year": forms.NumberInput(attrs={"class": "form-control"}),
            "tags": forms.TextInput(attrs={
                "class": "form-control", 
                "placeholder": "e.g., january, bonus, tax (comma separated)"
            }),
            "is_public": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["month"].choices = [('', 'Select Month')] + [(i, m) for i, m in enumerate([
            'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'
        ], 1)]
        self.fields["year"].initial = None
        self.fields["year"].widget.attrs["placeholder"] = "e.g., 2024"
        self.fields["tags"].help_text = "Comma-separated tags for easy searching"


class PayrollFileEditForm(forms.ModelForm):
    class Meta:
        model = PayrollFile
        fields = [
            "title", "description", "notes", "category", "employee", 
            "payroll_period", "month", "year", "tags", "is_starred", 
            "is_archived", "is_public"
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "employee": forms.Select(attrs={"class": "form-select"}),
            "payroll_period": forms.Select(attrs={"class": "form-select"}),
            "month": forms.Select(attrs={"class": "form-select"}),
            "year": forms.NumberInput(attrs={"class": "form-control"}),
            "tags": forms.TextInput(attrs={"class": "form-control"}),
            "is_starred": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_archived": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_public": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["month"].choices = [('', 'Select Month')] + [(i, m) for i, m in enumerate([
            'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'
        ], 1)]


class FileCategoryForm(forms.ModelForm):
    class Meta:
        model = FileCategory
        fields = ["name", "category_type", "description", "is_active", "color"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "category_type": forms.Select(attrs={"class": "form-select"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "color": forms.TextInput(attrs={"class": "form-control", "type": "color"}),
        }

