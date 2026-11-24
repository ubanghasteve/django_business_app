# -*- coding: utf-8 -*-
"""
Extraction app - OCR and PDF table extraction.
- Layout-aware: single-pass PDF (text + tables + layout_lines), image OCR with PSM 6.
- Enhanced with advanced OCR engines: EasyOCR, RapidOCR, PaddleOCR
- Enhanced with table extraction: Tabula-py, Camelot-py
- Enhanced with layout analysis: doclayout-yolo
"""
import json
import os

from .utils import is_pdf_path, is_image_path
from .layout import pdf_extract_text_and_tables_single_pass, image_extract_with_layout, _infer_tables_from_text

try:
    from .smart_backends import run_smart_extraction
except ImportError:
    run_smart_extraction = None
try:
    from .pdf_ocr import pdf_ocr_fallback
except ImportError:
    pdf_ocr_fallback = None


def extract_with_advanced_ocr(document_file):
    """
    Extract text using advanced OCR engines (PaddleOCR, EasyOCR, RapidOCR).
    This is used when USE_ADVANCED_OCR=1 is set in environment.
    
    Returns: dict with text, tables, layout_lines, engine, error.
    """
    if not os.environ.get('USE_ADVANCED_OCR'):
        return None
    
    try:
        from .advanced_ocr import AdvancedOCR
    except ImportError:
        return None
    
    name = getattr(document_file, 'name', '') or ''
    
    try:
        if is_image_path(name):
            result = AdvancedOCR.extract_from_image(document_file)
            if result:
                return {
                    'text': result.text or '',
                    'tables': result.tables or [],
                    'layout_lines': result.layout_lines or [],
                    'pages': [],
                    'engine': result.engine,
                    'error': result.error or '',
                }
        elif is_pdf_path(name):
            result = AdvancedOCR.extract_from_pdf(document_file)
            if result:
                return {
                    'text': result.text or '',
                    'tables': result.tables or [],
                    'layout_lines': result.layout_lines or [],
                    'pages': [],
                    'engine': result.engine,
                    'error': result.error or '',
                }
    except Exception as e:
        return {'text': '', 'tables': [], 'layout_lines': [], 'pages': [], 'engine': 'advanced-ocr', 'error': str(e)}
    
    return None


def extract_tables_with_advanced_engine(pdf_path_or_file):
    """
    Extract tables using advanced table extraction engines (Tabula, Camelot, PDFPlumber).
    This is used when USE_ADVANCED_TABLE_EXTRACTION=1 is set in environment.
    
    Returns: dict with success, tables, raw_tables, engine, error.
    """
    if not os.environ.get('USE_ADVANCED_TABLE_EXTRACTION'):
        return None
    
    try:
        from .table_extractor import TableExtractor
    except ImportError:
        return None
    
    try:
        result = TableExtractor.extract_all_tables(pdf_path_or_file)
        if result:
            return {
                'success': len(result.tables) > 0,
                'tables': result.tables or [],
                'raw_tables': [{'page': 1, 'rows': t} for t in (result.tables or [])],
                'engine': result.engine,
                'error': result.error or '',
            }
    except Exception as e:
        return {'success': False, 'tables': [], 'raw_tables': [], 'engine': 'advanced-table', 'error': str(e)}
    
    return None


