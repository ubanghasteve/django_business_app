"""
Smart File Processor
==================
Smart file processor that handles all types of files:
- PDF
- Word documents (doc, docx)
- Excel files (xls, xlsx)
- Images (jpg, png, gif, bmp, tiff)
- CSV files
- Text files
- And many more...
"""

import os
import re
import hashlib
import mimetypes
from datetime import datetime
from typing import Dict, Any, Optional

from django.core.files.uploadedfile import UploadedFile
from django.conf import settings


class SmartFileProcessor:
    """
    Smart file processor for payroll documents.
    Handles file validation, type detection, and metadata extraction.
    """
    
    FILE_TYPE_MAP = {
        '.pdf': 'pdf',
        '.doc': 'word',
        '.docx': 'word',
        '.xls': 'excel',
        '.xlsx': 'excel',
        '.xlsm': 'excel',
        '.csv': 'csv',
        '.jpg': 'image',
        '.jpeg': 'image',
        '.png': 'image',
        '.gif': 'image',
        '.bmp': 'image',
        '.tiff': 'image',
        '.tif': 'image',
        '.webp': 'image',
        '.txt': 'text',
        '.rtf': 'text',
        '.odt': 'text',
        '.ods': 'excel',
        '.ppt': 'other',
        '.pptx': 'other',
        '.zip': 'other',
        '.rar': 'other',
    }
    
    MIME_TYPE_MAP = {
        'application/pdf': 'pdf',
        'application/msword': 'word',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'word',
        'application/vnd.ms-excel': 'excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'excel',
        'text/csv': 'csv',
        'image/jpeg': 'image',
        'image/png': 'image',
        'image/gif': 'image',
        'image/bmp': 'image',
        'image/tiff': 'image',
        'image/webp': 'image',
        'text/plain': 'text',
        'application/zip': 'other',
    }
    
    PERIOD_PATTERNS = [
        r'(\d{4})[/\-](\d{1,2})',
        r'(\d{1,2})[/\-](\d{4})',
        r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[/\-](\d{4})',
        r'(\d{4})[/\-](jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*',
    ]
    
    MONTH_MAP = {
        'jan': 1, 'january': 1,
        'feb': 2, 'february': 2,
        'mar': 3, 'march': 3,
        'apr': 4, 'april': 4,
        'may': 5,
        'jun': 6, 'june': 6,
        'jul': 7, 'july': 7,
        'aug': 8, 'august': 8,
        'sep': 9, 'sept': 9, 'september': 9,
        'oct': 10, 'october': 10,
        'nov': 11, 'november': 11,
        'dec': 12, 'december': 12,
    }
    
    def __init__(self, file: UploadedFile, company, user):
        """
        Initialize the file processor.
        
        Args:
            file: The uploaded file
            company: Company profile
            user: User who uploaded the file
        """
        self.file = file
        self.company = company
        self.user = user
        self.result = {
            'original_filename': file.name,
            'title': '',
            'file_type': 'other',
            'mime_type': '',
            'file_size': file.size,
            'file_hash': '',
            'period_month': None,
            'period_year': None,
            'error': None,
        }
    
    def process(self) -> Dict[str, Any]:
        """
        Process the uploaded file and extract metadata.
        
        Returns:
            Dict containing processed file information
        """
        try:
            self._validate_file()
            self._detect_file_type()
            self._calculate_hash()
            self._extract_title()
            self._detect_period()
            
            return self.result
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.result['error'] = str(e)
            return self.result
    
    def _validate_file(self) -> None:
        """Validate the uploaded file."""
        if not self.file:
            raise ValueError("No file provided")
        
        if self.file.size == 0:
            raise ValueError("File is empty")
        
        max_size = getattr(settings, 'FILE_UPLOAD_MAX_MEMORY_SIZE', 10 * 1024 * 1024)
        if self.file.size > max_size * 10:
            raise ValueError(f"File size exceeds maximum allowed ({max_size / 1024 / 1024 * 10:.0f}MB)")
    
    def _detect_file_type(self) -> None:
        """Detect the file type from extension and MIME type."""
        ext = self._get_extension()
        mime_type = self._get_mime_type()
        
        file_type = self.FILE_TYPE_MAP.get(ext.lower())
        
        if not file_type:
            mime_type_mapped = self.MIME_TYPE_MAP.get(mime_type)
            if mime_type_mapped:
                file_type = mime_type_mapped
        
        if not file_type:
            file_type = 'other'
        
        self.result['file_type'] = file_type
        self.result['mime_type'] = mime_type
    
    def _calculate_hash(self) -> None:
        """Calculate SHA256 hash of the file."""
        try:
            hash_md5 = hashlib.sha256()
            
            for chunk in self.file.chunks():
                hash_md5.update(chunk)
            
            self.result['file_hash'] = hash_md5.hexdigest()
            
            self.file.seek(0)
            
        except Exception:
            pass
    
    def _extract_title(self) -> None:
        """Extract a title from the filename."""
        filename = self.file.name
        
        title = os.path.splitext(filename)[0]
        
        title = re.sub(r'[-_]+', ' ', title)
        
        title = re.sub(r'\s+', ' ', title).strip()
        
        title = title.title()
        
        if len(title) > 100:
            title = title[:100]
        
        self.result['title'] = title
    
    def _detect_period(self) -> None:
        """Detect pay period (month/year) from filename."""
        filename = self.file.name.lower()
        
        for pattern in self.PERIOD_PATTERNS:
            match = re.search(pattern, filename)
            if match:
                groups = match.groups()
                
                if len(groups) == 2:
                    first, second = groups[0].lower(), groups[1].lower()
                    
                    if first.isdigit() and second.isdigit():
                        if len(first) == 4:
                            year = int(first)
                            month = int(second)
                        else:
                            year = int(second)
                            month = int(first)
                        
                        if 1 <= month <= 12 and 1990 <= year <= 2100:
                            self.result['period_year'] = year
                            self.result['period_month'] = month
                            return
                    
                    elif len(first) == 4 and second in self.MONTH_MAP:
                        year = int(first)
                        month = self.MONTH_MAP[second]
                        self.result['period_year'] = year
                        self.result['period_month'] = month
                        return
                    
                    elif first in self.MONTH_MAP and second.isdigit():
                        month = self.MONTH_MAP[first]
                        year = int(second)
                        if len(second) == 4:
                            self.result['period_year'] = year
                            self.result['period_month'] = month
                            return
        
        current_year = datetime.now().year
        current_month = datetime.now().month
        
        year_match = re.search(r'20\d{2}', filename)
        if year_match:
            try:
                year = int(year_match.group())
                if 1990 <= year <= 2100:
                    self.result['period_year'] = year
            except ValueError:
                pass
        
        month_match = re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', filename)
        if month_match:
            month = self.MONTH_MAP.get(month_match.group())
            if month:
                self.result['period_month'] = month
    
    def _get_extension(self) -> str:
        """Get file extension."""
        return os.path.splitext(self.file.name)[1]
    
    def _get_mime_type(self) -> str:
        """Get MIME type of the file."""
        mime_type, _ = mimetypes.guess_type(self.file.name)
        if mime_type:
            return mime_type
        
        content_type = getattr(self.file, 'content_type', '')
        if content_type:
            return content_type
        
        return 'application/octet-stream'
    
    @staticmethod
    def get_file_icon(file_type: str) -> tuple:
        """
        Get icon and color for file type.
        
        Returns:
            Tuple of (icon_class, color)
        """
        icons = {
            'pdf': ('fa-file-pdf', '#e74c3c'),
            'word': ('fa-file-word', '#2b579a'),
            'excel': ('fa-file-excel', '#217346'),
            'image': ('fa-file-image', '#27ae60'),
            'csv': ('fa-file-csv', '#16a085'),
            'text': ('fa-file-alt', '#7f8c8d'),
            'other': ('fa-file', '#95a5a6'),
        }
        return icons.get(file_type, ('fa-file', '#95a5a6'))
    
    @staticmethod
    def can_preview(file_type: str) -> bool:
        """Check if file type can be previewed in browser."""
        preview_types = ['pdf', 'image']
        return file_type in preview_types
    
    @staticmethod
    def get_supported_extensions() -> list:
        """Get list of supported file extensions."""
        return list(SmartFileProcessor.FILE_TYPE_MAP.keys())


