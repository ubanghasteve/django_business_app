# -*- coding: utf-8 -*-
"""
Smart extraction backends and orchestrator.

This module normalizes multiple third‑party engines into a single internal
shape so the rest of the app only ever sees:

    text: str
    tables: list[list[list[str]]]
    layout_lines: list[str]

Backends (all optional, enabled by env vars):
- Amazon Textract (primary when USE_AWS_TEXTRACT=1)
- docTR deep‑learning OCR (USE_DOCTR=1)
- Google Document AI (if configured)
- Azure Document Intelligence (if configured)
- PaddleOCR (USE_PADDLEOCR=1)
- EasyOCR (USE_EASYOCR=1)
- RapidOCR (USE_RAPIDOCR=1)
- doclayout-yolo (USE_DOCLAYOUT=1)
- Tabula/Camelot table extraction (USE_TABLE_EXTRACTION=1)

The public entry point is run_smart_extraction(), which the main
run_extraction() function in services.py calls before falling back to the
local pdfplumber + Tesseract pipeline.
"""
import os
import io

_DOCTR_MODEL = None  # Loaded lazily when/if docTR is used.


def _read_file_to_bytes(document_file):
    """Return (bytes, mime_type, name) for document_file (Django File or path)."""
    if hasattr(document_file, 'read'):
        document_file.seek(0)
        raw = document_file.read()
        if isinstance(raw, str):
            raw = raw.encode('utf-8')
    else:
        with open(document_file, 'rb') as f:
            raw = f.read()
    name = getattr(document_file, 'name', '') or str(document_file)
    lower = name.lower()
    if lower.endswith('.pdf'):
        return raw, 'application/pdf', name
    if lower.endswith(('.png', '.jpg', '.jpeg')):
        return raw, 'image/jpeg', name
    if lower.endswith(('.tiff', '.tif')):
        return raw, 'image/tiff', name
    return raw, 'application/octet-stream', name


def _aws_textract_extract(document_bytes, mime_type, filename):
    """
    Call Amazon Textract (AnalyzeDocument) and normalize to text/tables/layout_lines.

    Enabled when USE_AWS_TEXTRACT=1 and boto3 is installed. For cost control, an
    optional TEXTRACT_MAX_MB env var (float, default 5) can be set to skip very
    large files and let the local pipeline handle them instead.
    """
    if not os.environ.get('USE_AWS_TEXTRACT'):
        return None
    try:
        import boto3
    except ImportError:
        return None

    max_mb = float(os.environ.get('TEXTRACT_MAX_MB', '5'))
    if max_mb > 0 and len(document_bytes or b'') > max_mb * 1024 * 1024:
        # Too large for cheap synchronous Textract; let caller fall back.
        return None

    region = (
        os.environ.get('AWS_TEXTRACT_REGION')
        or os.environ.get('AWS_REGION')
        or os.environ.get('AWS_DEFAULT_REGION')
    )
    client_kwargs = {}
    if region:
        client_kwargs['region_name'] = region
    try:
        client = boto3.client('textract', **client_kwargs)
    except Exception:
        return None

    try:
        response = client.analyze_document(
            Document={'Bytes': document_bytes},
            FeatureTypes=['TABLES', 'FORMS'],
        )
    except Exception as e:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': str(e)}

    blocks = response.get('Blocks') or []
    if not blocks:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': 'No blocks returned from Textract'}

    block_map = {b.get('Id'): b for b in blocks if b.get('Id')}

    # ---- Lines / layout_lines ----
    line_blocks = [b for b in blocks if b.get('BlockType') == 'LINE' and b.get('Text')]

    def _line_sort_key(b):
        geom = b.get('Geometry') or {}
        bbox = geom.get('BoundingBox') or {}
        return (b.get('Page', 1), bbox.get('Top', 0.0), bbox.get('Left', 0.0))

    line_blocks.sort(key=_line_sort_key)
    layout_lines = [b.get('Text', '').strip() for b in line_blocks if b.get('Text')]
    text = '\n'.join(layout_lines).strip()

    # ---- Tables ----
    tables = []
    for block in blocks:
        if block.get('BlockType') != 'TABLE':
            continue
        rels = block.get('Relationships') or []
        cell_ids = []
        for rel in rels:
            if rel.get('Type') == 'CHILD':
                cell_ids.extend(rel.get('Ids') or [])
        cell_blocks = [
            block_map[cid]
            for cid in cell_ids
            if block_map.get(cid) and block_map[cid].get('BlockType') == 'CELL'
        ]
        if not cell_blocks:
            continue
        max_row = 0
        max_col = 0
        cell_map = {}
        for cell in cell_blocks:
            r = cell.get('RowIndex', 1)
            c = cell.get('ColumnIndex', 1)
            max_row = max(max_row, r)
            max_col = max(max_col, c)
            parts = []
            for rel in cell.get('Relationships') or []:
                if rel.get('Type') != 'CHILD':
                    continue
                for wid in rel.get('Ids') or []:
                    w = block_map.get(wid)
                    if not w:
                        continue
                    if w.get('BlockType') == 'SELECTION_ELEMENT':
                        if w.get('SelectionStatus') == 'SELECTED':
                            parts.append('X')
                    elif w.get('BlockType') == 'WORD' and w.get('Text'):
                        parts.append(w['Text'])
            cell_text = ' '.join(parts).strip()
            cell_map[(r - 1, c - 1)] = cell_text
        rows = []
        for r in range(max_row):
            row_vals = []
            for c in range(max_col):
                row_vals.append(cell_map.get((r, c), ''))
            rows.append(row_vals)
        if rows:
            tables.append(rows)

    return {
        'text': text,
        'tables': tables,
        'layout_lines': layout_lines,
        'error': '',
    }


