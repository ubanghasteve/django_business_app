import os
import re
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

from django.core.files.uploadedfile import UploadedFile


class FileTypeDetector:
    MIME_TO_TYPE_MAP = {
        "application/pdf": "pdf",
        "application/vnd.ms-excel": "excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
        "application/vnd.ms-excel.sheet.macroEnabled.12": "excel",
        "application/vnd.oasis.opendocument.spreadsheet": "excel",
        "image/jpeg": "image",
        "image/png": "image",
        "image/gif": "image",
        "image/webp": "image",
        "image/svg+xml": "image",
        "application/msword": "word",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "word",
        "text/csv": "csv",
        "text/plain": "text",
        "application/zip": "zip",
        "application/x-zip-compressed": "zip",
    }

    EXTENSION_TO_TYPE_MAP = {
        ".pdf": "pdf",
        ".xls": "excel",
        ".xlsx": "excel",
        ".xlsm": "excel",
        ".xlsb": "excel",
        ".ods": "excel",
        ".jpg": "image",
        ".jpeg": "image",
        ".png": "image",
        ".gif": "image",
        ".webp": "image",
        ".svg": "image",
        ".doc": "word",
        ".docx": "word",
        ".csv": "csv",
        ".txt": "text",
        ".zip": "zip",
    }

    EXTENSION_TO_MIME_MAP = {
        ".pdf": "application/pdf",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
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
        ext = os.path.splitext(filename)[1].lower()
        if ext in cls.EXTENSION_TO_MIME_MAP:
            return cls.EXTENSION_TO_MIME_MAP[ext]
        return "application/octet-stream"

    @classmethod
    def is_previewable(cls, file_type: str) -> bool:
        return file_type in ["image", "pdf"]

    @classmethod
    def get_icon(cls, file_type: str) -> str:
        icons = {
            "pdf": "fa-file-pdf",
            "excel": "fa-file-excel",
            "image": "fa-file-image",
            "word": "fa-file-word",
            "csv": "fa-file-csv",
            "text": "fa-file-alt",
            "zip": "fa-file-archive",
            "other": "fa-file",
        }
        return icons.get(file_type, "fa-file")

    @classmethod
    def get_color(cls, file_type: str) -> str:
        colors = {
            "pdf": "#e74c3c",
            "excel": "#27ae60",
            "image": "#3498db",
            "word": "#2980b9",
            "csv": "#16a085",
            "text": "#7f8c8d",
            "zip": "#f39c12",
            "other": "#95a5a6",
        }
        return colors.get(file_type, "#95a5a6")


class FileNameParser:
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

    PATTERNS = [
        (r"(\d{4})[_\-](\d{1,2})", "year_month"),
        (r"(\d{1,2})[_\-](\d{4})", "month_year"),
        (r"(\d{4})(\d{2})", "year_month_compact"),
        (r"payslip[_\-]?(\w+)[_\-]?(\d{4})", "payslip_month_year"),
        (r"payslip[_\-]?(\d{4})[_\-]?(\w+)", "payslip_year_month"),
        (r"report[_\-]?(\w+)[_\-]?(\d{4})", "report_month_year"),
        (r"salary[_\-]?(\d{4})[_\-]?(\d{1,2})", "salary_year_month"),
        (r"(\d{4})[_\-]?payroll", "year_payroll"),
    ]

    @classmethod
    def parse_filename(cls, filename: str) -> Dict[str, Any]:
        result = {
            "month": None,
            "year": None,
            "employee_name": None,
            "category_hint": None,
        }

        base_name = os.path.splitext(filename)[0].lower()

        for pattern, pattern_type in cls.PATTERNS:
            match = re.search(pattern, base_name)
            if match:
                if pattern_type == "year_month":
                    year, month = int(match.group(1)), int(match.group(2))
                    if 1 <= month <= 12 and 2000 <= year <= 2100:
                        result["year"] = year
                        result["month"] = month
                        break
                elif pattern_type == "month_year":
                    month, year = int(match.group(1)), int(match.group(2))
                    if 1 <= month <= 12 and 2000 <= year <= 2100:
                        result["year"] = year
                        result["month"] = month
                        break
                elif pattern_type == "year_month_compact":
                    year, month = int(match.group(1)[:4]), int(match.group(1)[4:6])
                    if 1 <= month <= 12:
                        result["year"] = year
                        result["month"] = month
                        break
                elif pattern_type in ("payslip_month_year", "report_month_year", "salary_year_month"):
                    month_str = match.group(1).lower()
                    year = int(match.group(2))
                    if month_str in cls.MONTH_NAMES:
                        result["month"] = cls.MONTH_NAMES[month_str]
                        result["year"] = year
                        result["category_hint"] = "payslip" if "payslip" in pattern_type else "report"
                        break
                elif pattern_type == "payslip_year_month":
                    year = int(match.group(1))
                    month_str = match.group(2).lower()
                    if month_str in cls.MONTH_NAMES:
                        result["month"] = cls.MONTH_NAMES[month_str]
                        result["year"] = year
                        result["category_hint"] = "payslip"
                        break
                elif pattern_type == "year_payroll":
                    result["year"] = int(match.group(1))
                    result["category_hint"] = "report"
                    break

        if "payslip" in base_name:
            result["category_hint"] = "payslip"
        elif "report" in base_name:
            result["category_hint"] = "report"
        elif "contract" in base_name:
            result["category_hint"] = "contract"
        elif "tax" in base_name:
            result["category_hint"] = "tax_document"
        elif "pension" in base_name:
            result["category_hint"] = "pension"
        elif "bank" in base_name:
            result["category_hint"] = "bank_details"
        elif "loan" in base_name:
            result["category_hint"] = "loan_document"
        elif "bonus" in base_name:
            result["category_hint"] = "bonus"
        elif "advance" in base_name:
            result["category_hint"] = "advance"

        name_parts = re.split(r"[_\-.\s]+", base_name)
        employee_patterns = [p for p in name_parts if len(p) > 3 and not p.isdigit()]
        if employee_patterns:
            result["employee_name"] = " ".join(employee_patterns[:3]).title()

        return result

    @classmethod
    def generate_title(cls, filename: str, month: int = None, year: int = None) -> str:
        base_name = os.path.splitext(filename)[0]
        title = base_name.replace("_", " ").replace("-", " ").title()

        if month and year:
            try:
                from datetime import date
                month_name = date(year, month, 1).strftime("%B")
                title = f"{title} - {month_name} {year}"
            except:
                pass
        elif year:
            title = f"{title} - {year}"

        return title


class FileProcessor:
    MAX_FILE_SIZE = 50 * 1024 * 1024
    ALLOWED_EXTENSIONS = {
        ".pdf", ".xls", ".xlsx", ".xlsm", ".xlsb",
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
        ".doc", ".docx", ".csv", ".txt", ".zip",
    }

    @classmethod
    def validate_file(cls, file: UploadedFile) -> Tuple[bool, str]:
        if file.size > cls.MAX_FILE_SIZE:
            max_mb = cls.MAX_FILE_SIZE / (1024 * 1024)
            return False, f"File size exceeds {max_mb}MB limit"

        ext = os.path.splitext(file.name)[1].lower()
        if ext not in cls.ALLOWED_EXTENSIONS:
            return False, f"File type {ext} is not allowed"

        return True, ""

    @classmethod
    def process_upload(
        cls,
        file: UploadedFile,
        company_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
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

        category_hint = parsed.get("category_hint")

        return {
            "file": file,
            "original_filename": file.name,
            "file_type": file_type,
            "mime_type": mime_type,
            "file_size": file.size,
            "title": title,
            "month": parsed.get("month"),
            "year": parsed.get("year"),
            "category_hint": category_hint,
            "employee_name_hint": parsed.get("employee_name"),
        }

    @classmethod
    def get_upload_path(cls, company_id: int, filename: str, year: int = None, month: int = None) -> str:
        if year and month:
            return f"payroll/files/{company_id}/{year}/{month:02d}/{filename}"
        now = datetime.now()
        return f"payroll/files/{company_id}/{now.year}/{now.month:02d}/{filename}"


def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def get_file_icon(file_type: str) -> Tuple[str, str]:
    icons = {
        "pdf": ("fa-file-pdf", "#e74c3c"),
        "excel": ("fa-file-excel", "#27ae60"),
        "image": ("fa-file-image", "#3498db"),
        "word": ("fa-file-word", "#2980b9"),
        "csv": ("fa-file-csv", "#16a085"),
        "text": ("fa-file-alt", "#7f8c8d"),
        "zip": ("fa-file-archive", "#f39c12"),
        "other": ("fa-file", "#95a5a6"),
    }
    return icons.get(file_type, ("fa-file", "#95a5a6"))
