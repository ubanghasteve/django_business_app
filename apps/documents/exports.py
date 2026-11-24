from io import BytesIO
import json

from django.http import HttpResponse


def export_tables_to_excel(document):
    """
    Export the document's tables (cleaned if present, else raw) to an Excel file.
    Returns a Django HttpResponse with the xlsx content.
    """
    try:
        import pandas as pd
    except ImportError:
        return HttpResponse('pandas not installed', status=500)

    tables = []
    if getattr(document, 'cleaned_tables_json', ''):
        try:
            tables = json.loads(document.cleaned_tables_json) or []
        except (json.JSONDecodeError, TypeError):
            tables = []
    if not tables and getattr(document, 'extracted_tables_json', ''):
        try:
            tables = json.loads(document.extracted_tables_json) or []
        except (json.JSONDecodeError, TypeError):
            tables = []

    if not tables:
        return HttpResponse('No tables to export', status=400)

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        for idx, tbl in enumerate(tables):
            df = pd.DataFrame(tbl)
            sheet_name = f'Table{idx + 1}'
            df.to_excel(writer, sheet_name=sheet_name, header=False, index=False)
    buffer.seek(0)
    filename = (document.file.name or f'document_{document.pk}').split('/')[-1]
    xlsx_name = filename.rsplit('.', 1)[0] + '_tables.xlsx'
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{xlsx_name}"'
    return response