def _doctr_extract(document_bytes, mime_type, filename):
    """
    Call docTR deep-learning OCR/layout and normalize to text/layout_lines.

    Enabled when USE_DOCTR=1 and docTR is installed. Tables are not detected
    by docTR itself, so we currently return tables = [] while providing rich
    layout_lines and full text for downstream analyzers.
    """
    if not os.environ.get('USE_DOCTR'):
        return None
    global _DOCTR_MODEL
    try:
        from doctr.io import DocumentFile
        from doctr.models import ocr_predictor
    except ImportError:
        return None

    try:
        if _DOCTR_MODEL is None:
            # Lazy-load to avoid heavy startup cost when unused.
            _DOCTR_MODEL = ocr_predictor(pretrained=True)

        lower = (filename or '').lower()
        if mime_type == 'application/pdf' or lower.endswith('.pdf'):
            doc = DocumentFile.from_pdf(document_bytes)
        else:
            # from_images accepts a single bytes object or a list of files.
            doc = DocumentFile.from_images(document_bytes)

        result = _DOCTR_MODEL(doc)
        exported = result.export()
        pages = exported.get('pages') or []
        layout_lines = []
        for page in pages:
            for block in page.get('blocks') or []:
                for line in block.get('lines') or []:
                    words = line.get('words') or []
                    line_text = ' '.join(
                        (w.get('value') or '').strip()
                        for w in words
                        if w.get('value')
                    ).strip()
                    if line_text:
                        layout_lines.append(line_text)
        text = '\n'.join(layout_lines).strip()
        return {
            'text': text,
            'tables': [],
            'layout_lines': layout_lines,
            'error': '',
        }
    except Exception as e:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': str(e)}


