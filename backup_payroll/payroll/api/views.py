from datetime import date

from django.db.models import Q
from rest_framework import viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.ownership import drf_filter_queryset_for_user, get_account_for_user
from apps.core.utils import get_company_profile_for_user
from apps.core.permissions import DjangoModelPermissions

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
from ..services import generate_payroll_run, generate_payslip
from ..analytics import get_payroll_dashboard_metrics
from ..file_processor import get_file_icon
from .serializers import (
    PayrollStructureSerializer,
    EmployeePayrollProfileSerializer,
    PayrollPeriodSerializer,
    PayrollRunSerializer,
    PayrollItemSerializer,
    PayslipSerializer,
    BonusRuleSerializer,
    EmployeeBonusSerializer,
    EmployeeLoanSerializer,
    LoanRepaymentSerializer,
    SalaryAdvanceSerializer,
    PayrollFileSerializer,
    FileCategorySerializer,
)


class BaseTenantViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    account_lookup = "company__account"

    def get_queryset(self):
        qs = super().get_queryset()
        return drf_filter_queryset_for_user(qs, self.request, account_lookup=self.account_lookup)

    def perform_create(self, serializer):
        account = get_account_for_user(self.request.user)
        company = get_company_profile_for_user(self.request.user, self.request)
        serializer.save(account=account, company=company, created_by=self.request.user)


class PayrollStructureViewSet(BaseTenantViewSet):
    queryset = PayrollStructure.objects.all()
    serializer_class = PayrollStructureSerializer


class EmployeePayrollProfileViewSet(BaseTenantViewSet):
    queryset = EmployeePayrollProfile.objects.select_related("employee", "payroll_structure")
    serializer_class = EmployeePayrollProfileSerializer


class PayrollPeriodViewSet(BaseTenantViewSet):
    queryset = PayrollPeriod.objects.all()
    serializer_class = PayrollPeriodSerializer


class PayrollRunViewSet(BaseTenantViewSet):
    queryset = PayrollRun.objects.select_related("period", "structure")
    serializer_class = PayrollRunSerializer

    @action(detail=True, methods=["post"])
    def generate_payslips(self, request, pk=None):
        run = self.get_object()
        if run.status not in ("approved", "paid"):
            return Response({"detail": "Payslips can only be generated for approved payroll."}, status=400)
        count = 0
        for item in run.items.select_related("employee"):
            generate_payslip(item, created_by=request.user)
            count += 1
        return Response({"detail": f"Payslips generated for {count} employees."})


class PayrollItemViewSet(BaseTenantViewSet):
    queryset = PayrollItem.objects.select_related("employee", "payroll_run", "payroll_run__period")
    serializer_class = PayrollItemSerializer


class PayslipViewSet(BaseTenantViewSet):
    queryset = Payslip.objects.select_related("employee", "period")
    serializer_class = PayslipSerializer


class BonusRuleViewSet(BaseTenantViewSet):
    queryset = BonusRule.objects.all()
    serializer_class = BonusRuleSerializer


class EmployeeBonusViewSet(BaseTenantViewSet):
    queryset = EmployeeBonus.objects.select_related("employee", "rule", "payroll_run")
    serializer_class = EmployeeBonusSerializer


class EmployeeLoanViewSet(BaseTenantViewSet):
    queryset = EmployeeLoan.objects.select_related("employee")
    serializer_class = EmployeeLoanSerializer


class LoanRepaymentViewSet(BaseTenantViewSet):
    queryset = LoanRepayment.objects.select_related("loan", "payroll_item")
    serializer_class = LoanRepaymentSerializer


