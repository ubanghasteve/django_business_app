from io import BytesIO

from django.http import HttpResponse

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from .models import PayrollItem


def render_payslip_pdf(item: PayrollItem):
    """
    Generate a simple payslip PDF for a PayrollItem and return (filename, bytes_io).
    """
    employee = item.employee
    period = item.payroll_run.period
    company = item.company
    currency = getattr(company, "currency_symbol", "₦") if company else "₦"

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        "Title", parent=styles["Heading1"], fontSize=16, spaceAfter=12
    )
    story.append(Paragraph("Payslip", title_style))
    story.append(
        Paragraph(
            f"Company: {getattr(company, 'company_name', '') or 'N/A'}", styles["Normal"]
        )
    )
    story.append(
        Paragraph(
            f"Employee: {employee.full_name} ({employee.employee_id or '—'})",
            styles["Normal"],
        )
    )
    story.append(Paragraph(f"Period: {period}", styles["Normal"]))
    story.append(Spacer(1, 0.3 * inch))

    def _fmt(amount):
        return f"{currency}{float(amount):,.2f}"

    earnings = [
        ["Basic Salary", _fmt(item.basic_salary)],
        ["Allowances", _fmt(item.allowances)],
        ["Bonuses", _fmt(item.bonuses)],
        ["Overtime", _fmt(item.overtime)],
        ["Gross Salary", _fmt(item.gross_salary)],
    ]
    deductions = [
        ["Pension", _fmt(item.pension)],
        ["NHF", _fmt(item.nhf)],
        ["PAYE Tax", _fmt(item.tax)],
        ["Loan Deductions", _fmt(item.loan_deduction)],
        ["Salary Advance", _fmt(item.salary_advance)],
        ["Other Deductions", _fmt(item.other_deductions)],
    ]

    earnings_table = Table([["Earnings", "Amount"]] + earnings, colWidths=[3 * inch, 2 * inch])
    earnings_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]
        )
    )
    deductions_table = Table(
        [["Deductions", "Amount"]] + deductions, colWidths=[3 * inch, 2 * inch]
    )
    deductions_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]
        )
    )

    story.append(earnings_table)
    story.append(Spacer(1, 0.2 * inch))
    story.append(deductions_table)
    story.append(Spacer(1, 0.3 * inch))
    story.append(
        Paragraph(f"Net Salary: {_fmt(item.net_salary)}", styles["Heading2"])
    )

    doc.build(story)
    buffer.seek(0)
    filename = f"payslip_{employee.employee_id or employee.id}_{period.year}_{period.month}.pdf"
    return filename, buffer


def payroll_summary(company, period):
    """
    Simple totals for summary view.
    """
    items = PayrollItem.objects.filter(
        company=company, payroll_run__period=period
    ).select_related("employee")
    total_cost = sum((i.gross_salary for i in items), start=0)
    total_deductions = sum(
        (i.pension + i.nhf + i.tax + i.loan_deduction + i.salary_advance + i.other_deductions)
        for i in items
    )
    total_net = sum((i.net_salary for i in items), start=0)
    return {
        "items": items,
        "total_cost": total_cost,
        "total_deductions": total_deductions,
        "total_net": total_net,
    }


def payslip_http_response(item: PayrollItem):
    """
    Convenience wrapper to return an HttpResponse with payslip PDF.
    """
    filename, buf = render_payslip_pdf(item)
    response = HttpResponse(buf.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