class FileTypeDetector:
    """Detects file type from filename and content type."""
    
    MIME_TO_TYPE_MAP = {
        "application/pdf": "pdf",
        "application/vnd.ms-excel": "excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
        "application/vnd.ms-excel.sheet.macroEnabled.12": "excel",
        "image/jpeg": "image",
        "image/png": "image",
        "image/gif": "image",
        "image/webp": "image",
        "application/msword": "word",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word",
        "text/csv": "csv",
        "text/plain": "text",
        "application/zip": "other",
    }
    
    EXTENSION_TO_TYPE_MAP = {
        ".pdf": "pdf",
        ".xls": "excel",
        ".xlsx": "excel",
        ".xlsm": "excel",
        ".jpg": "image",
        ".jpeg": "image",
        ".png": "image",
        ".gif": "image",
        ".webp": "image",
        ".doc": "word",
        ".docx": "word",
        ".csv": "csv",
        ".txt": "text",
        ".zip": "other",
    }
    
    @classmethod
    def get_file_type(cls, filename: str, mime_type: str = "") -> str:
        ext = os.path.splitext(filename)[1].lower()
        if ext in cls.EXTENSION_TO_TYPE_MAP:
            return cls.EXTENSION_TO_TYPE_MAP[ext]
        if mime_type and mime_type in cls.MIME_TO_TYPE_MAP:
            return cls.MIME_TO_TYPE_MAP[mime_type]
        return "other"
    
    @classmethod
    def get_mime_type(cls, filename: str, content_type: str = "") -> str:
        if content_type and content_type != "application/octet-stream":
            return content_type
        return "application/octet-stream"