def _google_document_ai_extract(document_bytes, mime_type):
    """
    Call Google Document AI (OCR processor). Returns normalized dict with
    text, tables, layout_lines, error.
    """
    project_id = os.environ.get('DOCUMENT_AI_PROJECT_ID') or os.environ.get('GOOGLE_CLOUD_PROJECT_ID')
    location = os.environ.get('DOCUMENT_AI_LOCATION') or os.environ.get('GOOGLE_CLOUD_LOCATION') or 'us'
    processor_id = os.environ.get('DOCUMENT_AI_PROCESSOR_ID')
    if not project_id or not processor_id:
        return None
    try:
        from google.cloud import documentai_v1 as documentai
    except ImportError:
        return None
    try:
        client = documentai.DocumentProcessorServiceClient()
        name = f'projects/{project_id}/locations/{location}/processors/{processor_id}'
        raw_doc = documentai.RawDocument(content=document_bytes, mime_type=mime_type)
        request = documentai.ProcessRequest(name=name, raw_document=raw_doc)
        result = client.process_document(request=request)
        doc = result.document
        text = (doc.text or '').strip()
        layout_lines = []
        tables = []
        if doc.pages:
            for page in doc.pages:
                if getattr(page, 'paragraphs', None):
                    for p in page.paragraphs:
                        layout = getattr(p, 'layout', None)
                        anchor = getattr(layout, 'text_anchor', None) if layout else None
                        segs = getattr(anchor, 'text_segments', []) or []
                        if segs and text:
                            s0 = getattr(segs[0], 'start_index', getattr(segs[0], 'startIndex', 0))
                            e0 = getattr(segs[0], 'end_index', getattr(segs[0], 'endIndex', 0))
                            seg = text[s0:e0].strip()
                            if seg:
                                layout_lines.append(seg)
                if getattr(page, 'tables', None):
                    for tbl in page.tables:
                        rows = []
                        for row in getattr(tbl, 'body_rows', []) or []:
                            cells = []
                            for cell in getattr(row, 'cells', []) or []:
                                layout = getattr(cell, 'layout', None)
                                anchor = getattr(layout, 'text_anchor', None) if layout else None
                                segs = getattr(anchor, 'text_segments', []) or []
                                cell_text = ''
                                if segs and text:
                                    s0 = getattr(segs[0], 'start_index', getattr(segs[0], 'startIndex', 0))
                                    e0 = getattr(segs[0], 'end_index', getattr(segs[0], 'endIndex', 0))
                                    cell_text = text[s0:e0].strip()
                                cells.append(cell_text)
                            rows.append(cells)
                        if rows:
                            tables.append(rows)
        if not layout_lines and text:
            layout_lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
        return {'text': text, 'tables': tables, 'layout_lines': layout_lines, 'error': ''}
    except Exception as e:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': str(e)}


