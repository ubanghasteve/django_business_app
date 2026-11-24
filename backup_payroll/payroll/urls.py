from django.urls import path

from . import views

app_name = "payroll"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("runs/", views.payroll_list, name="payroll_list"),
    path("run/", views.payroll_run_view, name="payroll_run"),
    path("runs/<int:run_id>/approve/", views.approve_payroll_run, name="approve_run"),
    path("runs/<int:run_id>/mark-paid/", views.mark_run_paid, name="mark_run_paid"),
    path("items/<int:item_id>/", views.employee_payroll_detail, name="employee_payroll_detail"),
    path("items/<int:item_id>/payslip/", views.payslip_view, name="payslip"),
    path("reports/summary/<int:period_id>/", views.payroll_summary_view, name="payroll_summary"),
    path("reports/paye/<int:period_id>/", views.paye_report_view, name="paye_report"),
    path("reports/nhf/<int:period_id>/", views.nhf_report_view, name="nhf_report"),
    path("reports/pension/<int:period_id>/", views.pension_report_view, name="pension_report"),
    path("reports/export/<int:period_id>/<str:export_type>/", views.export_excel_view, name="export_excel"),
    
    path("profiles/", views.employee_payroll_profiles_list, name="employee_profiles_list"),
    path("profiles/<int:profile_id>/edit/", views.employee_payroll_profile_edit, name="employee_profile_edit"),
    
    path("loans/", views.loans_list, name="loans_list"),
    path("loans/create/", views.loan_create, name="loan_create"),
    path("loans/<int:loan_id>/edit/", views.loan_edit, name="loan_edit"),
    
    path("advances/", views.salary_advances_list, name="salary_advances_list"),
    path("advances/create/", views.salary_advance_create, name="salary_advance_create"),
    path("advances/<int:advance_id>/approve/", views.salary_advance_approve, name="salary_advance_approve"),
    
    path("bonuses/", views.bonuses_list, name="bonuses_list"),
    path("bonuses/rules/create/", views.bonus_rule_create, name="bonus_rule_create"),
    path("bonuses/rules/<int:rule_id>/edit/", views.bonus_rule_edit, name="bonus_rule_edit"),
    
    path("structures/", views.payroll_structures_list, name="structures_list"),
    path("structures/create/", views.payroll_structure_create, name="structure_create"),

    path("files/", views.files_list, name="files_list"),
    path("files/upload/", views.files_upload, name="files_upload"),
    path("files/search/", views.files_search, name="files_search"),
    path("files/categories/", views.file_categories_list, name="file_categories_list"),
    path("files/categories/create/", views.file_category_create, name="file_category_create"),
    path("files/categories/<int:category_id>/edit/", views.file_category_edit, name="file_category_edit"),
    path("files/<int:file_id>/", views.file_detail, name="file_detail"),
    path("files/<int:file_id>/edit/", views.file_edit, name="file_edit"),
    path("files/<int:file_id>/download/", views.file_download, name="file_download"),
    path("files/<int:file_id>/preview/", views.file_preview, name="file_preview"),
    path("files/<int:file_id>/delete/", views.file_delete, name="file_delete"),
    path("files/<int:file_id>/toggle-star/", views.file_toggle_star, name="file_toggle_star"),
    path("files/<int:file_id>/toggle-archive/", views.file_toggle_archive, name="file_toggle_archive"),
    path("files/<int:file_id>/extract/", views.excel_extract, name="excel_extract"),
    path("files/<int:file_id>/parse/", views.excel_parse_and_save, name="excel_parse_save"),
    
    path("records/", views.excel_records_list, name="excel_records_list"),
    path("records/<int:record_id>/link/", views.excel_records_link_employee, name="excel_records_link"),
    path("records/<int:record_id>/verify/", views.excel_records_verify, name="excel_records_verify"),
    
    path("templates/", views.template_list, name="template_list"),
    path("templates/create/<int:file_id>/", views.template_create_from_file, name="template_create"),
    path("templates/<int:template_id>/", views.template_detail, name="template_detail"),
    path("templates/<int:template_id>/fill/", views.template_fill_form, name="template_fill"),
    path("templates/<int:template_id>/add-row/", views.template_add_row, name="template_add_row"),
    path("templates/<int:template_id>/continue/<int:entry_id>/", views.template_entry_continue, name="template_entry_continue"),
    
    path("entries/", views.entry_list, name="entry_list"),
    path("entries/export-all/", views.entries_export_all, name="entries_export_all"),
    path("entries/<int:entry_id>/", views.entry_detail, name="entry_detail"),
    path("entries/<int:entry_id>/export/", views.entry_export, name="entry_export"),
]

