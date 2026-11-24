# -*- coding: utf-8 -*-
"""
Scanned PDF fallback: when a PDF has no or minimal text layer (e.g. scanned bank statement),
render each page to an image and run Tesseract OCR. Use when pdfplumber returns empty text.
"""


def pdf_ocr_fallback(pdf_path_or_file, min_text_length=150):
    """
    Render PDF pages to images and run Tesseract OCR. Use when normal PDF extraction
    returns empty or very short text (scanned document).
    Returns: dict with text (str), layout_lines (list), error (str).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return {'text': '', 'layout_lines': [], 'error': 'PyMuPDF not installed (pip install pymupdf)'}
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return {'text': '', 'layout_lines': [], 'error': 'pytesseract or Pillow not installed'}

    import sys
    if sys.platform == 'win32':
        import os
        if os.path.isfile(r'C:\Program Files\Tesseract-OCR\tesseract.exe'):
            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

    try:
        if hasattr(pdf_path_or_file, 'read'):
            pdf_path_or_file.seek(0)
            data = pdf_path_or_file.read()
            doc = fitz.open(stream=data, filetype='pdf')
        else:
            doc = fitz.open(pdf_path_or_file)
        parts = []
        layout_lines = []
        # 150 DPI is a good balance for OCR on statements
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=150, alpha=False)
            try:
                img = pix.pil_image()
            except AttributeError:
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            page_text = pytesseract.image_to_string(img, config='--psm 6 --oem 3')
            page_text = (page_text or '').strip()
            if page_text:
                parts.append(page_text)
                for line in page_text.split('\n'):
                    line = line.strip()
                    if line:
                        layout_lines.append(line)
        doc.close()
        text = '\n'.join(parts)
        return {'text': text.strip(), 'layout_lines': layout_lines, 'error': ''}
    except Exception as e:
        return {'text': '', 'layout_lines': [], 'error': str(e)}
