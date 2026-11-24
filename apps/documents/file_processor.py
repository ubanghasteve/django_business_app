"""
Smart Document File Processor
===========================
Smart file processor for document extraction app.
Handles file validation, type detection, and metadata extraction.
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
    Smart file processor for documents.
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
            'error': None,
        }
    
    def process(self) -> Dict[str, Any]:
        try:
            self._validate_file()
            self._detect_file_type()
            self._calculate_hash()
            self._extract_title()
            
            return self.result
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.result['error'] = str(e)
            return self.result
    
    def _validate_file(self) -> None:
        if not self.file:
            raise ValueError("No file provided")
        
        if self.file.size == 0:
            raise ValueError("File is empty")
        
        max_size = 100 * 1024 * 1024
        if self.file.size > max_size:
            raise ValueError(f"File size exceeds maximum allowed ({max_size / 1024 / 1024:.0f}MB)")
    
    def _detect_file_type(self) -> None:
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
        try:
            hash_sha256 = hashlib.sha256()
            
            for chunk in self.file.chunks():
                hash_sha256.update(chunk)
            
            self.result['file_hash'] = hash_sha256.hexdigest()
            
            self.file.seek(0)
            
        except Exception:
            pass
    
    def _extract_title(self) -> None:
        filename = self.file.name
        
        title = os.path.splitext(filename)[0]
        
        title = re.sub(r'[-_]+', ' ', title)
        title = re.sub(r'\s+', ' ', title).strip()
        title = title.title()
        
        if len(title) > 100:
            title = title[:100]
        
        self.result['title'] = title
    
    def _get_extension(self) -> str:
        return os.path.splitext(self.file.name)[1]
    
    def _get_mime_type(self) -> str:
        mime_type, _ = mimetypes.guess_type(self.file.name)
        if mime_type:
            return mime_type
        
        content_type = getattr(self.file, 'content_type', '')
        if content_type:
            return content_type
        
        return 'application/octet-stream'
    
    @staticmethod
    def get_file_icon(file_type: str) -> tuple:
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
        preview_types = ['pdf', 'image', 'word', 'excel', 'csv']
        return file_type in preview_types
    
    @staticmethod
    def get_supported_extensions() -> list:
        return list(SmartFileProcessor.FILE_TYPE_MAP.keys())


class FileTypeDetector:
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


def get_file_icon(file_type: str) -> tuple:
    return SmartFileProcessor.get_file_icon(file_type)


def can_preview(file_type: str) -> bool:
    return SmartFileProcessor.can_preview(file_type)


def get_supported_extensions() -> list:
    return list(SmartFileProcessor.FILE_TYPE_MAP.keys())