def analyze_layout_advanced(document_file):
    """
    Analyze document layout using doclayout-yolo AI model.
    This is used when USE_LAYOUT_ANALYSIS=1 is set in environment.
    
    Returns: dict with elements, pages, text, tables, layout_lines, error.
    """
    if not os.environ.get('USE_LAYOUT_ANALYSIS'):
        return None
    
    try:
        from .layout_analyzer import LayoutAnalyzer
    except ImportError:
        return None
    
    name = getattr(document_file, 'name', '') or ''
    
    try:
        if is_image_path(name):
            result = LayoutAnalyzer.analyze_image(document_file)
            if result:
                return {
                    'elements': [e.to_dict() for e in result.elements] if result.elements else [],
                    'pages': result.pages or [],
                    'text': result.full_text or '',
                    'tables': result.tables or [],
                    'layout_lines': result.layout_lines or [],
                    'engine': result.engine,
                    'error': result.error or '',
                }
        elif is_pdf_path(name):
            result = LayoutAnalyzer.analyze_pdf(document_file)
            if result:
                return {
                    'elements': [e.to_dict() for e in result.elements] if result.elements else [],
                    'pages': result.pages or [],
                    'text': result.full_text or '',
                    'tables': result.tables or [],
                    'layout_lines': result.layout_lines or [],
                    'engine': result.engine,
                    'error': result.error or '',
                }
    except Exception as e:
        return {'elements': [], 'pages': [], 'text': '', 'tables': [], 'layout_lines': [], 'engine': 'layout-analyzer', 'error': str(e)}
    
    return None


