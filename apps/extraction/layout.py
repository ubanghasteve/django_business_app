# -*- coding: utf-8 -*-
"""
Layout-aware extraction: preserve reading order and structure for smarter analysis.
- PDF: extract text in reading order, group by lines/blocks, and infer tables
  even when there are no visible grid/border lines (text-only tables).
- Image: OCR with document-optimized config and line grouping.

SUPER SMART: Multiple strategies for detecting invisible tables and preserving exact layout.
"""
import re
from collections import defaultdict


def _detect_column_positions(lines, min_occurrences=3):
    """
    Detect column positions by finding vertical alignment of text across multiple lines.
    This finds where columns are even if there's no visible border.
    """
    if not lines or len(lines) < min_occurrences:
        return []
    
    # Find all word positions
    all_positions = []
    for line in lines:
        if not line.strip():
            continue
        pos = 0
        for i, char in enumerate(line):
            if char != ' ':
                pos = i
                break
        all_positions.append(pos)
    
    if not all_positions:
        return []
    
    # Cluster positions that are close together
    positions = sorted(set(all_positions))
    clusters = []
    if positions:
        current_cluster = [positions[0]]
        for pos in positions[1:]:
            if pos - current_cluster[-1] <= 2:  # Within 2 chars
                current_cluster.append(pos)
            else:
                clusters.append(sum(current_cluster) // len(current_cluster))
                current_cluster = [pos]
        if current_cluster:
            clusters.append(sum(current_cluster) // len(current_cluster))
    
    return clusters


def _slice_row_by_positions(row_text, positions):
    """Slice a row string by detected column positions."""
    if not positions or not row_text:
        return []
    
    # Ensure row is long enough
    row_text = row_text.ljust(positions[-1] + 20)
    
    cells = []
    starts = positions
    ends = starts[1:] + [len(row_text)]
    
    for s, e in zip(starts, ends):
        cell = row_text[s:e].strip()
        cells.append(cell)
    
    return cells


def _infer_tables_from_text(page_text):
    """
    SUPER SMART table detection for borderless/invisible tables.
    
    Strategies:
    1. Bank statement header detection (Trans Date, Balance, etc.)
    2. Column position detection from vertical alignment
    3. Spacing-based detection (2+ spaces = column separator)
    4. Keyword-based detection (table-like content patterns)
    5. Consistent row length detection
    
    Returns all detected tables, not just the best one.
    """
    if not page_text:
        return []
    
    lines = [ln.rstrip('\n') for ln in page_text.split('\n')]
    all_tables = []
    
    # ===== Strategy 1: Bank Statement Header Detection =====
    header_table = _detect_bank_statement_table(lines)
    if header_table:
        all_tables.extend(header_table)
    
    # ===== Strategy 2: Invoice/Receipt Table Detection =====
    invoice_table = _detect_invoice_table(lines)
    if invoice_table:
        all_tables.extend(invoice_table)
    
    # ===== Strategy 3: Column Position Detection =====
    position_table = _detect_tables_by_column_positions(lines)
    if position_table:
        all_tables.extend(position_table)
    
    # ===== Strategy 4: Spacing-based Detection =====
    spacing_tables = _detect_tables_by_spacing(lines)
    if spacing_tables:
        all_tables.extend(spacing_tables)
    
    # ===== Strategy 5: Keyword Pattern Detection =====
    keyword_tables = _detect_tables_by_keywords(lines)
    if keyword_tables:
        all_tables.extend(keyword_tables)
    
    return all_tables


def _detect_bank_statement_table(lines):
    """Detect bank statement tables with headers like Trans Date, Balance, etc."""
    tables = []
    header_keywords = ['trans', 'date', 'transaction', 'balance', 'withdrawal', 'deposit', 'value']
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        # Check if this line has multiple bank statement keywords
        matches = sum(1 for kw in header_keywords if kw in line_lower)
        
        if matches >= 3:  # Likely a table header
            # Try to detect column positions from this header
            # Common column headers and their approximate positions
            col_patterns = [
                ('trans date', 0, 12),
                ('value date', 12, 22),
                ('ref number', 22, 35),
                ('ref. number', 22, 35),
                ('transaction details', 35, 70),
                ('details', 35, 60),
                ('withdrawal', 70, 85),
                ('deposit', 70, 85),
                ('credit', 70, 85),
                ('debit', 70, 85),
                ('amount', 70, 85),
                ('balance', 85, 100),
            ]
            
            detected_cols = []
            for pattern, start, end in col_patterns:
                if pattern in line_lower:
                    idx = line_lower.find(pattern)
                    if idx >= 0:
                        detected_cols.append((idx, pattern))
            
            if detected_cols:
                detected_cols.sort(key=lambda x: x[0])
                positions = [pos for pos, _ in detected_cols]
                
                # Extract rows using these positions
                table_rows = []
                
                # Header row
                header_cells = _slice_row_by_positions(line, positions)
                if any(c for c in header_cells):
                    table_rows.append(header_cells)
                
                # Data rows
                for row_line in lines[i+1:]:
                    if not row_line.strip():
                        if table_rows and len(table_rows) > 1:
                            break
                        continue
                    
                    cells = _slice_row_by_positions(row_line, positions)
                    if any(c for c in cells):
                        table_rows.append(cells)
                
                if len(table_rows) >= 2:
                    tables.append(table_rows)
    
    return tables


def _detect_invoice_table(lines):
    """Detect invoice/receipt tables with Item, Qty, Rate, Amount columns."""
    tables = []
    
    for i, line in enumerate(lines):
        line_lower = line.lower()
        
        # Invoice table keywords
        invoice_keywords = ['item', 'description', 'quantity', 'qty', 'unit price', 'rate', 'amount', 'total']
        matches = sum(1 for kw in invoice_keywords if kw in line_lower)
        
        if matches >= 2:
            # Try position-based extraction
            col_patterns = [
                ('item', 0, 8),
                ('description', 8, 40),
                ('quantity', 40, 50),
                ('qty', 40, 50),
                ('unit price', 50, 65),
                ('rate', 50, 65),
                ('amount', 65, 80),
                ('total', 65, 80),
            ]
            
            positions = []
            for pattern, start, end in col_patterns:
                if pattern in line_lower:
                    idx = line_lower.find(pattern)
                    if idx >= 0:
                        positions.append(idx)
            
            if len(positions) >= 2:
                positions = sorted(set(positions))
                table_rows = []
                
                # Header
                header_cells = _slice_row_by_positions(line, positions)
                if any(c for c in header_cells):
                    table_rows.append(header_cells)
                
                # Data rows
                for row_line in lines[i+1:]:
                    if not row_line.strip():
                        if table_rows and len(table_rows) > 1:
                            break
                        continue
                    
                    cells = _slice_row_by_positions(row_line, positions)
                    if any(c for c in cells):
                        table_rows.append(cells)
                
                if len(table_rows) >= 2:
                    tables.append(table_rows)
    
    return tables


def _detect_tables_by_column_positions(lines):
    """Detect tables by finding consistent column positions across multiple lines."""
    tables = []
    
    # Find lines that could be table headers (contain multiple keywords)
    table_indicators = [
        'date', 'description', 'amount', 'debit', 'credit', 'balance', 
        'item', 'quantity', 'price', 'rate', 'total', 'qty', 'unit',
        'code', 'name', 'type', 'ref', 'no', 'number', 'account'
    ]
    
    header_candidates = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        line_lower = line.lower()
        matches = sum(1 for ind in table_indicators if ind in line_lower)
        if matches >= 2:
            header_candidates.append((i, line))
    
    for header_idx, header_line in header_candidates:
        # Find column positions from this header
        positions = _detect_column_positions(lines[header_idx:header_idx+10], min_occurrences=3)
        
        if len(positions) >= 2:
            # Extract table with these positions
            table_rows = []
            
            # Header
            header_cells = _slice_row_by_positions(header_line, positions)
            if any(c for c in header_cells):
                table_rows.append(header_cells)
            
            # Data rows - look for next 50 lines or until gap
            for row_line in lines[header_idx+1:header_idx+51]:
                if not row_line.strip():
                    if table_rows and len(table_rows) > 1:
                        break
                    continue
                
                cells = _slice_row_by_positions(row_line, positions)
                if cells and any(c for c in cells):
                    table_rows.append(cells)
            
            if len(table_rows) >= 2:
                tables.append(table_rows)
    
    return tables


def _detect_tables_by_spacing(lines):
    """Detect tables based on consistent spacing (2+ spaces = column separator)."""
    tables = []
    current_rows = []
    row_lengths = []
    
    for line in lines:
        raw = line.strip()
        if not raw:
            if current_rows and len(current_rows) >= 2:
                tables.append(list(current_rows))
            current_rows = []
            row_lengths = []
            continue
        
        # Split by 2+ spaces
        parts = [p.strip() for p in re.split(r'\s{2,}', raw) if p.strip()]
        
        # Check if this looks like a table row
        if len(parts) >= 2:
            # Track row length consistency
            row_len = len(parts)
            if not row_lengths:
                current_rows.append(parts)
                row_lengths.append(row_len)
            elif row_len == row_lengths[-1] or abs(row_len - row_lengths[-1]) <= 1:
                current_rows.append(parts)
                row_lengths.append(row_len)
            else:
                # Row length changed - might be end of table
                if current_rows and len(current_rows) >= 2:
                    tables.append(list(current_rows))
                current_rows = [parts]
                row_lengths = [row_len]
        else:
            if current_rows and len(current_rows) >= 2:
                tables.append(list(current_rows))
            current_rows = []
            row_lengths = []
    
    # Don't forget last table
    if current_rows and len(current_rows) >= 2:
        tables.append(list(current_rows))
    
    return tables


def _detect_tables_by_keywords(lines):
    """Detect tables by finding patterns of table-like content."""
    tables = []
    
    # Look for sequences of lines that have similar structure
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        
        # Check if line contains table-related keywords
        keywords = ['date', 'amount', 'description', 'balance', 'debit', 'credit', 'qty', 'quantity', 'price', 'rate']
        has_keyword = any(kw in line.lower() for kw in keywords)
        
        if has_keyword:
            # Start building a table
            table_rows = [line]
            
            # Look for next 30 lines that could be table rows
            for next_line in lines[i+1:i+31]:
                next_stripped = next_line.strip()
                if not next_stripped:
                    if table_rows and len(table_rows) > 3:
                        break
                    continue
                
                # Check if this looks like a data row (has numbers/dates)
                has_data = bool(re.search(r'\d', next_stripped))
                
                if has_data or len(next_stripped.split()) >= 2:
                    table_rows.append(next_stripped)
                else:
                    if len(table_rows) > 3:
                        break
            
            # If we have enough rows, process them
            if len(table_rows) >= 3:
                # Try to extract consistent columns
                processed_rows = []
                for row in table_rows:
                    # Try splitting by multiple spaces first
                    parts = [p.strip() for p in re.split(r'\s{2,}', row) if p.strip()]
                    if len(parts) >= 2:
                        processed_rows.append(parts)
                    else:
                        # Try single space split
                        parts = row.split()
                        if len(parts) >= 2:
                            processed_rows.append(parts)
                
                if processed_rows and len(processed_rows) >= 3:
                    tables.append(processed_rows)
            
            i += len(table_rows)
        else:
            i += 1
    
    return tables


def pdf_extract_text_and_tables_single_pass(pdf_path_or_file):
    """
    Single-pass PDF extraction: open once, get text and tables.
    Returns: dict with text (str), tables (list), layout_lines (list of str, one per logical line).
    
    ENHANCED: More aggressive table detection for borderless tables.
    """
    try:
        import pdfplumber
    except ImportError:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': 'pdfplumber not installed'}

    try:
        if hasattr(pdf_path_or_file, 'read'):
            pdf_path_or_file.seek(0)
            pdf = pdfplumber.open(pdf_path_or_file)
        else:
            pdf = pdfplumber.open(pdf_path_or_file)
        
        all_text_parts = []
        all_tables = []
        layout_lines = []
        pages = []
        
        with pdf as p:
            for page in p.pages:
                page_tables = page.extract_tables()
                per_page_tables = []
                page_layout_lines = []
                
                # Strategy 1: pdfplumber's built-in table extraction
                if page_tables:
                    for t in page_tables:
                        rows = [[(str(c).strip() if c is not None else '') for c in row] for row in t]
                        if rows:
                            all_tables.append(rows)
                            per_page_tables.append(rows)
                
                # Text in reading order
                page_text = page.extract_text(x_tolerance=2, y_tolerance=2)
                if page_text:
                    all_text_parts.append(page_text)
                    for line in page_text.split('\n'):
                        line = line.strip()
                        if line:
                            layout_lines.append(line)
                            page_layout_lines.append(line)
                
                # Strategy 2-5: Infer borderless tables from text
                # This is the SUPER SMART part - detects tables without borders
                inferred_tables = _infer_tables_from_text(page_text)
                for t in inferred_tables:
                    if t:  # Only add non-empty tables
                        # Check if this table is already detected (avoid duplicates)
                        is_duplicate = False
                        for existing in all_tables:
                            if existing and len(existing) == len(t) and existing[0] == t[0]:
                                is_duplicate = True
                                break
                        if not is_duplicate:
                            all_tables.append(t)
                            per_page_tables.append(t)
                
                pages.append({
                    'page_number': len(pages) + 1,
                    'text': page_text or '',
                    'tables': per_page_tables,
                    'layout_lines': page_layout_lines,
                })
        
        pdf.close()
        text = '\n'.join(all_text_parts)
        
        return {
            'text': text,
            'tables': all_tables,
            'layout_lines': layout_lines,
            'pages': pages,
            'error': '',
        }
    except Exception as e:
        return {'text': '', 'tables': [], 'layout_lines': [], 'error': str(e)}


def image_extract_with_layout(image_path_or_file):
    """
    OCR with layout-friendly config for documents.
    ENHANCED: Multiple PSM modes for better text detection.
    Returns: dict with text (str), layout_lines (list of str), error (str).
    """
    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError:
        return {'text': '', 'layout_lines': [], 'error': 'pytesseract or Pillow not installed'}

    import sys
    if sys.platform == 'win32':
        import os
        if os.path.isfile(r'C:\Program Files\Tesseract-OCR\tesseract.exe'):
            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

    try:
        if hasattr(image_path_or_file, 'read'):
            image_path_or_file.seek(0)
            img = Image.open(image_path_or_file)
        else:
            img = Image.open(image_path_or_file)
        img.load()
        
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Try multiple OCR configurations for best results
        configs = [
            '--psm 6 --oem 3',  # Assume uniform block of text
            '--psm 4 --oem 3',  # Treat the image as a single column of text of variable sizes
            '--psm 3 --oem 3',  # Fully automatic page segmentation, but no OSD
            '--psm 11 --oem 1',  # Sparse text. Find as much text as possible in no particular order
        ]
        
        best_text = ''
        best_lines = []
        
        for config in configs:
            try:
                text = pytesseract.image_to_string(img, config=config)
                text = (text or '').strip()
                
                if text:
                    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
                    
                    # Keep the result with the most lines (likely most complete)
                    if len(lines) > len(best_lines):
                        best_text = text
                        best_lines = lines
            except Exception:
                continue
        
        # If OCR with default configs didn't work well, try image enhancement
        if not best_text or len(best_lines) < 5:
            try:
                # Enhance image
                gray = img.convert('L')
                enhancer = ImageEnhance.Contrast(gray)
                enhanced = enhancer.enhance(2.0)
                enhanced = enhanced.filter(ImageFilter.SMOOTH)
                
                text = pytesseract.image_to_string(enhanced, config='--psm 6 --oem 1')
                text = (text or '').strip()
                
                if text:
                    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
                    if len(lines) > len(best_lines):
                        best_text = text
                        best_lines = lines
            except Exception:
                pass
        
        # Try to infer tables from the extracted text
        inferred_tables = _infer_tables_from_text(best_text)
        
        return {
            'text': best_text, 
            'layout_lines': best_lines, 
            'tables': inferred_tables,
            'error': ''
        }
    except Exception as e:
        return {'text': '', 'layout_lines': [], 'error': str(e)}
