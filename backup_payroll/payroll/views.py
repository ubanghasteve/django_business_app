from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.views.static import serve
from django.conf import settings
from django.db.models import Q

from apps.core.permissions import company_admin_or_permission_required, company_admin_or_any_permission_required
from apps.core.ownership import for_user_queryset, get_account_for_user
from apps.core.utils import get_company_profile_for_user, apply_no_cache_headers

from .analytics import get_payroll_dashboard_metrics
from .exporters import (
    export_paye,
    export_nhf,
    export_pension,
    export_payroll_summary,
)
from .forms import (
    PayrollStructureForm,
    EmployeePayrollProfileForm,
    EmployeeLoanForm,
    SalaryAdvanceForm,
    BonusRuleForm,
    PayrollFileUploadForm,
    PayrollFileEditForm,
    FileCategoryForm,
)
from .models import (
    PayrollStructure,
    EmployeePayrollProfile,
    PayrollPeriod,
    PayrollRun,
    PayrollItem,
    Payslip,
    BonusRule,
    EmployeeBonus,
    EmployeeLoan,
    SalaryAdvance,
    PayrollFile,
    FileCategory,
    FileAccessLog,
    ExcelData,
    ExtractedPayrollRecord,
    PayrollTemplate,
    PayrollEntry,
)
from .reports import payslip_http_response, payroll_summary
from .services import generate_payroll_run, generate_payslip, post_payroll_to_accounting, mark_payroll_as_paid
from .file_processor import FileProcessor, FileTypeDetector, FileNameParser, get_file_icon
from .excel_parser import ExcelParser, parse_excel_file
from .template_detector import TemplateDetector, create_template_from_excel, generate_form_fields
from apps.hr_staff.models import Employee
from apps.core.ownership import get_account_for_user


def _company(request):
    return getattr(request, "company", None) or get_company_profile_for_user(
        request.user, request
    )


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def dashboard(request):
    """
    Payroll dashboard for file upload, template detection, and dynamic payroll entry management.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")

    total_files = PayrollFile.objects.filter(company=company).count()
    total_templates = PayrollTemplate.objects.filter(company=company).count()
    total_entries = PayrollEntry.objects.filter(company=company).count()

    recent_files = PayrollFile.objects.filter(
        company=company, is_archived=False
    ).select_related("category", "created_by").order_by("-created_at")[:5]

    recent_templates = PayrollTemplate.objects.filter(
        company=company
    ).order_by("-created_at")[:5]

    recent_entries = PayrollEntry.objects.filter(
        company=company
    ).select_related("template", "created_by").order_by("-created_at")[:5]

    files_by_type = {}
    for ft, label in PayrollFile.FILE_TYPE_CHOICES:
        count = PayrollFile.objects.filter(company=company, file_type=ft).count()
        if count > 0:
            files_by_type[ft] = {"label": label, "count": count}

    entries_by_status = {}
    for status_choice in PayrollEntry.STATUS_CHOICES:
        count = PayrollEntry.objects.filter(company=company, status=status_choice[0]).count()
        if count > 0:
            entries_by_status[status_choice[0]] = {"label": status_choice[1], "count": count}

    context = {
        "total_files": total_files,
        "total_templates": total_templates,
        "total_entries": total_entries,
        "recent_files": recent_files,
        "recent_templates": recent_templates,
        "recent_entries": recent_entries,
        "files_by_type": files_by_type,
        "entries_by_status": entries_by_status,
        "payroll_current_page": "dashboard",
    }
    response = render(request, "payroll/dashboard.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def payroll_list(request):
    """
    List payroll runs for the current company.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    runs = PayrollRun.objects.filter(company=company).select_related("period").order_by(
        "-created_at"
    )
    context = {
        "runs": runs,
        "payroll_current_page": "runs",
    }
    response = render(request, "payroll/payroll_list.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.run_payroll", raise_exception=True)