def extract_text_from_image(image_path_or_file):
    """
    Extract text from an image using Tesseract OCR.
    image_path_or_file: path (str) or file-like object.
    Returns: dict with keys: success (bool), text (str), error (str if failed).
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return {'success': False, 'text': '', 'error': 'pytesseract or Pillow not installed'}

    # Windows: use default install path if Tesseract is not on PATH
    import sys
    if sys.platform == 'win32':
        import os
        default_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
        if os.path.isfile(default_path):
            pytesseract.pytesseract.tesseract_cmd = default_path

    try:
        if hasattr(image_path_or_file, 'read'):
            image_path_or_file.seek(0)
            img = Image.open(image_path_or_file)
            img.load()
        else:
            img = Image.open(image_path_or_file)
        text = pytesseract.image_to_string(img)
        return {'success': True, 'text': (text or '').strip(), 'error': ''}
    except Exception as e:
        return {'success': False, 'text': '', 'error': str(e)}


def extract_tables_from_pdf(pdf_path_or_file):
    """
    Extract tables from a PDF using pdfplumber.
    pdf_path_or_file: path (str) or file-like object.
    Returns: dict with success (bool), tables (list of list of lists), raw_tables (list of dicts), error (str).
    Output format is JSON-structured: list of tables, each table = list of rows, each row = list of cell strings.
    """
    try:
        import pdfplumber
    except ImportError:
        return {
            'success': False,
            'tables': [],
            'raw_tables': [],
            'error': 'pdfplumber not installed',
        }

    try:
        if hasattr(pdf_path_or_file, 'read'):
            pdf_path_or_file.seek(0)
            pdf = pdfplumber.open(pdf_path_or_file)
        else:
            pdf = pdfplumber.open(pdf_path_or_file)
        tables = []
        raw_tables = []
        with pdf as p:
            for i, page in enumerate(p.pages):
                page_tables = page.extract_tables()
                for t in page_tables or []:
                    # t is list of rows, each row is list of cells (can be None)
                    rows = [[(str(cell).strip() if cell is not None else '') for cell in row] for row in t]
                    tables.append(rows)
                    raw_tables.append({'page': i + 1, 'rows': rows})
        pdf.close()
        return {'success': True, 'tables': tables, 'raw_tables': raw_tables, 'error': ''}
    except Exception as e:
        return {'success': False, 'tables': [], 'raw_tables': [], 'error': str(e)}


def extract_text_from_pdf(pdf_path_or_file):
    """
    Extract plain text from PDF (pdfplumber). Used when no tables or in addition to tables.
    Returns: dict with success, text, error.
    """
    try:
        import pdfplumber
    except ImportError:
        return {'success': False, 'text': '', 'error': 'pdfplumber not installed'}

    try:
        if hasattr(pdf_path_or_file, 'read'):
            pdf_path_or_file.seek(0)
            pdf = pdfplumber.open(pdf_path_or_file)
        else:
            pdf = pdfplumber.open(pdf_path_or_file)
        parts = []
        with pdf as p:
            for page in p.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
        pdf.close()
        return {'success': True, 'text': '\n'.join(parts), 'error': ''}
    except Exception as e:
        return {'success': False, 'text': '', 'error': str(e)}


def run_extraction(document_file):
    """
    Run layout-aware extraction: one pass when possible, preserve line order.
    When USE_SMART_EXTRACTION is set and Google Document AI or Azure Document
    Intelligence is configured, uses cloud API first (handwriting + structure);
    otherwise uses local OCR/PDF extraction.
    
    Enhanced with:
    - USE_ADVANCED_OCR: Uses PaddleOCR/EasyOCR/RapidOCR for better OCR
    - USE_ADVANCED_TABLE_EXTRACTION: Uses Tabula/Camelot for better tables
    - USE_LAYOUT_ANALYSIS: Uses doclayout-yolo for layout understanding
    
    document_file: Django FileField value (has .name, .path or .read()).
    Returns: dict with text (str), tables (list), layout_lines (list), raw_json (str), error (str).
    """
    name = getattr(document_file, 'name', '') or ''
    result = {'text': '', 'tables': [], 'layout_lines': [], 'pages': [], 'raw_json': '{}', 'error': ''}
    lower_name = name.lower()

    # Try advanced layout analysis first (doclayout-yolo)
    if is_pdf_path(name) or is_image_path(name):
        layout_result = analyze_layout_advanced(document_file)
        if layout_result and (layout_result.get('text') or layout_result.get('tables')):
            result['text'] = layout_result.get('text', '')
            result['tables'] = layout_result.get('tables', []) or []
            result['layout_lines'] = layout_result.get('layout_lines', []) or []
            result['pages'] = layout_result.get('pages', []) or []
            result['error'] = layout_result.get('error', '')
            result['raw_json'] = json.dumps({
                'type': 'layout-analysis',
                'engine': layout_result.get('engine', 'doclayout-yolo'),
                'text': result['text'],
                'tables': result['tables'],
                'layout_lines': result['layout_lines'],
                'elements': layout_result.get('elements', []),
            })
            return result

    if run_smart_extraction and (is_pdf_path(name) or is_image_path(name)):
        smart = run_smart_extraction(document_file)
        if smart and (smart.get('text') or smart.get('tables')):
            result['text'] = smart.get('text', '')
            result['tables'] = smart.get('tables', []) or []
            result['layout_lines'] = smart.get('layout_lines', []) or []
            result['pages'] = smart.get('pages', []) or []
            result['error'] = smart.get('error', '')

            # For PDFs, if the smart backend did not return any tables at all,
            # complement it with local pdfplumber+heuristics tables to better
            # preserve the original grid layout (rows/columns).
            if is_pdf_path(name):
                if not result['tables']:
                    if hasattr(document_file, 'seek'):
                        document_file.seek(0)
                    local = pdf_extract_text_and_tables_single_pass(document_file)
                    local_tables = local.get('tables') or []
                    if local_tables:
                        result['tables'] = local_tables

            result['raw_json'] = json.dumps({
                'type': 'smart',
                'text': result['text'],
                'tables': result['tables'],
                'layout_lines': result['layout_lines'],
                'pages': result['pages'],
            })
            return result
        if hasattr(document_file, 'seek'):
            document_file.seek(0)

    # ---- IMAGE (PNG/JPEG/TIFF) ----
    if is_image_path(name):
        out = image_extract_with_layout(document_file)
        result['text'] = out.get('text', '')
        result['layout_lines'] = out.get('layout_lines', [])
        result['tables'] = out.get('tables', []) or []  # Enhanced: include inferred tables
        result['error'] = out.get('error', '')
        
        # Try advanced OCR for better results
        if not result['text'] or len(result['text'].strip()) < 100:
            advanced_result = extract_with_advanced_ocr(document_file)
            if advanced_result and advanced_result.get('text'):
                result['text'] = advanced_result.get('text', '')
                result['layout_lines'] = advanced_result.get('layout_lines', []) or [
                    ln.strip() for ln in result['text'].split('\n') if ln.strip()
                ]
                if advanced_result.get('tables'):
                    result['tables'] = advanced_result.get('tables')
                result['error'] = ''
        
        if result['error'] and not result['text']:
            # Fallback to basic OCR
            fallback = extract_text_from_image(document_file)
            if fallback.get('text'):
                result['text'] = fallback['text']
                result['layout_lines'] = [ln.strip() for ln in result['text'].split('\n') if ln.strip()]
                result['error'] = ''
        
        # If still no tables, try to infer from layout lines
        if not result['tables'] and result['layout_lines']:
            inferred = _infer_tables_from_text(result['text'])
            if inferred:
                result['tables'] = inferred
        
        result['raw_json'] = json.dumps({'type': 'ocr', 'text': result['text'], 'layout_lines': result['layout_lines'], 'tables': result['tables']})
        return result

    # ---- PDF ----
    if is_pdf_path(name):
        out = pdf_extract_text_and_tables_single_pass(document_file)
        result['text'] = out.get('text', '')
        result['tables'] = out.get('tables', [])
        result['layout_lines'] = out.get('layout_lines', [])
        result['pages'] = out.get('pages', []) or []
        result['error'] = out.get('error', '')
        if result['error'] and (not result['text'] and not result['tables']):
            # Fallback to legacy two-pass
            if hasattr(document_file, 'seek'):
                document_file.seek(0)
            text_out = extract_text_from_pdf(document_file)
            result['text'] = text_out.get('text', '')
            if hasattr(document_file, 'seek'):
                document_file.seek(0)
            table_out = extract_tables_from_pdf(document_file)
            result['tables'] = table_out.get('tables', [])
            result['layout_lines'] = [ln.strip() for ln in result['text'].split('\n') if ln.strip()]
            result['pages'] = []
            result['error'] = text_out.get('error', '') or table_out.get('error', '')
        # Try advanced OCR for scanned/poor quality PDFs
        if len((result['text'] or '').strip()) < 200:
            advanced_result = extract_with_advanced_ocr(document_file)
            if advanced_result and advanced_result.get('text'):
                result['text'] = advanced_result.get('text', '')
                result['layout_lines'] = advanced_result.get('layout_lines', []) or [
                    ln.strip() for ln in result['text'].split('\n') if ln.strip()
                ]
                if advanced_result.get('tables'):
                    result['tables'] = advanced_result.get('tables')
                result['error'] = ''
        
        # Try advanced table extraction for PDFs
        if not result['tables']:
            advanced_tables = extract_tables_with_advanced_engine(document_file)
            if advanced_tables and advanced_tables.get('tables'):
                result['tables'] = advanced_tables.get('tables')
        
        # Scanned PDF: if text is empty or very short, run OCR on rendered pages
        if pdf_ocr_fallback and len((result['text'] or '').strip()) < 200:
            if hasattr(document_file, 'seek'):
                document_file.seek(0)
            ocr_out = pdf_ocr_fallback(document_file, min_text_length=150)
            if ocr_out.get('text'):
                result['text'] = (result['text'] or '') + '\n' + ocr_out['text']
                result['text'] = result['text'].strip()
                result['layout_lines'] = ocr_out.get('layout_lines', []) or [
                    ln.strip() for ln in result['text'].split('\n') if ln.strip()
                ]
                # Try to infer tables from OCR text when the PDF had no table
                # structure (image-only bank statements, etc.).
                if not result['tables']:
                    inferred_tables = _infer_tables_from_text(ocr_out.get('text', ''))
                    if inferred_tables:
                        result['tables'] = inferred_tables
                if result['error'] and 'No structured data' not in result['error']:
                    result['error'] = ''
        result['raw_json'] = json.dumps({
            'type': 'pdf',
            'text': result['text'],
            'tables': result['tables'],
            'layout_lines': result['layout_lines'],
        })
        return result

    # ---- Word documents (DOC / DOCX) ----
    if lower_name.endswith(('.docx', '.doc')):
        try:
            import docx  # python-docx
        except ImportError:
            result['error'] = 'python-docx not installed (pip install python-docx)'
            return result
        try:
            if hasattr(document_file, 'seek'):
                document_file.seek(0)
            doc_obj = docx.Document(document_file)
        except Exception as e:
            result['error'] = f'Word extraction failed: {e}'
            return result

        paragraphs = []
        layout_lines = []
        text_lines = []
        for p in getattr(doc_obj, 'paragraphs', []):
            text_line = (getattr(p, 'text', '') or '').strip()
            if not text_line:
                continue

            # Detect heading-style paragraphs (Heading 1, Heading 2, etc.) so that
            # the downstream structure analyzer can more accurately mark them as
            # section headings by seeing blank-line separation.
            style = getattr(p, 'style', None)
            style_name = getattr(style, 'name', '') or ''
            is_heading_style = style_name.lower().startswith('heading')

            if is_heading_style:
                # Ensure a blank line before and after heading in the raw text.
                if text_lines and text_lines[-1] != '':
                    text_lines.append('')
                text_lines.append(text_line)
                text_lines.append('')
            else:
                text_lines.append(text_line)

            paragraphs.append(text_line)
            layout_lines.append(text_line)

        tables = []
        for tbl in getattr(doc_obj, 'tables', []):
            tbl_rows = []
            for row in getattr(tbl, 'rows', []):
                cells = []
                for cell in getattr(row, 'cells', []):
                    cells.append((getattr(cell, 'text', '') or '').strip())
                if any(cells):
                    tbl_rows.append(cells)
            if tbl_rows:
                tables.append(tbl_rows)

        # Use text_lines (with extra spacing around heading-style paragraphs)
        # so the structure analyzer can better infer section boundaries.
        result['text'] = '\n'.join(text_lines).strip()
        result['layout_lines'] = layout_lines
        result['tables'] = tables
        result['raw_json'] = json.dumps({
            'type': 'word',
            'paragraphs': len(paragraphs),
            'tables': len(tables),
        })
        if not result['text'] and not tables:
            result['error'] = 'No readable content found in Word document'
        return result

    # ---- Excel (XLS/XLSX/XLSM) ----
    if lower_name.endswith(('.xls', '.xlsx', '.xlsm')):
        try:
            import pandas as pd
        except ImportError:
            result['error'] = 'pandas not installed (pip install pandas openpyxl)'
            return result
        # Read all sheets; build tables and text so AI analyzers can reuse them.
        try:
            if hasattr(document_file, 'seek'):
                document_file.seek(0)
            # engine="openpyxl" works for modern Excel formats
            excel_data = pd.read_excel(document_file, sheet_name=None, header=None, engine='openpyxl')
        except Exception as e:
            result['error'] = f'Excel extraction failed: {e}'
            return result

        tables = []
        layout_lines = []
        text_parts = []
        for sheet_name, df in (excel_data or {}).items():
            if df is None:
                continue
            # Replace NaN with empty string for consistency with PDF tables.
            clean_df = df.fillna('')
            sheet_rows = []
            for row in clean_df.itertuples(index=False):
                cells = [str(cell).strip() for cell in row]
                # Skip completely empty rows
                if not any(cells):
                    continue
                sheet_rows.append(cells)
                layout_lines.append(' '.join(c for c in cells if c))
            if sheet_rows:
                tables.append(sheet_rows)
                text_parts.append(f'### Sheet: {sheet_name} ###')
                for r in sheet_rows:
                    text_parts.append(' | '.join(r))

        result['tables'] = tables
        result['layout_lines'] = layout_lines
        result['text'] = '\n'.join(text_parts).strip()
        result['raw_json'] = json.dumps({
            'type': 'excel',
            'sheets': len(tables),
        })
        if not tables and not result['text']:
            result['error'] = 'No readable cells found in Excel file'
        return result

    # ---- Unsupported type ----
    result['error'] = 'Unsupported file type for extraction'
    return result