def _azure_document_intelligence_extract(document_bytes, mime_type):
    """
    Call Azure Document Intelligence Layout. Returns normalized dict with
    text, tables, layout_lines, error.
    Enhanced to handle all table types and preserve exact layout.
    """
    endpoint = os.environ.get('AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT')
    key = os.environ.get('AZURE_DOCUMENT_INTELLIGENCE_KEY')
    if not endpoint or not key:
        return None
    try:
        from azure.ai.formrecognizer import DocumentAnalysisClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError:
        return None
    try:
        client = DocumentAnalysisClient(
            endpoint=endpoint.rstrip('/'),
            credential=AzureKeyCredential(key),
        )
        
        # Use the layout model which returns tables, paragraphs, and lines
        poller = client.begin_analyze_document(
            "prebuilt-layout",
            document=document_bytes,
            content_type=mime_type,
        )
        result = poller.result()
        
        # Get full text
        full_text = (getattr(result, 'content', '') or '').strip()
        layout_lines = []
        tables = []
        
        # Get all pages
        pages = getattr(result, 'pages', []) or []
        
        # Extract lines from each page in order (preserves layout)
        for page in pages:
            page_number = getattr(page, 'page_number', 0) or 0
            
            # Get lines (most accurate for layout order)
            for line in getattr(page, 'lines', []) or []:
                line_text = (getattr(line, 'content', '') or '').strip()
                if line_text:
                    layout_lines.append(line_text)
            
            # If no lines, try paragraphs
            if not any(getattr(p, 'lines', []) for p in pages[:1] if getattr(p, 'lines', [])):
                for para in getattr(page, 'paragraphs', []) or []:
                    para_text = (getattr(para, 'content', '') or '').strip()
                    if para_text:
                        layout_lines.append(para_text)
        
        # Extract tables - Azure returns tables with row/column info
        azure_tables = getattr(result, 'tables', []) or []
        for tbl_idx, tbl in enumerate(azure_tables):
            rows = []
            cells = getattr(tbl, 'cells', []) or []
            row_count = getattr(tbl, 'row_count', 0) or 0
            column_count = getattr(tbl, 'column_count', 0) or 0
            
            if cells and row_count > 0 and column_count > 0:
                # Build row map
                row_map = {}
                for cell in cells:
                    r = getattr(cell, 'row_index', 0) or 0
                    c = getattr(cell, 'column_index', 0) or 0
                    row_span = getattr(cell, 'row_span', 1) or 1
                    col_span = getattr(cell, 'column_span', 1) or 1
                    text = (getattr(cell, 'content', None) or '').strip()
                    
                    # Handle spanning cells
                    for dr in range(row_span):
                        for dc in range(col_span):
                            rr = r + dr
                            cc = c + dc
                            if rr not in row_map:
                                row_map[rr] = {}
                            # Keep first non-empty value for overlapping cells
                            if not row_map[rr].get(cc):
                                row_map[rr][cc] = text
                
                # Convert to list of lists
                if row_map:
                    for ri in range(row_count):
                        row_vals = []
                        row_cells = row_map.get(ri, {})
                        for ci in range(column_count):
                            row_vals.append(row_cells.get(ci, ''))
                        if any(row_vals):  # Only add non-empty rows
                            rows.append(row_vals)
            
            # Alternative: if cells don't have proper indices, extract raw
            if not rows and cells:
                # Just extract all cell contents in order
                row_vals = []
                for cell in cells:
                    text = (getattr(cell, 'content', None) or '').strip()
                    row_vals.append(text)
                if row_vals:
                    rows.append(row_vals)
            
            if rows:
                tables.append(rows)
        
        # If no tables from Azure, try to infer from text using layout detection
        if not tables and layout_lines:
            inferred = _infer_tables_from_layout_lines(layout_lines)
            if inferred:
                tables = inferred
        
        # Ensure we have some content
        if not full_text and layout_lines:
            full_text = '\n'.join(layout_lines)
        
        return {
            'text': full_text,
            'tables': tables,
            'layout_lines': layout_lines,
            'error': ''
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Azure Document Intelligence error: {str(e)}")
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': str(e)}

        if not layout_lines and full_text:
            layout_lines = [ln.strip() for ln in full_text.split('\n') if ln.strip()]

        return {
            'text': full_text.strip(),
            'tables': tables,
            'layout_lines': layout_lines,
            'error': '',
        }
    except Exception as e:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': str(e)}


def _infer_tables_from_layout_lines(layout_lines):
    """
    Infer tables from layout lines when the OCR doesn't return explicit table structures.
    This helps extract tables that appear as aligned text without borders.
    """
    if not layout_lines or len(layout_lines) < 2:
        return []
    
    import re
    tables = []
    current_table = []
    table_keywords = ['date', 'amount', 'debit', 'credit', 'balance', 'description', 'details', 
                      'transaction', 'withdrawal', 'deposit', 'type', 'ref', 'no.', 'number',
                      'qty', 'unit', 'price', 'total', 'subtotal', 'tax', 'rate']
    
    in_table = False
    
    for line in layout_lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
            
        # Check if line looks like a table header
        line_lower = line_stripped.lower()
        keyword_count = sum(1 for kw in table_keywords if kw in line_lower)
        
        # If line has multiple table keywords, it's likely a header
        if keyword_count >= 2:
            if current_table and len(current_table) >= 2:
                tables.append(current_table)
            current_table = [line_stripped]
            in_table = True
            continue
        
        # Check if line has consistent spacing (column separators)
        # Multiple spaces between words suggest columns
        spaced_parts = re.split(r'\s{2,}', line_stripped)
        
        if len(spaced_parts) >= 3:
            # This looks like a table row
            current_table.append(spaced_parts)
            in_table = True
        elif in_table and len(spaced_parts) >= 2:
            # Could still be a table row
            current_table.append(spaced_parts)
        elif in_table:
            # End of table
            if current_table and len(current_table) >= 2:
                tables.append(current_table)
            current_table = []
            in_table = False
    
    # Don't forget the last table
    if current_table and len(current_table) >= 2:
        tables.append(current_table)
    
    return tables


def _paddleocr_extract(document_bytes, mime_type, filename):
    """
    Extract text using PaddleOCR (Baidu's OCR engine).
    
    Enabled when USE_PADDLEOCR=1. PaddleOCR provides excellent table detection
    and layout analysis for documents.
    """
    if not os.environ.get('USE_PADDLEOCR'):
        return None
    
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        return None
    
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False, table=True)
        
        lower = (filename or '').lower()
        if mime_type == 'application/pdf' or lower.endswith('.pdf'):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(document_bytes)
                tmp_path = tmp.name
            
            try:
                result = ocr.ocr(tmp_path, table=True)
            finally:
                os.unlink(tmp_path)
        else:
            result = ocr.ocr(document_bytes)
        
        if not result or not result[0]:
            return {'text': '', 'tables': [], 'layout_lines': [], 'error': 'No text detected'}
        
        layout_lines = []
        tables = []
        
        for page_result in result:
            if not page_result:
                continue
            for line in page_result:
                if not line:
                    continue
                info = line[1]
                text = info[0] if isinstance(info, tuple) else info
                if text and str(text).strip():
                    layout_lines.append(str(text).strip())
        
        return {
            'text': '\n'.join(layout_lines),
            'tables': tables,
            'layout_lines': layout_lines,
            'error': '',
        }
    except Exception as e:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': str(e)}