def payroll_run_view(request):
    """
    Trigger payroll generation for a given month/year.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    if request.method == "POST":
        try:
            month = int(request.POST.get("month") or date.today().month)
            year = int(request.POST.get("year") or date.today().year)
        except (TypeError, ValueError):
            messages.error(request, "Invalid month/year.")
            return redirect("payroll:payroll_run")
        structure_id = request.POST.get("structure")
        structure = None
        if structure_id:
            structure = get_object_or_404(
                PayrollStructure, pk=structure_id, company=company
            )
        payroll_run = generate_payroll_run(
            user=request.user, month=month, year=year, structure=structure, request=request
        )
        messages.success(
            request,
            f"Payroll run {payroll_run.id} created for {month}/{year} and moved to Pending Approval.",
        )
        return redirect("payroll:payroll_list")
    structures = PayrollStructure.objects.filter(company=company, is_active=True)
    structures_list = [
        {"id": s.id, "name": s.name}
        for s in structures
    ]
    account = get_account_for_user(request.user)
    employees_qs = (
        Employee.objects.filter(account=account, company=company, status="active", is_deleted=False)
        .select_related("department")
        .order_by("last_name", "first_name")
    )
    employees_list = [
        {
            "id": emp.id,
            "full_name": emp.full_name,
            "employee_id": emp.employee_id,
            "position": emp.position,
            "department": emp.department.name if emp.department else None,
            "monthly_salary": str(emp.monthly_salary) if emp.monthly_salary else "0",
            "email": emp.email,
            "phone": emp.phone,
            "first_name": emp.first_name,
            "last_name": emp.last_name,
        }
        for emp in employees_qs
    ]
    context = {
        "structures": structures,
        "structures_json": structures_list,
        "employees": employees_list,
        "payroll_current_page": "run",
    }
    response = render(request, "payroll/payroll_run.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def employee_payroll_detail(request, item_id):
    """
    View per-employee payroll item in a run.
    """
    qs = PayrollItem.objects.select_related(
        "employee", "payroll_run", "payroll_run__period"
    )
    account = get_account_for_user(request.user)
    qs = qs.filter(company__account=account)
    item = get_object_or_404(qs, pk=item_id)
    context = {
        "item": item,
        "payroll_current_page": "runs",
    }
    response = render(request, "payroll/employee_payroll.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_any_permission_required(
    ["payroll.approve_payroll", "payroll.run_payroll"], raise_exception=True
)
@require_POST
def approve_payroll_run(request, run_id):
    """
    Approve a payroll run and post to accounting.
    """
    company = _company(request)
    run = get_object_or_404(
        PayrollRun.objects.select_related("period"),
        pk=run_id,
        company=company,
    )
    if run.status not in ("pending_approval", "processing", "draft"):
        messages.warning(request, "Payroll run is already approved or paid.")
        return redirect("payroll:payroll_list")
    # Post to accounting and set status to approved inside service.
    post_payroll_to_accounting(run, request.user)
    messages.success(request, "Payroll run approved and posted to accounting.")
    return redirect("payroll:payroll_list")


@login_required
@never_cache
@company_admin_or_permission_required("payroll.approve_payroll", raise_exception=True)
@require_POST
def mark_run_paid(request, run_id):
    """
    Mark a payroll run as paid and post payment journal (Salary Payable → Bank).
    """
    company = _company(request)
    run = get_object_or_404(
        PayrollRun.objects.select_related("period"),
        pk=run_id,
        company=company,
    )
    if run.status != "approved":
        messages.error(request, "Only approved payroll runs can be marked as paid.")
        return redirect("payroll:payroll_list")
    journal = mark_payroll_as_paid(run, request.user)
    if not journal:
        messages.error(request, "Unable to post payment journal. Please configure Salary Payable and Bank accounts.")
    else:
        messages.success(request, "Payroll run marked as paid and payment journal posted.")
    return redirect("payroll:payroll_list")


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payslip", raise_exception=True)
def payslip_view(request, item_id):
    """
    Generate/return payslip PDF for a payroll item.
    Only approved payroll runs may generate payslips.
    """
    company = _company(request)
    item = get_object_or_404(
        PayrollItem.objects.select_related("payroll_run", "payroll_run__period"),
        pk=item_id,
        company=company,
    )
    if item.payroll_run.status not in ("approved", "paid"):
        messages.error(request, "Payslips can only be generated for approved payroll.")
        return redirect("payroll:employee_payroll_detail", item_id=item.id)
    payslip = generate_payslip(item, created_by=request.user)
    return payslip_http_response(item)


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
@require_GET
def payroll_summary_view(request, period_id):
    """
    Payroll summary report for a given period.
    """
    company = _company(request)
    period = get_object_or_404(PayrollPeriod, pk=period_id, company=company)
    summary = payroll_summary(company, period)
    context = {
        "period": period,
        "items": summary["items"],
        "total_cost": summary["total_cost"],
        "total_deductions": summary["total_deductions"],
        "total_net": summary["total_net"],
        "payroll_current_page": "reports",
    }
    response = render(request, "payroll/reports/payroll_summary.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
@require_GET
def paye_report_view(request, period_id):
    company = _company(request)
    period = get_object_or_404(PayrollPeriod, pk=period_id, company=company)
    items = PayrollItem.objects.filter(
        company=company, payroll_run__period=period
    ).select_related("employee")
    context = {
        "period": period,
        "items": items,
    }
    response = render(request, "payroll/reports/paye_report.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
@require_GET
def nhf_report_view(request, period_id):
    company = _company(request)
    period = get_object_or_404(PayrollPeriod, pk=period_id, company=company)
    items = PayrollItem.objects.filter(
        company=company, payroll_run__period=period
    ).select_related("employee")
    context = {
        "period": period,
        "items": items,
    }
    response = render(request, "payroll/reports/nhf_report.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
@require_GET
def pension_report_view(request, period_id):
    company = _company(request)
    period = get_object_or_404(PayrollPeriod, pk=period_id, company=company)
    items = PayrollItem.objects.filter(
        company=company, payroll_run__period=period
    ).select_related("employee")
    context = {
        "period": period,
        "items": items,
    }
    response = render(request, "payroll/reports/pension_report.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def export_excel_view(request, period_id, export_type):
    """
    Excel exports: PAYE, NHF, Pension, Payroll summary.
    """
    company = _company(request)
    period = get_object_or_404(PayrollPeriod, pk=period_id, company=company)
    if export_type == "paye":
        buf = export_paye(company, period)
        filename = f"paye_{period.year}_{period.month}.xlsx"
    elif export_type == "nhf":
        buf = export_nhf(company, period)
        filename = f"nhf_{period.year}_{period.month}.xlsx"
    elif export_type == "pension":
        buf = export_pension(company, period)
        filename = f"pension_{period.year}_{period.month}.xlsx"
    else:
        buf = export_payroll_summary(company, period)
        filename = f"payroll_summary_{period.year}_{period.month}.xlsx"
    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def employee_payroll_profiles_list(request):
    """
    List all employee payroll profiles for the company.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    profiles = EmployeePayrollProfile.objects.filter(company=company).select_related(
        "employee", "payroll_structure"
    ).order_by("employee__last_name", "employee__first_name")
    context = {
        "profiles": profiles,
        "payroll_current_page": "profiles",
    }
    response = render(request, "payroll/employee_profiles_list.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def employee_payroll_profile_edit(request, profile_id):
    """
    Edit an employee payroll profile.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    profile = get_object_or_404(
        EmployeePayrollProfile.objects.select_related("employee"),
        pk=profile_id,
        company=company,
    )
    if request.method == "POST":
        form = EmployeePayrollProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, f"Payroll profile for {profile.employee} updated successfully.")
            return redirect("payroll:employee_profiles_list")
    else:
        form = EmployeePayrollProfileForm(instance=profile)
    context = {
        "form": form,
        "profile": profile,
        "payroll_current_page": "profiles",
    }
    response = render(request, "payroll/employee_profile_form.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def loans_list(request):
    """
    List all employee loans.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    loans = EmployeeLoan.objects.filter(company=company).select_related("employee").order_by(
        "-created_at"
    )
    context = {
        "loans": loans,
        "payroll_current_page": "loans",
    }
    response = render(request, "payroll/loans_list.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def loan_create(request):
    """
    Create a new employee loan.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    if request.method == "POST":
        form = EmployeeLoanForm(request.POST)
        if form.is_valid():
            loan = form.save(commit=False)
            loan.account = get_account_for_user(request.user)
            loan.company = company
            loan.created_by = request.user
            loan.outstanding_balance = loan.principal_amount
            loan.save()
            messages.success(request, f"Loan created for {loan.employee}.")
            return redirect("payroll:loans_list")
    else:
        form = EmployeeLoanForm()
    context = {
        "form": form,
        "payroll_current_page": "loans",
    }
    response = render(request, "payroll/loan_form.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def loan_edit(request, loan_id):
    """
    Edit an employee loan.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    loan = get_object_or_404(EmployeeLoan, pk=loan_id, company=company)
    if request.method == "POST":
        form = EmployeeLoanForm(request.POST, instance=loan)
        if form.is_valid():
            form.save()
            messages.success(request, f"Loan for {loan.employee} updated.")
            return redirect("payroll:loans_list")
    else:
        form = EmployeeLoanForm(instance=loan)
    context = {
        "form": form,
        "loan": loan,
        "payroll_current_page": "loans",
    }
    response = render(request, "payroll/loan_form.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def salary_advances_list(request):
    """
    List all salary advances.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    advances = SalaryAdvance.objects.filter(company=company).select_related("employee").order_by(
        "-created_at"
    )
    context = {
        "advances": advances,
        "payroll_current_page": "advances",
    }
    response = render(request, "payroll/salary_advances_list.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def salary_advance_create(request):
    """
    Create a new salary advance request.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    if request.method == "POST":
        form = SalaryAdvanceForm(request.POST)
        if form.is_valid():
            advance = form.save(commit=False)
            advance.account = get_account_for_user(request.user)
            advance.company = company
            advance.created_by = request.user
            advance.save()
            messages.success(request, f"Salary advance created for {advance.employee}.")
            return redirect("payroll:salary_advances_list")
    else:
        form = SalaryAdvanceForm()
    context = {
        "form": form,
        "payroll_current_page": "advances",
    }
    response = render(request, "payroll/salary_advance_form.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.approve_payroll", raise_exception=True)
@require_POST
def salary_advance_approve(request, advance_id):
    """
    Approve a salary advance request.
    """
    company = _company(request)
    advance = get_object_or_404(SalaryAdvance, pk=advance_id, company=company)
    if advance.status != "pending":
        messages.warning(request, "This advance is not pending approval.")
        return redirect("payroll:salary_advances_list")
    advance.status = "approved"
    advance.save()
    messages.success(request, f"Salary advance for {advance.employee} approved.")
    return redirect("payroll:salary_advances_list")


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def bonuses_list(request):
    """
    List all bonus rules and employee bonuses.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    bonus_rules = BonusRule.objects.filter(company=company).order_by("name")
    employee_bonuses = EmployeeBonus.objects.filter(company=company).select_related(
        "employee", "rule", "payroll_run"
    ).order_by("-created_at")[:50]
    context = {
        "bonus_rules": bonus_rules,
        "employee_bonuses": employee_bonuses,
        "payroll_current_page": "bonuses",
    }
    response = render(request, "payroll/bonuses_list.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def bonus_rule_create(request):
    """
    Create a new bonus rule.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    rule = None
    if request.method == "POST":
        form = BonusRuleForm(request.POST)
        if form.is_valid():
            rule = form.save(commit=False)
            rule.account = get_account_for_user(request.user)
            rule.company = company
            rule.created_by = request.user
            rule.save()
            messages.success(request, f"Bonus rule '{rule.name}' created.")
            return redirect("payroll:bonuses_list")
    else:
        form = BonusRuleForm()
    context = {
        "form": form,
        "rule": rule,
        "payroll_current_page": "bonuses",
    }
    response = render(request, "payroll/bonus_rule_form.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def bonus_rule_edit(request, rule_id):
    """
    Edit an existing bonus rule.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    rule = get_object_or_404(BonusRule, pk=rule_id, company=company)
    if request.method == "POST":
        form = BonusRuleForm(request.POST, instance=rule)
        if form.is_valid():
            rule = form.save()
            messages.success(request, f"Bonus rule '{rule.name}' updated.")
            return redirect("payroll:bonuses_list")
    else:
        form = BonusRuleForm(instance=rule)
    context = {
        "form": form,
        "rule": rule,
        "payroll_current_page": "bonuses",
    }
    response = render(request, "payroll/bonus_rule_form.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def payroll_structures_list(request):
    """
    List all payroll structures.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    structures = PayrollStructure.objects.filter(company=company).order_by("name")
    context = {
        "structures": structures,
        "payroll_current_page": "structures",
    }
    response = render(request, "payroll/structures_list.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def payroll_structure_create(request):
    """
    Create a new payroll structure.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    if request.method == "POST":
        form = PayrollStructureForm(request.POST)
        if form.is_valid():
            structure = form.save(commit=False)
            structure.account = get_account_for_user(request.user)
            structure.company = company
            structure.created_by = request.user
            structure.save()
            messages.success(request, f"Payroll structure '{structure.name}' created.")
            return redirect("payroll:structures_list")
    else:
        form = PayrollStructureForm()
    context = {
        "form": form,
        "payroll_current_page": "structures",
    }
    response = render(request, "payroll/structure_form.html", context)
    apply_no_cache_headers(response)
    return response


def payroll_offline_sync(request):
    """
    API endpoint for offline payroll data sync.
    Accepts salary advances, loans, and bonus requests to be processed when back online.
    """
    from django.http import JsonResponse
    from django.views.decorators.csrf import csrf_exempt
    from django.views.decorators.http import require_POST
    
    @csrf_exempt
    @require_POST
    def inner(request):
        import json
        from .models import SalaryAdvance, EmployeeLoan, BonusRule
        from apps.core.ownership import get_account_for_user
        from apps.core.utils import get_company_profile_for_user
        
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        account = get_account_for_user(request.user)
        if not account:
            return JsonResponse({'error': 'No account found'}, status=403)
        
        company = get_company_profile_for_user(request.user, request)
        
        try:
            data = json.loads(request.body) if isinstance(request.body, str) else request.data
        except:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        
        if not isinstance(data, dict):
            return JsonResponse({'error': 'Expected JSON object'}, status=400)
        
        created_items = []
        errors = []
        
        for item in data.get('salary_advances', []):
            try:
                advance = SalaryAdvance.objects.create(
                    employee_id=item.get('employee_id'),
                    company=company,
                    amount=item.get('amount', 0),
                    reason=item.get('reason', ''),
                    status='pending' if item.get('status') is None else item.get('status'),
                    requested_by=request.user
                )
                created_items.append({'type': 'salary_advance', 'id': advance.id})
            except Exception as e:
                errors.append({'type': 'salary_advance', 'error': str(e), 'data': item})
        
        for item in data.get('loans', []):
            try:
                loan = EmployeeLoan.objects.create(
                    employee_id=item.get('employee_id'),
                    company=company,
                    principal_amount=item.get('principal_amount', 0),
                    interest_rate=item.get('interest_rate', 0),
                    tenure_months=item.get('tenure_months', 1),
                    reason=item.get('reason', ''),
                    status='pending' if item.get('status') is None else item.get('status'),
                    created_by=request.user
                )
                created_items.append({'type': 'loan', 'id': loan.id})
            except Exception as e:
                errors.append({'type': 'loan', 'error': str(e), 'data': item})
        
        for item in data.get('bonuses', []):
            try:
                bonus = BonusRule.objects.create(
                    company=company,
                    name=item.get('name', ''),
                    bonus_type=item.get('bonus_type', 'performance'),
                    calculation_type=item.get('calculation_type', 'fixed'),
                    amount=item.get('amount', 0),
                    percentage=item.get('percentage', 0),
                    is_active=item.get('is_active', True)
                )
                created_items.append({'type': 'bonus', 'id': bonus.id})
            except Exception as e:
                errors.append({'type': 'bonus', 'error': str(e), 'data': item})
        
        return JsonResponse({
            'success': True,
            'created_count': len(created_items),
            'created_items': created_items,
            'errors': errors
        })
    
    return inner(request)


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def files_list(request):
    """
    List all payroll files with filtering and search.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")

    query = request.GET.get("q", "")
    category_id = request.GET.get("category", "")
    file_type = request.GET.get("type", "")
    year = request.GET.get("year", "")
    month = request.GET.get("month", "")
    show_archived = request.GET.get("archived", "false") == "true"
    show_starred = request.GET.get("starred", "false") == "true"

    files_qs = PayrollFile.objects.filter(company=company).select_related(
        "category", "employee", "payroll_period", "created_by"
    ).order_by("-created_at")

    if query:
        files_qs = files_qs.filter(
            Q(title__icontains=query) |
            Q(original_filename__icontains=query) |
            Q(description__icontains=query) |
            Q(tags__icontains=query)
        )

    if category_id:
        files_qs = files_qs.filter(category_id=category_id)

    if file_type:
        files_qs = files_qs.filter(file_type=file_type)

    if year:
        files_qs = files_qs.filter(year=year)

    if month:
        files_qs = files_qs.filter(month=month)

    if show_archived:
        files_qs = files_qs.filter(is_archived=True)
    else:
        files_qs = files_qs.filter(is_archived=False)

    if show_starred:
        files_qs = files_qs.filter(is_starred=True)

    categories = FileCategory.objects.filter(company=company, is_active=True)
    years = PayrollFile.objects.filter(company=company).exclude(year__isnull=True).values_list(
        "year", flat=True
    ).distinct().order_by("-year")

    total_files = files_qs.count()
    total_size = sum(f.file_size for f in files_qs)

    context = {
        "files": files_qs,
        "categories": categories,
        "years": years,
        "total_files": total_files,
        "total_size": total_size,
        "payroll_current_page": "files",
        "query": query,
        "selected_category": category_id,
        "selected_type": file_type,
        "selected_year": year,
        "selected_month": month,
        "show_archived": show_archived,
        "show_starred": show_starred,
    }
    response = render(request, "payroll/files_list.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.upload_payroll_file", raise_exception=True)
def files_upload(request):
    """
    Upload payroll files with smart categorization.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    account = get_account_for_user(request.user)

    if request.method == "POST":
        form = PayrollFileUploadForm(request.POST)
        files = request.FILES.getlist("file")

        if not files:
            messages.error(request, "Please select at least one file to upload.")
            return redirect("payroll:files_upload")

        uploaded_count = 0
        errors = []

        for uploaded_file in files:
            try:
                result = FileProcessor.process_upload(
                    uploaded_file, company.id, request.user.id
                )

                payroll_file = PayrollFile(
                    account=account,
                    company=company,
                    created_by=request.user,
                    file=uploaded_file,
                    original_filename=result["original_filename"],
                    file_type=result["file_type"],
                    mime_type=result["mime_type"],
                    file_size=result["file_size"],
                    title=result["title"],
                    month=result["month"],
                    year=result["year"],
                )

                if result.get("category_hint"):
                    category = FileCategory.objects.filter(
                        company=company, category_type=result["category_hint"]
                    ).first()
                    if category:
                        payroll_file.category = category

                if request.POST.get("title") and uploaded_count == 0:
                    payroll_file.title = request.POST["title"]
                if request.POST.get("description"):
                    if uploaded_count == 0:
                        payroll_file.description = request.POST["description"]
                if request.POST.get("category"):
                    category_id = request.POST["category"]
                    if category_id:
                        payroll_file.category_id = category_id
                if request.POST.get("employee"):
                    payroll_file.employee_id = request.POST["employee"]
                if request.POST.get("month"):
                    payroll_file.month = int(request.POST["month"])
                if request.POST.get("year"):
                    payroll_file.year = int(request.POST["year"])
                if request.POST.get("tags"):
                    payroll_file.tags = request.POST["tags"]

                payroll_file.save()
                uploaded_count += 1

                FileAccessLog.objects.create(
                    account=account,
                    company=company,
                    user=request.user,
                    file=payroll_file,
                    action="view",
                    ip_address=_get_client_ip(request),
                    user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
                )

            except ValueError as e:
                errors.append(f"{uploaded_file.name}: {str(e)}")
            except Exception as e:
                errors.append(f"{uploaded_file.name}: Upload failed - {str(e)}")

        if uploaded_count > 0:
            msg = f"Successfully uploaded {uploaded_count} file(s)."
            if len(errors) > 0:
                msg += f" {len(errors)} file(s) failed."
            messages.success(request, msg)

        if errors and uploaded_count == 0:
            for error in errors:
                messages.error(request, error)

        return redirect("payroll:files_list")

    form = PayrollFileUploadForm()
    categories = FileCategory.objects.filter(company=company, is_active=True)
    employees = Employee.objects.filter(
        account=account, company=company, is_deleted=False
    ).order_by("last_name", "first_name")
    periods = PayrollPeriod.objects.filter(company=company).order_by("-year", "-month")[:12]
    current_year = date.today().year
    years = list(range(current_year - 5, current_year + 1))

    context = {
        "form": form,
        "categories": categories,
        "employees": employees,
        "periods": periods,
        "years": years,
        "payroll_current_page": "files",
    }
    response = render(request, "payroll/files_upload.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def files_search(request):
    """
    Search payroll files with advanced filtering.
    """
    company = _company(request)
    if not company:
        return JsonResponse({"error": "Company not found"}, status=404)

    query = request.GET.get("q", "")
    category_id = request.GET.get("category", "")
    file_type = request.GET.get("type", "")
    year = request.GET.get("year", "")
    month = request.GET.get("month", "")
    employee_id = request.GET.get("employee", "")

    files_qs = PayrollFile.objects.filter(
        company=company, is_archived=False
    ).select_related("category", "employee", "created_by")

    if query:
        files_qs = files_qs.filter(
            Q(title__icontains=query) |
            Q(original_filename__icontains=query) |
            Q(description__icontains=query) |
            Q(tags__icontains=query)
        )

    if category_id:
        files_qs = files_qs.filter(category_id=category_id)

    if file_type:
        files_qs = files_qs.filter(file_type=file_type)

    if year:
        files_qs = files_qs.filter(year=year)

    if month:
        files_qs = files_qs.filter(month=month)

    if employee_id:
        files_qs = files_qs.filter(employee_id=employee_id)

    results = []
    for f in files_qs[:50]:
        icon, color = get_file_icon(f.file_type)
        results.append({
            "id": f.id,
            "title": f.title,
            "original_filename": f.original_filename,
            "file_type": f.file_type,
            "icon": icon,
            "color": color,
            "file_size": f.file_size_display,
            "category": f.category.name if f.category else None,
            "employee": str(f.employee) if f.employee else None,
            "period": f.period_display,
            "created_at": f.created_at.isoformat(),
            "is_starred": f.is_starred,
            "url": f.file.url if f.file else None,
        })

    return JsonResponse({"results": results, "count": files_qs.count()})


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def file_detail(request, file_id):
    """
    View file details.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")

    payroll_file = get_object_or_404(
        PayrollFile.objects.select_related("category", "employee", "payroll_period", "created_by"),
        pk=file_id,
        company=company,
    )

    access_logs = payroll_file.access_logs.all()[:10]

    context = {
        "payroll_file": payroll_file,
        "access_logs": access_logs,
        "payroll_current_page": "files",
    }
    response = render(request, "payroll/file_detail.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def file_edit(request, file_id):
    """
    Edit file metadata.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    account = get_account_for_user(request.user)

    payroll_file = get_object_or_404(PayrollFile, pk=file_id, company=company)

    if request.method == "POST":
        form = PayrollFileEditForm(request.POST, instance=payroll_file)
        if form.is_valid():
            form.save()
            messages.success(request, "File metadata updated successfully.")
            return redirect("payroll:file_detail", file_id=file_id)
    else:
        form = PayrollFileEditForm(instance=payroll_file)

    categories = FileCategory.objects.filter(company=company, is_active=True)
    employees = Employee.objects.filter(
        account=account, company=company, is_deleted=False
    ).order_by("last_name", "first_name")
    periods = PayrollPeriod.objects.filter(company=company).order_by("-year", "-month")

    context = {
        "form": form,
        "payroll_file": payroll_file,
        "categories": categories,
        "employees": employees,
        "periods": periods,
        "payroll_current_page": "files",
    }
    response = render(request, "payroll/file_edit.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def file_download(request, file_id):
    """
    Download a payroll file.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    account = get_account_for_user(request.user)

    payroll_file = get_object_or_404(PayrollFile, pk=file_id, company=company)

    if not payroll_file.file:
        raise Http404("File not found")

    payroll_file.download_count += 1
    payroll_file.save(update_fields=["download_count"])

    FileAccessLog.objects.create(
        account=account,
        company=company,
        user=request.user,
        file=payroll_file,
        action="download",
        ip_address=_get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )

    response = HttpResponse(payroll_file.file, content_type=payroll_file.mime_type)
    response["Content-Disposition"] = f'attachment; filename="{payroll_file.original_filename}"'
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def file_preview(request, file_id):
    """
    Preview a payroll file (for images and PDFs).
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    account = get_account_for_user(request.user)

    payroll_file = get_object_or_404(PayrollFile, pk=file_id, company=company)

    if not payroll_file.file:
        raise Http404("File not found")

    if not FileTypeDetector.is_previewable(payroll_file.file_type):
        return JsonResponse({"error": "File type not previewable"}, status=400)

    payroll_file.view_count += 1
    payroll_file.save(update_fields=["view_count"])

    FileAccessLog.objects.create(
        account=account,
        company=company,
        user=request.user,
        file=payroll_file,
        action="view",
        ip_address=_get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )

    response = HttpResponse(payroll_file.file, content_type=payroll_file.mime_type)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.delete_payroll_file", raise_exception=True)
@require_POST
def file_delete(request, file_id):
    """
    Delete a payroll file.
    """
    company = _company(request)
    if not company:
        return JsonResponse({"error": "Company not found"}, status=404)

    payroll_file = get_object_or_404(PayrollFile, pk=file_id, company=company)

    FileAccessLog.objects.create(
        company=company,
        user=request.user,
        file=payroll_file,
        action="delete",
        ip_address=_get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )

    payroll_file.file.delete(save=True)
    payroll_file.delete()

    messages.success(request, "File deleted successfully.")
    return redirect("payroll:files_list")


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
@require_POST
def file_toggle_star(request, file_id):
    """
    Toggle star status of a file.
    """
    company = _company(request)
    if not company:
        return JsonResponse({"error": "Company not found"}, status=404)

    payroll_file = get_object_or_404(PayrollFile, pk=file_id, company=company)
    payroll_file.is_starred = not payroll_file.is_starred
    payroll_file.save(update_fields=["is_starred"])

    return JsonResponse({"is_starred": payroll_file.is_starred})


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
@require_POST
def file_toggle_archive(request, file_id):
    """
    Toggle archive status of a file.
    """
    company = _company(request)
    if not company:
        return JsonResponse({"error": "Company not found"}, status=404)

    payroll_file = get_object_or_404(PayrollFile, pk=file_id, company=company)
    payroll_file.is_archived = not payroll_file.is_archived
    payroll_file.save(update_fields=["is_archived"])

    return JsonResponse({"is_archived": payroll_file.is_archived})


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def excel_extract(request, file_id):
    """
    Extract and view data from an Excel file.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")

    payroll_file = get_object_or_404(PayrollFile, pk=file_id, company=company)

    if payroll_file.file_type != "excel":
        messages.warning(request, "This feature only works with Excel files.")
        return redirect("payroll:file_detail", file_id=file_id)

    if not payroll_file.file:
        raise Http404("File not found")

    excel_data = payroll_file.excel_data.all()
    extracted_records = ExtractedPayrollRecord.objects.filter(
        payroll_file=payroll_file
    ).select_related("employee")

    parser = ExcelParser(payroll_file.file.path)
    sheet_info = []
    records_preview = []
    has_parsed = False

    if parser.load():
        sheet_info = parser.get_sheet_info()
        records_preview = parser.parse_all_sheets()
        has_parsed = True

    context = {
        "payroll_file": payroll_file,
        "sheet_info": sheet_info,
        "records_preview": records_preview,
        "excel_data": excel_data,
        "extracted_records": extracted_records,
        "has_parsed": has_parsed,
        "payroll_current_page": "files",
    }
    response = render(request, "payroll/excel_extract.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def excel_parse_and_save(request, file_id):
    """
    Parse Excel file and save extracted data to database.
    """
    from django.db import transaction
    
    company = _company(request)
    if not company:
        return JsonResponse({"error": "Company not found"}, status=404)
    account = get_account_for_user(request.user)

    payroll_file = get_object_or_404(PayrollFile, pk=file_id, company=company)

    if payroll_file.file_type != "excel":
        return JsonResponse({"error": "Not an Excel file"}, status=400)

    if not payroll_file.file:
        return JsonResponse({"error": "File not found"}, status=404)

    try:
        success, result = parse_excel_file(payroll_file.file.path)
        
        if not success:
            return JsonResponse({"error": result.get("errors", ["Unknown error"])}, status=400)

        with transaction.atomic():
            ExcelData.objects.filter(payroll_file=payroll_file).delete()
            ExtractedPayrollRecord.objects.filter(payroll_file=payroll_file).delete()

            records_created = 0
            for record in result.get("records", []):
                excel_data = ExcelData.objects.create(
                    account=account,
                    company=company,
                    created_by=request.user,
                    payroll_file=payroll_file,
                    sheet_name=record.get("sheet_name", ""),
                    data=record.get("raw_data", {}),
                    period_month=record.get("period", {}).get("month"),
                    period_year=record.get("period", {}).get("year"),
                    row_number=record.get("row_number", 0),
                )

                emp_name = record.get("employee_name", "")
                emp_id = record.get("employee_id", "")
                
                matched_employee = None
                if emp_id:
                    matched_employee = Employee.objects.filter(
                        account=account, company=company
                    ).filter(
                        Q(employee_id=emp_id) | Q(email__icontains=emp_id)
                    ).first()
                elif emp_name:
                    matched_employee = Employee.objects.filter(
                        account=account, company=company
                    ).filter(
                        Q(first_name__icontains=emp_name) | 
                        Q(last_name__icontains=emp_name) |
                        Q(email__icontains=emp_name)
                    ).first()

                extracted_record = ExtractedPayrollRecord.objects.create(
                    account=account,
                    company=company,
                    created_by=request.user,
                    payroll_file=payroll_file,
                    excel_data=excel_data,
                    employee=matched_employee,
                    employee_name=emp_name,
                    employee_identifier=emp_id,
                    period_month=record.get("period", {}).get("month"),
                    period_year=record.get("period", {}).get("year"),
                    basic_salary=record.get("basic_salary"),
                    allowances=record.get("allowances"),
                    bonuses=record.get("bonuses"),
                    overtime=record.get("overtime"),
                    gross_salary=record.get("gross_salary"),
                    pension=record.get("pension"),
                    nhf=record.get("nhf"),
                    tax=record.get("tax"),
                    loan_deduction=record.get("loan_deduction"),
                    other_deductions=record.get("other_deductions"),
                    net_salary=record.get("net_salary"),
                    raw_data=record.get("raw_data", {}),
                    is_linked_to_employee=matched_employee is not None,
                )
                records_created += 1

        return JsonResponse({
            "success": True,
            "message": f"Successfully extracted and saved {records_created} records",
            "records_count": records_created,
            "sheets_count": len(result.get("sheets", [])),
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def excel_records_list(request):
    """
    List all extracted payroll records.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    account = get_account_for_user(request.user)

    query = request.GET.get("q", "")
    year = request.GET.get("year", "")
    month = request.GET.get("month", "")
    verified = request.GET.get("verified", "")
    linked = request.GET.get("linked", "")

    records_qs = ExtractedPayrollRecord.objects.filter(
        company=company
    ).select_related("employee", "payroll_file")

    if query:
        records_qs = records_qs.filter(
            Q(employee_name__icontains=query) |
            Q(employee_id__icontains=query)
        )
    if year:
        records_qs = records_qs.filter(period_year=year)
    if month:
        records_qs = records_qs.filter(period_month=month)
    if verified == "yes":
        records_qs = records_qs.filter(is_verified=True)
    elif verified == "no":
        records_qs = records_qs.filter(is_verified=False)
    if linked == "yes":
        records_qs = records_qs.filter(is_linked_to_employee=True)
    elif linked == "no":
        records_qs = records_qs.filter(is_linked_to_employee=False)

    years = ExtractedPayrollRecord.objects.filter(company=company).exclude(
        period_year__isnull=True
    ).values_list("period_year", flat=True).distinct().order_by("-period_year")

    context = {
        "records": records_qs,
        "years": years,
        "query": query,
        "selected_year": year,
        "selected_month": month,
        "selected_verified": verified,
        "selected_linked": linked,
        "payroll_current_page": "excel_records",
    }
    response = render(request, "payroll/excel_records_list.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def excel_records_link_employee(request, record_id):
    """
    Link an extracted record to an employee.
    """
    company = _company(request)
    if not company:
        return JsonResponse({"error": "Company not found"}, status=404)
    account = get_account_for_user(request.user)

    record = get_object_or_404(ExtractedPayrollRecord, pk=record_id, company=company)

    if request.method == "POST":
        employee_id = request.POST.get("employee_id")
        if employee_id:
            employee = get_object_or_404(
                Employee, pk=employee_id, account=account, company=company
            )
            record.employee = employee
            record.is_linked_to_employee = True
            record.save(update_fields=["employee", "is_linked_to_employee"])
            messages.success(request, f"Linked to {employee.full_name}")
        else:
            record.employee = None
            record.is_linked_to_employee = False
            record.save(update_fields=["employee", "is_linked_to_employee"])
            messages.success(request, "Employee link removed")

    return redirect("payroll:excel_records_list")


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def excel_records_verify(request, record_id):
    """
    Verify an extracted record.
    """
    company = _company(request)
    if not company:
        return JsonResponse({"error": "Company not found"}, status=404)

    record = get_object_or_404(ExtractedPayrollRecord, pk=record_id, company=company)
    record.is_verified = not record.is_verified
    record.save(update_fields=["is_verified"])

    return JsonResponse({"is_verified": record.is_verified})


@login_required
@never_cache
@company_admin_or_permission_required("payroll.manage_payroll_files", raise_exception=True)
def file_categories_list(request):
    """
    List file categories.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")

    categories = FileCategory.objects.filter(company=company).order_by("name")

    context = {
        "categories": categories,
        "payroll_current_page": "file_categories",
    }
    response = render(request, "payroll/file_categories_list.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.manage_payroll_files", raise_exception=True)
def file_category_create(request):
    """
    Create a new file category.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    account = get_account_for_user(request.user)

    if request.method == "POST":
        form = FileCategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            category.account = account
            category.company = company
            category.created_by = request.user
            category.save()
            messages.success(request, f"Category '{category.name}' created.")
            return redirect("payroll:file_categories_list")
    else:
        form = FileCategoryForm()

    context = {
        "form": form,
        "payroll_current_page": "file_categories",
    }
    response = render(request, "payroll/file_category_form.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.manage_payroll_files", raise_exception=True)
def file_category_edit(request, category_id):
    """
    Edit a file category.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")

    category = get_object_or_404(FileCategory, pk=category_id, company=company)

    if request.method == "POST":
        form = FileCategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, f"Category '{category.name}' updated.")
            return redirect("payroll:file_categories_list")
    else:
        form = FileCategoryForm(instance=category)

    context = {
        "form": form,
        "category": category,
        "payroll_current_page": "file_categories",
    }
    response = render(request, "payroll/file_category_form.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.manage_payroll_files", raise_exception=True)
def template_list(request):
    """
    List all payroll templates.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")

    templates = PayrollTemplate.objects.filter(company=company).order_by("-usage_count", "-created_at")

    context = {
        "templates": templates,
        "payroll_current_page": "templates",
    }
    response = render(request, "payroll/template_list.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.upload_payroll_file", raise_exception=True)
def template_create_from_file(request, file_id):
    """
    Create a template from an uploaded Excel file.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    account = get_account_for_user(request.user)

    payroll_file = get_object_or_404(PayrollFile, pk=file_id, company=company)

    if payroll_file.file_type != "excel":
        messages.warning(request, "This feature only works with Excel files.")
        return redirect("payroll:file_detail", file_id=file_id)

    if not payroll_file.file:
        raise Http404("File not found")

    if request.method == "POST":
        template_name = request.POST.get("name", f"Template from {payroll_file.original_filename}")
        
        success, result = create_template_from_excel(
            payroll_file.file.path,
            company.id,
            request.user.id,
            template_name
        )

        if success:
            template = PayrollTemplate.objects.create(
                account=account,
                company=company,
                created_by=request.user,
                name=result["name"],
                description=f"Auto-generated from {payroll_file.original_filename}",
                columns=result["columns"],
                column_order=result["column_order"],
                sample_data=result["sample_data"],
                min_rows=result.get("min_rows", 0),
                max_rows=result.get("max_rows", 0),
                detected_from_file=payroll_file,
            )
            
            messages.success(request, f"Template '{template.name}' created successfully!")
            return redirect("payroll:template_detail", template_id=template.id)
        else:
            messages.error(request, result.get("error", "Failed to create template"))

    context = {
        "payroll_file": payroll_file,
        "payroll_current_page": "templates",
    }
    response = render(request, "payroll/template_create.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def template_detail(request, template_id):
    """
    View template details with columns configuration.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")

    template = get_object_or_404(PayrollTemplate, pk=template_id, company=company)

    context = {
        "template": template,
        "payroll_current_page": "templates",
    }
    response = render(request, "payroll/template_detail.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.use_payroll_template", raise_exception=True)
def template_fill_form(request, template_id):
    """
    Fill payroll data using the dynamic form based on template.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    account = get_account_for_user(request.user)

    template = get_object_or_404(PayrollTemplate, pk=template_id, company=company)
    
    template.usage_count += 1
    template.save(update_fields=["usage_count"])

    employees = Employee.objects.filter(
        account=account, company=company, is_deleted=False, status="active"
    ).order_by("last_name", "first_name")

    if request.method == "POST":
        period_month = request.POST.get("period_month")
        period_year = request.POST.get("period_year")
        title = request.POST.get("title", f"Payroll {period_month}/{period_year}")
        
        rows_data = []
        row_count = 0
        
        for key, value in request.POST.items():
            if key.startswith("row_"):
                parts = key.split("_", 2)
                if len(parts) >= 3:
                    row_num = parts[1]
                    col_name = parts[2]
                    row_key = f"row_{row_num}"
                    
                    if row_key not in rows_data:
                        rows_data.append({})
                    
                    row_idx = int(row_num)
                    while len(rows_data) <= row_idx:
                        rows_data.append({})
                    
                    rows_data[row_idx][col_name] = value

        entry = PayrollEntry.objects.create(
            account=account,
            company=company,
            created_by=request.user,
            updated_by=request.user,
            template=template,
            period_month=int(period_month) if period_month else None,
            period_year=int(period_year) if period_year else None,
            title=title,
            data={"rows": rows_data, "columns": template.columns},
            row_count=len(rows_data),
            status="completed",
        )
        
        messages.success(request, f"Payroll entry '{title}' saved successfully!")
        return redirect("payroll:entry_detail", entry_id=entry.id)

    current_year = date.today().year
    years = list(range(current_year - 2, current_year + 1))
    current_month = date.today().month

    months = [
        {"value": 1, "name": "January"},
        {"value": 2, "name": "February"},
        {"value": 3, "name": "March"},
        {"value": 4, "name": "April"},
        {"value": 5, "name": "May"},
        {"value": 6, "name": "June"},
        {"value": 7, "name": "July"},
        {"value": 8, "name": "August"},
        {"value": 9, "name": "September"},
        {"value": 10, "name": "October"},
        {"value": 11, "name": "November"},
        {"value": 12, "name": "December"},
    ]

    context = {
        "template": template,
        "employees": employees,
        "years": years,
        "months": months,
        "current_month": current_month,
        "payroll_current_page": "templates",
    }
    response = render(request, "payroll/template_fill_form.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def template_add_row(request, template_id):
    """
    Return HTML for a new row in the dynamic form.
    """
    if not request.headers.get("x-requested-with") == "XMLHttpRequest":
        return Http404("Invalid request")

    template = get_object_or_404(PayrollTemplate, pk=template_id)
    row_num = int(request.GET.get("row_num", 0))

    html = render_to_string("payroll/partials/form_row.html", {
        "template": template,
        "row_num": row_num,
    })

    return HttpResponse(html)


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def entry_list(request):
    """
    List all payroll entries.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")

    entries = PayrollEntry.objects.filter(company=company).select_related(
        "template", "source_file", "created_by"
    ).order_by("-created_at")

    context = {
        "entries": entries,
        "payroll_current_page": "entries",
    }
    response = render(request, "payroll/entry_list.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def entry_detail(request, entry_id):
    """
    View entry details.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")

    entry = get_object_or_404(PayrollEntry, pk=entry_id, company=company)

    context = {
        "entry": entry,
        "payroll_current_page": "entries",
    }
    response = render(request, "payroll/entry_detail.html", context)
    apply_no_cache_headers(response)
    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.edit_payroll", raise_exception=True)
def template_entry_continue(request, template_id, entry_id):
    """
    Continue editing an existing entry.
    """
    company = _company(request)
    if not company:
        raise Http404("Company not found")
    account = get_account_for_user(request.user)

    template = get_object_or_404(PayrollTemplate, pk=template_id, company=company)
    entry = get_object_or_404(PayrollEntry, pk=entry_id, company=company, template=template)

    if request.method == "POST":
        period_month = request.POST.get("period_month")
        period_year = request.POST.get("period_year")
        title = request.POST.get("title", entry.title)
        
        rows_data = []
        for key, value in request.POST.items():
            if key.startswith("row_"):
                parts = key.split("_", 2)
                if len(parts) >= 3:
                    row_num = parts[1]
                    col_name = parts[2]
                    row_key = f"row_{row_num}"
                    
                    if row_key not in rows_data:
                        rows_data.append({})
                    
                    row_idx = int(row_num)
                    while len(rows_data) <= row_idx:
                        rows_data.append({})
                    
                    rows_data[row_idx][col_name] = value

        entry.title = title
        entry.period_month = int(period_month) if period_month else None
        entry.period_year = int(period_year) if period_year else None
        entry.data = {"rows": rows_data, "columns": template.columns}
        entry.row_count = len(rows_data)
        entry.updated_by = request.user
        entry.save()

        messages.success(request, f"Entry '{title}' updated successfully!")
        return redirect("payroll:entry_detail", entry_id=entry.id)

    employees = Employee.objects.filter(
        account=account, company=company, is_deleted=False, status="active"
    ).order_by("last_name", "first_name")
    
    current_year = date.today().year
    years = list(range(current_year - 2, current_year + 1))
    
    months = [
        {"value": 1, "name": "January"},
        {"value": 2, "name": "February"},
        {"value": 3, "name": "March"},
        {"value": 4, "name": "April"},
        {"value": 5, "name": "May"},
        {"value": 6, "name": "June"},
        {"value": 7, "name": "July"},
        {"value": 8, "name": "August"},
        {"value": 9, "name": "September"},
        {"value": 10, "name": "October"},
        {"value": 11, "name": "November"},
        {"value": 12, "name": "December"},
    ]

    context = {
        "template": template,
        "entry": entry,
        "employees": employees,
        "years": years,
        "months": months,
        "payroll_current_page": "entries",
    }
    response = render(request, "payroll/template_fill_form.html", context)
    apply_no_cache_headers(response)
    return response


def _get_client_ip(request):
    """Get client IP address from request."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def entry_export(request, entry_id):
    """
    Export a payroll entry to Excel format.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        messages.error(request, "openpyxl is required for export functionality")
        return redirect("payroll:entry_detail", entry_id=entry_id)

    company = _company(request)
    if not company:
        raise Http404("Company not found")

    entry = get_object_or_404(PayrollEntry, pk=entry_id, company=company)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payroll Data"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    title_cell = ws.cell(row=1, column=1, value=entry.title)
    title_cell.font = Font(bold=True, size=14)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(entry.data.get('columns', [])))

    info_row = 2
    if entry.period_month and entry.period_year:
        period_cell = ws.cell(row=info_row, column=1, value=f"Period: {entry.period_month}/{entry.period_year}")
        period_cell.font = Font(italic=True)
        ws.merge_cells(start_row=info_row, start_column=1, end_row=info_row, end_column=3)

    header_row = 4
    columns = entry.data.get('columns', [])
    for col_idx, col in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=col.get('label', col.get('key', f'Column {col_idx}')))
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    data_rows = entry.data.get('rows', [])
    for row_idx, row_data in enumerate(data_rows, start=header_row + 1):
        for col_idx, col in enumerate(columns, start=1):
            key = col.get('key', '')
            value = row_data.get(key, '')
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border

            col_type = col.get('type', 'text')
            if col_type in ('decimal', 'number', 'integer'):
                cell.alignment = Alignment(horizontal="right")

    for col_idx in range(1, len(columns) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 15

    filename = f"{entry.title.replace(' ', '_')}_{entry.period_month}_{entry.period_year}.xlsx"
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)

    return response


@login_required
@never_cache
@company_admin_or_permission_required("payroll.view_payroll", raise_exception=True)
def entries_export_all(request):
    """
    Export all payroll entries to Excel format.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        messages.error(request, "openpyxl is required for export functionality")
        return redirect("payroll:entry_list")

    company = _company(request)
    if not company:
        raise Http404("Company not found")

    entries = PayrollEntry.objects.filter(company=company).select_related(
        "template", "created_by"
    ).order_by("-created_at")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Payroll Entries"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    headers = ["Title", "Template", "Period", "Rows", "Status", "Created By", "Created At", "Updated At"]
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    for row_idx, entry in enumerate(entries, start=2):
        ws.cell(row=row_idx, column=1, value=entry.title).border = thin_border
        ws.cell(row=row_idx, column=2, value=str(entry.template.name) if entry.template else "N/A").border = thin_border
        ws.cell(row=row_idx, column=3, value=f"{entry.period_month}/{entry.period_year}" if entry.period_month and entry.period_year else "N/A").border = thin_border
        ws.cell(row=row_idx, column=4, value=entry.row_count).border = thin_border
        ws.cell(row=row_idx, column=5, value=entry.status).border = thin_border
        ws.cell(row=row_idx, column=6, value=str(entry.created_by.get_full_name() or entry.created_by.username)).border = thin_border
        ws.cell(row=row_idx, column=7, value=entry.created_at.strftime("%Y-%m-%d %H:%M")).border = thin_border
        ws.cell(row=row_idx, column=8, value=entry.updated_at.strftime("%Y-%m-%d %H:%M")).border = thin_border

    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 20

    filename = f"payroll_entries_{date.today().strftime('%Y%m%d')}.xlsx"
    response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    wb.save(response)

    return response


from django.template.loader import render_to_string

