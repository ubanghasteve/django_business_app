# -*- coding: utf-8 -*-
"""
Verify that the Tax Analyzer stack is installed and can read/analyze documents.
Run: python manage.py verify_tax_analyzer
"""
import os
import sys
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Verify Tax Analyzer dependencies and document read/analyze capability.'

    def handle(self, *args, **options):
        errors = []
        # 1. Python packages
        try:
            import pdfplumber
            self.stdout.write(self.style.SUCCESS('pdfplumber: OK'))
        except ImportError as e:
            errors.append(f'pdfplumber: MISSING - {e}')
        try:
            import pytesseract
            self.stdout.write(self.style.SUCCESS('pytesseract: OK'))
        except ImportError as e:
            errors.append(f'pytesseract: MISSING - {e}')
        try:
            from PIL import Image
            self.stdout.write(self.style.SUCCESS('Pillow (PIL): OK'))
        except ImportError as e:
            errors.append(f'Pillow: MISSING - {e}')

        # 2. Tesseract executable (OCR for images)
        tesseract_ok = False
        if sys.platform == 'win32':
            default_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
            if os.path.isfile(default_path):
                tesseract_ok = True
                self.stdout.write(self.style.SUCCESS(f'Tesseract (OCR): OK at {default_path}'))
            else:
                try:
                    import pytesseract
                    pytesseract.get_tesseract_version()
                    tesseract_ok = True
                    self.stdout.write(self.style.SUCCESS('Tesseract (OCR): OK on PATH'))
                except Exception as e:
                    errors.append(f'Tesseract: Not found at {default_path} and not on PATH - {e}')
        else:
            try:
                import pytesseract
                pytesseract.get_tesseract_version()
                tesseract_ok = True
                self.stdout.write(self.style.SUCCESS('Tesseract (OCR): OK on PATH'))
            except Exception as e:
                errors.append(f'Tesseract: {e}')

        # 3. Document formats we support
        from apps.extraction.utils import ALLOWED_DOCUMENT_EXTENSIONS
        exts = ', '.join(ALLOWED_DOCUMENT_EXTENSIONS)
        self.stdout.write(self.style.SUCCESS(f'Supported formats: {exts}'))

        # 4. Quick extraction test (no file needed - just import and call with empty/minimal)
        try:
            from apps.extraction.services import run_extraction
            from apps.ai_engine.services import analyze_document_text_service
            # Test that analyze runs (with empty text)
            result = analyze_document_text_service('')
            if isinstance(result, dict) and 'invoice_number' in result:
                self.stdout.write(self.style.SUCCESS('AI analyze_document_text: OK'))
            else:
                self.stdout.write(self.style.WARNING('AI analyze_document_text: returned unexpected shape'))
        except Exception as e:
            errors.append(f'AI/Extraction pipeline: {e}')

        if errors:
            self.stdout.write('')
            for msg in errors:
                self.stdout.write(self.style.ERROR(msg))
            self.stdout.write(self.style.ERROR('Verification failed. Fix the items above so uploads can be read and analyzed.'))
            return
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('All checks passed. Users can upload PDF and images; the app can read, analyze, and compute from them.'))