def _easyocr_extract(document_bytes, mime_type, filename):
    """
    Extract text using EasyOCR (multi-language deep learning OCR).
    
    Enabled when USE_EASYOCR=1. EasyOCR supports 80+ languages.
    """
    if not os.environ.get('USE_EASYOCR'):
        return None
    
    try:
        import easyocr
    except ImportError:
        return None
    
    try:
        reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        
        if mime_type.startswith('image/') or any(filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']):
            result = reader.readtext(document_bytes)
        else:
            return None  # EasyOCR doesn't handle PDFs directly
        
        if not result:
            return {'text': '', 'tables': [], 'layout_lines': [], 'error': 'No text detected'}
        
        layout_lines = []
        for detection in result:
            text = detection[1] if len(detection) > 1 else ''
            if text and text.strip():
                layout_lines.append(text.strip())
        
        return {
            'text': ' '.join(layout_lines),
            'tables': [],
            'layout_lines': layout_lines,
            'error': '',
        }
    except Exception as e:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': str(e)}


def _rapidocr_extract(document_bytes, mime_type, filename):
    """
    Extract text using RapidOCR (fast ONNX-based OCR).
    
    Enabled when USE_RAPIDOCR=1. RapidOCR is optimized for speed.
    """
    if not os.environ.get('USE_RAPIDOCR'):
        return None
    
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    
    try:
        ocr = RapidOCR()
        
        if mime_type.startswith('image/') or any(filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']):
            result, elapsed = ocr(document_bytes)
        else:
            return None
        
        if not result:
            return {'text': '', 'tables': [], 'layout_lines': [], 'error': 'No text detected'}
        
        layout_lines = []
        for detection in result:
            text = detection[1] if len(detection) > 1 else ''
            if text and str(text).strip():
                layout_lines.append(str(text).strip())
        
        return {
            'text': '\n'.join(layout_lines),
            'tables': [],
            'layout_lines': layout_lines,
            'error': '',
        }
    except Exception as e:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': str(e)}


def _doclayout_extract(document_bytes, mime_type, filename):
    """
    Analyze document layout using doclayout-yolo.
    
    Enabled when USE_DOCLAYOUT=1. doclayout-yolo provides state-of-the-art
    document layout analysis including table detection.
    """
    if not os.environ.get('USE_DOCLAYOUT'):
        return None
    
    try:
        import doclayout_yolo
        import numpy as np
        from PIL import Image
        import io as io_module
    except ImportError:
        return None
    
    try:
        model = doclayout_yolo.YOLO("doclayout-yolo/doclayout_yolo_tabular")
        
        # Load image
        if mime_type.startswith('image/'):
            img = Image.open(io_module.BytesIO(document_bytes))
            img_array = np.array(img)
            results = model.predict(source=img_array, verbose=False, save=False)
        else:
            return None
        
        if not results or len(results) == 0:
            return {'text': '', 'tables': [], 'layout_lines': [], 'error': 'No layout detected'}
        
        result = results[0]
        layout_lines = []
        
        if hasattr(result, 'boxes') and result.boxes:
            for box in result.boxes:
                # Get class name and text
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                if conf > 0.5:  # Only high confidence
                    layout_lines.append(f"[{result.names[cls_id]}]")
        
        return {
            'text': '\n'.join(layout_lines),
            'tables': [],
            'layout_lines': layout_lines,
            'error': '',
        }
    except Exception as e:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': str(e)}


def _table_extraction_extract(document_bytes, mime_type, filename):
    """
    Extract tables using Tabula-py and Camelot-py.
    
    Enabled when USE_TABLE_EXTRACTION=1. Combines multiple table extraction
    engines for best results.
    """
    if not os.environ.get('USE_TABLE_EXTRACTION'):
        return None
    
    try:
        from tabula import read_pdf
        import pandas as pd
    except ImportError:
        pass
    except Exception:
        pass
    
    try:
        import camelot
    except ImportError:
        pass
    except Exception:
        pass
    
    # Table extraction from PDFs
    lower = (filename or '').lower()
    if not lower.endswith('.pdf'):
        return None
    
    tables = []
    
    try:
        # Try Tabula
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(document_bytes)
            tmp_path = tmp.name
        
        try:
            dfs = read_pdf(tmp_path, pages='all', multiple_tables=True)
            for df in dfs:
                if df is not None and not df.empty:
                    df = df.fillna('')
                    rows = df.values.tolist()
                    rows = [[str(cell).strip() for cell in row] for row in rows]
                    rows = [row for row in rows if any(cell for cell in row)]
                    if rows:
                        tables.append(rows)
        except Exception:
            pass
        
        # Try Camelot (lattice)
        try:
            camelot_tables = camelot.read_pdf(tmp_path, pages='all', flavor='lattice')
            for ct in camelot_tables:
                if ct.df is not None and not ct.df.empty:
                    rows = ct.df.values.tolist()
                    rows = [[str(cell).strip() for cell in row] for row in rows]
                    rows = [row for row in rows if any(cell for cell in row)]
                    if rows and rows not in tables:
                        tables.append(rows)
        except Exception:
            pass
        
        # Try Camelot (stream)
        try:
            camelot_tables = camelot.read_pdf(tmp_path, pages='all', flavor='stream')
            for ct in camelot_tables:
                if ct.df is not None and not ct.df.empty:
                    rows = ct.df.values.tolist()
                    rows = [[str(cell).strip() for cell in row] for row in rows]
                    rows = [row for row in rows if any(cell for cell in row)]
                    if rows and rows not in tables:
                        tables.append(rows)
        except Exception:
            pass
        
        os.unlink(tmp_path)
    except Exception:
        pass
    
    if tables:
        return {
            'text': '',
            'tables': tables,
            'layout_lines': [],
            'error': '',
        }
    
    return None


def run_smart_extraction(document_file):
    """
    Smart orchestrator over multiple extraction backends.

    Strategy (when USE_SMART_EXTRACTION is truthy):
    1) Try Amazon Textract first (if USE_AWS_TEXTRACT=1 and available).
       - If it returns tables, use it immediately.
       - If it only returns text or fails, keep its result but try docTR next.
    2) Try docTR (if USE_DOCTR=1 and available).
       - If it returns any text, prefer it over a "tables‑empty" Textract run.
    3) Try new AI backends if configured:
       - PaddleOCR (USE_PADDLEOCR=1)
       - EasyOCR (USE_EASYOCR=1)
       - RapidOCR (USE_RAPIDOCR=1)
       - doclayout-yolo (USE_DOCLAYOUT=1)
       - Table extraction (USE_TABLE_EXTRACTION=1)
    4) If neither AWS/docTR is configured or successful, fall back to:
       - Google Document AI (if configured), else
       - Azure Document Intelligence (if configured).

    If all backends are unavailable or produce no usable output, return None so
    services.run_extraction() can fall back to the local pdfplumber + Tesseract
    pipeline (which already yields text/tables/layout_lines).
    """
    if not os.environ.get('USE_SMART_EXTRACTION'):
        return None
    try:
        raw, mime_type, name = _read_file_to_bytes(document_file)
    except Exception as e:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': str(e)}

    textract_out = _aws_textract_extract(raw, mime_type, name)
    if textract_out and isinstance(textract_out, dict):
        # If Textract produced tables, it's our primary choice.
        if textract_out.get('tables'):
            return textract_out
        # Otherwise, keep it around in case all other backends fail.

    doctr_out = _doctr_extract(raw, mime_type, name)
    if doctr_out and isinstance(doctr_out, dict) and (doctr_out.get('text') or doctr_out.get('tables')):
        return doctr_out

    # Try new AI backends
    paddleocr_out = _paddleocr_extract(raw, mime_type, name)
    if paddleocr_out and (paddleocr_out.get('text') or paddleocr_out.get('tables')):
        return paddleocr_out
    
    easyocr_out = _easyocr_extract(raw, mime_type, name)
    if easyocr_out and (easyocr_out.get('text') or easyocr_out.get('tables')):
        return easyocr_out
    
    rapidocr_out = _rapidocr_extract(raw, mime_type, name)
    if rapidocr_out and (rapidocr_out.get('text') or rapidocr_out.get('tables')):
        return rapidocr_out
    
    doclayout_out = _doclayout_extract(raw, mime_type, name)
    if doclayout_out and (doclayout_out.get('text') or doclayout_out.get('tables')):
        return doclayout_out
    
    table_out = _table_extraction_extract(raw, mime_type, name)
    if table_out and table_out.get('tables'):
        return table_out

    # Fall back to existing Google / Azure integrations if configured.
    if os.environ.get('DOCUMENT_AI_PROJECT_ID') or os.environ.get('GOOGLE_CLOUD_PROJECT_ID'):
        out = _google_document_ai_extract(raw, mime_type)
        if out is not None:
            return out
    if os.environ.get('AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT') and os.environ.get('AZURE_DOCUMENT_INTELLIGENCE_KEY'):
        out = _azure_document_intelligence_extract(raw, mime_type)
        if out is not None:
            return out

    # As a last resort, if Textract gave us at least some text, return it;
    # otherwise let the caller drop down to the local extractor.
    if textract_out and isinstance(textract_out, dict) and (textract_out.get('text') or textract_out.get('tables')):
        return textract_out
    return None
