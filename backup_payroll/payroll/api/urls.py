from rest_framework.routers import DefaultRouter
from django.urls import path, include

from .views import (
    PayrollStructureViewSet,
    EmployeePayrollProfileViewSet,
    PayrollPeriodViewSet,
    PayrollRunViewSet,
    PayrollItemViewSet,
    PayslipViewSet,
    BonusRuleViewSet,
    EmployeeBonusViewSet,
    EmployeeLoanViewSet,
    LoanRepaymentViewSet,
    SalaryAdvanceViewSet,
    PayrollFileViewSet,
    FileCategoryViewSet,
    payroll_dashboard_metrics_api,
    payroll_runs_list_api,
    payroll_period_items_api,
    payroll_loans_list_api,
    payroll_advances_list_api,
    payroll_run_employees_api,
    payroll_structures_api,
    files_search_api,
    files_summary_api,
    TemplateListAPIViewSet,
    TemplateDetailAPIViewSet,
    TemplateFieldsAPIView,
    EntryListAPIViewSet,
    EntryDetailAPIViewSet,
    EntryRowsAPIView,
)


router = DefaultRouter()
router.register(r"structures", PayrollStructureViewSet, basename="payroll-structures")
router.register(r"employees", EmployeePayrollProfileViewSet, basename="payroll-employees")
router.register(r"periods", PayrollPeriodViewSet, basename="payroll-periods")
router.register(r"run", PayrollRunViewSet, basename="payroll-run")
router.register(r"items", PayrollItemViewSet, basename="payroll-items")
router.register(r"payslips", PayslipViewSet, basename="payroll-payslips")
router.register(r"bonuses", BonusRuleViewSet, basename="payroll-bonuses")
router.register(r"employee-bonuses", EmployeeBonusViewSet, basename="payroll-employee-bonuses")
router.register(r"loans", EmployeeLoanViewSet, basename="payroll-loans")
router.register(r"loan-repayments", LoanRepaymentViewSet, basename="payroll-loan-repayments")
router.register(r"salary-advances", SalaryAdvanceViewSet, basename="payroll-salary-advances")
router.register(r"files", PayrollFileViewSet, basename="payroll-files")
router.register(r"file-categories", FileCategoryViewSet, basename="payroll-file-categories")
router.register(r"templates", TemplateListAPIViewSet, basename="payroll-templates")
router.register(r"entries", EntryListAPIViewSet, basename="payroll-entries")


urlpatterns = [
    path("dashboard-metrics/", payroll_dashboard_metrics_api, name="payroll-dashboard-metrics"),
    path("runs-list/", payroll_runs_list_api, name="payroll-runs-list"),
    path("period-items/<int:period_id>/", payroll_period_items_api, name="payroll-period-items"),
    path("loans-list/", payroll_loans_list_api, name="payroll-loans-list"),
    path("advances-list/", payroll_advances_list_api, name="payroll-advances-list"),
    path("run-employees/", payroll_run_employees_api, name="payroll-run-employees"),
    path("structures/", payroll_structures_api, name="payroll-structures"),
    path("files/search/", files_search_api, name="payroll-files-search"),
    path("files/summary/", files_summary_api, name="payroll-files-summary"),
    path("templates/<int:pk>/fields/", TemplateFieldsAPIView.as_view(), name="payroll-template-fields"),
    path("entries/<int:pk>/rows/", EntryRowsAPIView.as_view(), name="payroll-entry-rows"),
    path("", include(router.urls)),
]