class FileNameParser:
    """Parses filename to extract metadata."""
    
    MONTH_NAMES = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "sept": 9, "september": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    
    @classmethod
    def parse_filename(cls, filename: str) -> Dict[str, Any]:
        result = {
            "month": None,
            "year": None,
            "category_hint": None,
        }
        
        base_name = os.path.splitext(filename)[0].lower()
        
        patterns = [
            (r"(\d{4})[_\-](\d{1,2})", "year_month"),
            (r"(\d{1,2})[_\-](\d{4})", "month_year"),
            (r"payslip[_\-]?(\w+)[_\-]?(\d{4})", "payslip"),
            (r"salary[_\-]?(\w+)[_\-]?(\d{4})", "salary"),
            (r"report[_\-]?(\w+)[_\-]?(\d{4})", "report"),
        ]
        
        for pattern, pattern_type in patterns:
            match = re.search(pattern, base_name)
            if match:
                if pattern_type in ("year_month",):
                    year, month = int(match.group(1)), int(match.group(2))
                    if 1 <= month <= 12 and 2000 <= year <= 2100:
                        result["year"] = year
                        result["month"] = month
                        break
                elif pattern_type in ("month_year",):
                    month, year = int(match.group(1)), int(match.group(2))
                    if 1 <= month <= 12 and 2000 <= year <= 2100:
                        result["year"] = year
                        result["month"] = month
                        break
                elif pattern_type in ("payslip", "salary", "report"):
                    month_str = match.group(1).lower()
                    year = int(match.group(2))
                    if month_str in cls.MONTH_NAMES:
                        result["month"] = cls.MONTH_NAMES[month_str]
                        result["year"] = year
                        result["category_hint"] = pattern_type
                        break
        
        for keyword, category in [
            ("payslip", "payslip"),
            ("salary", "payslip"),
            ("report", "report"),
            ("contract", "contract"),
            ("tax", "tax_document"),
            ("pension", "pension"),
            ("bank", "bank_transfer"),
            ("loan", "loan"),
            ("bonus", "bonus"),
            ("allowance", "allowance"),
            ("deduction", "deduction"),
            ("leave", "leave"),
            ("termination", "termination"),
        ]:
            if keyword in base_name:
                result["category_hint"] = category
                break
        
        return result
    
    @classmethod
    def generate_title(cls, filename: str, month: int = None, year: int = None) -> str:
        base_name = os.path.splitext(filename)[0]
        title = base_name.replace("_", " ").replace("-", " ").title()
        
        if month and year:
            from datetime import date
            month_name = date(year, month, 1).strftime("%B")
            title = f"{title} - {month_name} {year}"
        elif year:
            title = f"{title} - {year}"
        
        return title


class FileProcessor:
    """Processes uploaded files."""
    
    MAX_FILE_SIZE = 50 * 1024 * 1024
    ALLOWED_EXTENSIONS = {
        ".pdf", ".xls", ".xlsx", ".xlsm",
        ".jpg", ".jpeg", ".png", ".gif", ".webp",
        ".doc", ".docx", ".csv", ".txt", ".zip",
        ".bmp", ".tiff", ".tif", ".rtf", ".odt", ".ods",
        ".ppt", ".pptx", ".rar",
    }
    
    @classmethod
    def validate_file(cls, file) -> tuple:
        if file.size > cls.MAX_FILE_SIZE:
            return False, f"File size exceeds {cls.MAX_FILE_SIZE / (1024 * 1024)}MB limit"
        
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in cls.ALLOWED_EXTENSIONS:
            return False, f"File type {ext} is not allowed"
        
        return True, ""
    
    @classmethod
    def process_upload(cls, file, company_id: int, user_id: int) -> Dict[str, Any]:
        is_valid, error = cls.validate_file(file)
        if not is_valid:
            raise ValueError(error)
        
        file_type = FileTypeDetector.get_file_type(
            file.name, getattr(file, "content_type", "")
        )
        mime_type = FileTypeDetector.get_mime_type(
            file.name, getattr(file, "content_type", "")
        )
        
        parsed = FileNameParser.parse_filename(file.name)
        title = FileNameParser.generate_title(
            file.name,
            month=parsed.get("month"),
            year=parsed.get("year"),
        )
        
        return {
            "original_filename": file.name,
            "file_type": file_type,
            "mime_type": mime_type,
            "file_size": file.size,
            "title": title,
            "month": parsed.get("month"),
            "year": parsed.get("year"),
            "category_hint": parsed.get("category_hint"),
        }


def get_file_icon(file_type: str) -> tuple:
    """Get icon and color for file type."""
    return SmartFileProcessor.get_file_icon(file_type)


def can_preview(file_type: str) -> bool:
    """Check if file type can be previewed."""
    return SmartFileProcessor.can_preview(file_type)


def get_supported_extensions() -> list:
    """Get supported file extensions."""
    return list(SmartFileProcessor.FILE_TYPE_MAP.keys())
