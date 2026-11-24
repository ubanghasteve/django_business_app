from datetime import date
from decimal import Decimal

from django.db.models import Sum, Count

from .models import PayrollRun, PayrollItem


def get_payroll_dashboard_metrics(company, year: int = None):
    """
    Aggregate metrics for payroll analytics dashboard.
    """
    today = date.today()
    year = year or today.year
    runs = PayrollRun.objects.filter(company=company, period__year=year)
    items = PayrollItem.objects.filter(company=company, payroll_run__period__year=year)

    total_cost = runs.aggregate(s=Sum("total_gross"))["s"] or Decimal("0.00")
    total_tax = runs.aggregate(s=Sum("total_tax"))["s"] or Decimal("0.00")
    total_pension = runs.aggregate(s=Sum("total_pension"))["s"] or Decimal("0.00")
    total_nhf = runs.aggregate(s=Sum("total_nhf"))["s"] or Decimal("0.00")
    total_net = runs.aggregate(s=Sum("total_net"))["s"] or Decimal("0.00")
    total_employees_paid = items.values("employee_id").distinct().count()

    monthly_trend = (
        runs.values("period__month")
        .annotate(total=Sum("total_gross"))
        .order_by("period__month")
    )

    dept_cost = (
        items.values("employee__department__name")
        .annotate(total=Sum("gross_salary"), count=Count("employee_id"))
        .order_by("employee__department__name")
    )

    salary_distribution = (
        items.values("basic_salary")
        .annotate(count=Count("id"))
        .order_by("basic_salary")
    )

    return {
        "total_payroll_cost": total_cost,
        "total_tax": total_tax,
        "total_pension": total_pension,
        "total_nhf": total_nhf,
        "total_net": total_net,
        "total_employees_paid": total_employees_paid,
        "monthly_trend": list(monthly_trend),
        "department_cost": list(dept_cost),
        "salary_distribution": list(salary_distribution),
    }