class SalaryAdvanceViewSet(BaseTenantViewSet):
    queryset = SalaryAdvance.objects.select_related("employee")
    serializer_class = SalaryAdvanceSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payroll_dashboard_metrics_api(request):
    """
    Lightweight API for realtime payroll dashboard metrics (poll from JS without page reload).
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return Response({"detail": "No company profile"}, status=403)
    try:
        year = int(request.GET.get("year") or date.today().year)
    except (TypeError, ValueError):
        year = date.today().year
    metrics = get_payroll_dashboard_metrics(company, year=year)

    def _to_str_map(d):
        # Convert Decimals to strings for JSON safety
        out = {}
        for k, v in d.items():
            if isinstance(v, (list, tuple)):
                out[k] = v
            else:
                try:
                    # Decimals and other numerics become strings; simple types pass through
                    out[k] = str(v)
                except Exception:
                    out[k] = v
        return out

    response_data = {
        "year": year,
        "total_payroll_cost": str(metrics["total_payroll_cost"]),
        "total_tax": str(metrics["total_tax"]),
        "total_pension": str(metrics["total_pension"]),
        "total_nhf": str(metrics["total_nhf"]),
        "total_net": str(metrics["total_net"]),
        "total_employees_paid": metrics["total_employees_paid"],
        "monthly_trend": [
            {
                "month": row["period__month"],
                "total": str(row["total"]),
            }
            for row in metrics["monthly_trend"]
        ],
        "department_cost": [
            {
                "department": row["employee__department__name"],
                "total": str(row["total"]),
                "count": row["count"],
            }
            for row in metrics["department_cost"]
        ],
        "salary_distribution": [
            {
                "basic_salary": str(row["basic_salary"]),
                "count": row["count"],
            }
            for row in metrics["salary_distribution"]
        ],
    }
    return Response(response_data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payroll_runs_list_api(request):
    """
    Lightweight runs list for realtime polling on the payroll list page.
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return Response({"detail": "No company profile"}, status=403)
    qs = (
        PayrollRun.objects.filter(company=company)
        .select_related("period")
        .order_by("-created_at")[:50]
    )
    data = [
        {
            "id": run.id,
            "period": str(run.period),
            "status": run.status,
            "status_display": run.get_status_display(),
            "total_gross": str(run.total_gross),
            "total_net": str(run.total_net),
            "period_id": run.period_id,
        }
        for run in qs
    ]
    return Response({"results": data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payroll_period_items_api(request, period_id):
    """
    List payroll items for a given period (used by summary and other reports for realtime refresh).
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return Response({"detail": "No company profile"}, status=403)
    items = (
        PayrollItem.objects.filter(
            company=company, payroll_run__period_id=period_id
        )
        .select_related("employee")
        .order_by("employee__last_name", "employee__first_name")
    )
    rows = []
    total_cost = total_deductions = total_net = 0
    for item in items:
        pension = item.pension or 0
        nhf = item.nhf or 0
        tax = item.tax or 0
        loan = item.loan_deduction or 0
        adv = item.salary_advance or 0
        other = item.other_deductions or 0
        deductions_sum = pension + nhf + tax + loan + adv + other
        total_cost += float(item.gross_salary or 0)
        total_deductions += float(deductions_sum)
        total_net += float(item.net_salary or 0)
        rows.append(
            {
                "employee": item.employee.full_name,
                "employee_id": item.employee.employee_id,
                "gross_salary": str(item.gross_salary),
                "pension": str(pension),
                "nhf": str(nhf),
                "tax": str(tax),
                "loan_deduction": str(loan),
                "salary_advance": str(adv),
                "other_deductions": str(other),
                "net_salary": str(item.net_salary),
                "total_deductions": str(deductions_sum),
            }
        )
    return Response(
        {
            "items": rows,
            "total_cost": str(total_cost),
            "total_deductions": str(total_deductions),
            "total_net": str(total_net),
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payroll_loans_list_api(request):
    """
    Lightweight loans list for realtime polling.
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return Response({"detail": "No company profile"}, status=403)
    loans = (
        EmployeeLoan.objects.filter(company=company)
        .select_related("employee")
        .order_by("-created_at")[:50]
    )
    data = [
        {
            "id": loan.id,
            "employee": loan.employee.full_name,
            "employee_id": loan.employee.employee_id,
            "principal_amount": str(loan.principal_amount),
            "outstanding_balance": str(loan.outstanding_balance),
            "monthly_repayment": str(loan.monthly_repayment_amount),
            "status": loan.status,
            "status_display": loan.get_status_display(),
        }
        for loan in loans
    ]
    return Response({"results": data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payroll_advances_list_api(request):
    """
    Lightweight salary advances list for realtime polling.
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return Response({"detail": "No company profile"}, status=403)
    advances = (
        SalaryAdvance.objects.filter(company=company)
        .select_related("employee")
        .order_by("-created_at")[:50]
    )
    data = [
        {
            "id": advance.id,
            "employee": advance.employee.full_name,
            "amount": str(advance.amount),
            "status": advance.status,
            "status_display": advance.get_status_display(),
        }
        for advance in advances
    ]
    return Response({"results": data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payroll_run_employees_api(request):
    """
    Lightweight API for realtime employee list on the payroll run page.
    Returns active employees from HR & Staff that would be included in a payroll run.
    """
    from apps.hr_staff.models import Employee
    from apps.core.ownership import get_account_for_user
    
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return Response({"detail": "No company profile"}, status=403)
    
    account = get_account_for_user(request.user)
    if not account:
        return Response({"detail": "No account"}, status=403)
    
    employees = (
        Employee.objects.filter(
            account=account,
            company=company,
            status="active",
            is_deleted=False
        )
        .select_related("department")
        .order_by("last_name", "first_name")
    )
    
    data = [
        {
            "id": emp.id,
            "full_name": emp.full_name,
            "employee_id": emp.employee_id,
            "position": emp.position or "—",
            "department": emp.department.name if emp.department else "—",
            "monthly_salary": str(emp.monthly_salary or 0),
            "email": emp.email or "—",
            "phone": emp.phone or "—",
            "first_name": emp.first_name or "",
            "last_name": emp.last_name or "",
        }
        for emp in employees
    ]
    return Response({"results": data, "count": len(data)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payroll_structures_api(request):
    """
    API for realtime payroll structures list.
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return Response({"detail": "No company profile"}, status=403)
    
    structures = PayrollStructure.objects.filter(company=company, is_active=True).order_by("name")
    data = [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description or "",
        }
        for s in structures
    ]
    return Response({"results": data})


class PayrollFileViewSet(BaseTenantViewSet):
    queryset = PayrollFile.objects.select_related("category", "employee", "payroll_period", "created_by")
    serializer_class = PayrollFileSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        query = self.request.query_params.get("q", "")
        category_id = self.request.query_params.get("category", "")
        file_type = self.request.query_params.get("type", "")
        year = self.request.query_params.get("year", "")
        
        if query:
            qs = qs.filter(
                Q(title__icontains=query) |
                Q(original_filename__icontains=query) |
                Q(description__icontains=query) |
                Q(tags__icontains=query)
            )
        if category_id:
            qs = qs.filter(category_id=category_id)
        if file_type:
            qs = qs.filter(file_type=file_type)
        if year:
            qs = qs.filter(year=year)
        
        return qs


class FileCategoryViewSet(BaseTenantViewSet):
    queryset = FileCategory.objects.all()
    serializer_class = FileCategorySerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def files_search_api(request):
    """
    Search payroll files with advanced filtering.
    """
    from django.db.models import Q
    
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return Response({"error": "Company not found"}, status=404)

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

    return Response({"results": results, "count": files_qs.count()})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def files_summary_api(request):
    """
    Get summary of files for dashboard widgets.
    """
    company = get_company_profile_for_user(request.user, request)
    if not company:
        return Response({"error": "Company not found"}, status=404)

    total_files = PayrollFile.objects.filter(company=company).count()
    total_size = sum(f.file_size for f in PayrollFile.objects.filter(company=company))
    by_type = {}
    for ft, _ in PayrollFile.FILE_TYPE_CHOICES:
        count = PayrollFile.objects.filter(company=company, file_type=ft).count()
        if count > 0:
            by_type[ft] = count
    
    recent = PayrollFile.objects.filter(
        company=company, is_archived=False
    ).order_by("-created_at")[:5]
    
    return Response({
        "total_files": total_files,
        "total_size": total_size,
        "total_size_display": format_file_size(total_size) if total_size else "0 B",
        "by_type": by_type,
        "recent_files": [
            {
                "id": f.id,
                "title": f.title,
                "file_type": f.file_type,
                "created_at": f.created_at.isoformat(),
            }
            for f in recent
        ]
    })


def format_file_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


from .serializers import (
    TemplateListSerializer,
    TemplateDetailSerializer,
    TemplateCreateSerializer,
    EntryListSerializer,
    EntryDetailSerializer,
    EntryCreateSerializer,
    EntryUpdateSerializer,
)


class TemplateListAPIViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        templates = PayrollTemplate.objects.filter(company=company).order_by('-created_at')
        serializer = TemplateListSerializer(templates, many=True)
        return Response(serializer.data)

    def create(self, request):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        account = get_account_for_user(request.user)
        
        serializer = TemplateCreateSerializer(data=request.data)
        if serializer.is_valid():
            template = PayrollTemplate.objects.create(
                company=company,
                account=account,
                name=serializer.validated_data['name'],
                description=serializer.validated_data.get('description', ''),
                columns=serializer.validated_data.get('columns', []),
            )
            return Response(
                TemplateDetailSerializer(template).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TemplateDetailAPIViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, pk=None):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        try:
            template = PayrollTemplate.objects.get(pk=pk, company=company)
        except PayrollTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=404)
        
        serializer = TemplateDetailSerializer(template)
        return Response(serializer.data)

    def update(self, request, pk=None):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        try:
            template = PayrollTemplate.objects.get(pk=pk, company=company)
        except PayrollTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=404)
        
        serializer = TemplateCreateSerializer(data=request.data)
        if serializer.is_valid():
            template.name = serializer.validated_data.get('name', template.name)
            template.description = serializer.validated_data.get('description', template.description)
            if 'columns' in serializer.validated_data:
                template.columns = serializer.validated_data['columns']
            template.save()
            return Response(TemplateDetailSerializer(template).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        try:
            template = PayrollTemplate.objects.get(pk=pk, company=company)
        except PayrollTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=404)
        
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TemplateFieldsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        try:
            template = PayrollTemplate.objects.get(pk=pk, company=company)
        except PayrollTemplate.DoesNotExist:
            return Response({"error": "Template not found"}, status=404)
        
        fields = []
        for col in template.columns:
            field_def = {
                'key': col.get('key', ''),
                'label': col.get('label', col.get('key', '')),
                'type': col.get('type', 'text'),
                'required': col.get('required', False),
            }
            
            if col.get('type') in ('decimal', 'number', 'integer'):
                field_def['input_type'] = 'number'
                field_def['step'] = '0.01' if col.get('type') == 'decimal' else '1'
            else:
                field_def['input_type'] = 'text'
            
            fields.append(field_def)
        
        return Response({
            'template_id': template.id,
            'template_name': template.name,
            'fields': fields,
            'field_count': len(fields)
        })


class EntryListAPIViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        entries = PayrollEntry.objects.filter(
            company=company
        ).select_related('template', 'created_by').order_by('-created_at')
        
        template_id = request.query_params.get('template_id')
        if template_id:
            entries = entries.filter(template_id=template_id)
        
        period_month = request.query_params.get('period_month')
        period_year = request.query_params.get('period_year')
        if period_month:
            entries = entries.filter(period_month=period_month)
        if period_year:
            entries = entries.filter(period_year=period_year)
        
        status_filter = request.query_params.get('status')
        if status_filter:
            entries = entries.filter(status=status_filter)
        
        serializer = EntryListSerializer(entries, many=True)
        return Response(serializer.data)

    def create(self, request):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        account = get_account_for_user(request.user)
        
        serializer = EntryCreateSerializer(data=request.data)
        if serializer.is_valid():
            template = PayrollTemplate.objects.get(
                pk=serializer.validated_data['template_id'],
                company=company
            )
            
            rows = serializer.validated_data.get('rows', [])
            
            entry = PayrollEntry.objects.create(
                company=company,
                account=account,
                created_by=request.user,
                updated_by=request.user,
                template=template,
                title=serializer.validated_data['title'],
                period_month=serializer.validated_data.get('period_month'),
                period_year=serializer.validated_data.get('period_year'),
                data={
                    'rows': rows,
                    'columns': template.columns
                },
                row_count=len(rows),
                status=serializer.validated_data.get('status', 'draft'),
            )
            return Response(
                EntryDetailSerializer(entry).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class EntryDetailAPIViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, pk=None):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        try:
            entry = PayrollEntry.objects.get(pk=pk, company=company)
        except PayrollEntry.DoesNotExist:
            return Response({"error": "Entry not found"}, status=404)
        
        serializer = EntryDetailSerializer(entry)
        return Response(serializer.data)

    def update(self, request, pk=None):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        try:
            entry = PayrollEntry.objects.get(pk=pk, company=company)
        except PayrollEntry.DoesNotExist:
            return Response({"error": "Entry not found"}, status=404)
        
        serializer = EntryUpdateSerializer(data=request.data)
        if serializer.is_valid():
            if 'title' in serializer.validated_data:
                entry.title = serializer.validated_data['title']
            if 'period_month' in serializer.validated_data:
                entry.period_month = serializer.validated_data['period_month']
            if 'period_year' in serializer.validated_data:
                entry.period_year = serializer.validated_data['period_year']
            if 'rows' in serializer.validated_data:
                rows = serializer.validated_data['rows']
                entry.data = {
                    'rows': rows,
                    'columns': entry.template.columns
                }
                entry.row_count = len(rows)
            if 'status' in serializer.validated_data:
                entry.status = serializer.validated_data['status']
            
            entry.updated_by = request.user
            entry.save()
            return Response(EntryDetailSerializer(entry).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        try:
            entry = PayrollEntry.objects.get(pk=pk, company=company)
        except PayrollEntry.DoesNotExist:
            return Response({"error": "Entry not found"}, status=404)
        
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EntryRowsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        try:
            entry = PayrollEntry.objects.get(pk=pk, company=company)
        except PayrollEntry.DoesNotExist:
            return Response({"error": "Entry not found"}, status=404)
        
        return Response({
            'columns': entry.data.get('columns', []),
            'rows': entry.data.get('rows', [])
        })

    def post(self, request, pk):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        try:
            entry = PayrollEntry.objects.get(pk=pk, company=company)
        except PayrollEntry.DoesNotExist:
            return Response({"error": "Entry not found"}, status=404)
        
        new_rows = request.data.get('rows', [])
        if not isinstance(new_rows, list):
            return Response({"error": "rows must be a list"}, status=400)
        
        existing_rows = entry.data.get('rows', [])
        existing_rows.extend(new_rows)
        
        entry.data = {
            'rows': existing_rows,
            'columns': entry.template.columns
        }
        entry.row_count = len(existing_rows)
        entry.updated_by = request.user
        entry.save()
        
        return Response({
            'columns': entry.data.get('columns', []),
            'rows': entry.data.get('rows', []),
            'row_count': entry.row_count
        })

    def delete(self, request, pk):
        company = get_company_profile_for_user(request.user, request)
        if not company:
            return Response({"error": "Company not found"}, status=403)
        
        try:
            entry = PayrollEntry.objects.get(pk=pk, company=company)
        except PayrollEntry.DoesNotExist:
            return Response({"error": "Entry not found"}, status=404)
        
        row_index = request.data.get('row_index')
        if row_index is None:
            return Response({"error": "row_index is required"}, status=400)
        
        try:
            row_index = int(row_index)
        except ValueError:
            return Response({"error": "row_index must be an integer"}, status=400)
        
        rows = entry.data.get('rows', [])
        if row_index < 0 or row_index >= len(rows):
            return Response({"error": "row_index out of range"}, status=400)
        
        rows.pop(row_index)
        
        entry.data = {
            'rows': rows,
            'columns': entry.template.columns
        }
        entry.row_count = len(rows)
        entry.updated_by = request.user
        entry.save()
        
        return Response({
            'columns': entry.data.get('columns', []),
            'rows': entry.data.get('rows', []),
            'row_count': entry.row_count
        })

