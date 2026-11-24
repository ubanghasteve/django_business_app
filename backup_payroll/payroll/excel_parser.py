import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple, Any
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


class ExcelParser:
    """
    Smart Excel parser that handles multi-sheet Excel files and extracts payroll data.
    Automatically detects columns, periods, and employee information.
    """

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

    PAYROLL_COLUMN_PATTERNS = {
        "employee_name": [
            r"name", r"employee\s*name", r"staff\s*name", r"full\s*name",
            r"employee", r"staff", r"beneficiary"
        ],
        "employee_id": [
            r"employee\s*id", r"staff\s*id", r"emp\s*id", r"emp\s*no",
            r"staff\s*no", r"personnel\s*no", r"id\s*no"
        ],
        "basic_salary": [
            r"basic", r"basic\s*salary", r"gross\s*salary", r"salary",
            r"monthly\s*salary", r"consolidated\s*salary"
        ],
        "allowances": [
            r"allowance", r"allowances", r"housing", r"transport",
            r"meal", r"utility", r"other\s*allowance"
        ],
        "bonuses": [
            r"bonus", r"bonuses", r"13th\s*salary", r"leave\s*allowance",
            r"end\s*of\s*year"
        ],
        "overtime": [
            r"overtime", r"overtime\s*pay", r"ot"
        ],
        "gross_salary": [
            r"gross", r"gross\s*pay", r"total\s*earnings", r"total\s*pay",
            r"gross\s*salary", r"total\s*salary"
        ],
        "pension": [
            r"pension", r"pension\s*contribution", r"retirement", r"pf"
        ],
        "nhf": [
            r"nhf", r"national\s*housing", r"housing\s*fund"
        ],
        "tax": [
            r"tax", r"paye", r"withholding\s*tax", r"income\s*tax", r"tax\s*deduction"
        ],
        "loan_deduction": [
            r"loan", r"loan\s*repayment", r"loan\s*deduction"
        ],
        "other_deductions": [
            r"other\s*deduction", r"other\s*deductions", r"misc", r"miscellaneous"
        ],
        "net_salary": [
            r"net", r"net\s*pay", r"net\s*salary", r"take\s*home", r"amount\s*paid"
        ],
    }

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.workbook = None
        self.sheets = []
        self.errors = []

    def load(self) -> bool:
        try:
            self.workbook = load_workbook(self.file_path, data_only=True)
            self.sheets = self.workbook.sheetnames
            return True
        except InvalidFileException as e:
            self.errors.append(f"Invalid Excel file: {str(e)}")
            return False
        except Exception as e:
            self.errors.append(f"Error loading Excel file: {str(e)}")
            return False

    def get_sheet_info(self) -> List[Dict[str, Any]]:
        """Get information about all sheets in the workbook."""
        if not self.workbook:
            return []
        
        info = []
        for idx, sheet_name in enumerate(self.sheets):
            sheet = self.workbook[sheet_name]
            info.append({
                "index": idx,
                "name": sheet_name,
                "rows": sheet.max_row,
                "columns": sheet.max_column,
            })
        return info

    def detect_columns(self, sheet_name: str) -> Dict[str, int]:
        """Detect payroll-related columns from sheet headers."""
        if not self.workbook:
            return {}
        
        sheet = self.workbook[sheet_name]
        headers = {}
        
        for row_idx in range(1, min(6, sheet.max_row + 1)):
            for col_idx in range(1, sheet.max_column + 1):
                cell_value = sheet.cell(row=row_idx, column=col_idx).value
                if cell_value:
                    cell_str = str(cell_value).lower().strip()
                    col_letter = self._get_column_letter(col_idx)
                    
                    for field, patterns in self.PAYROLL_COLUMN_PATTERNS.items():
                        if field not in headers:
                            for pattern in patterns:
                                if re.search(pattern, cell_str):
                                    headers[field] = col_idx
                                    break
                    headers[col_letter] = cell_value
        
        return headers

    def parse_sheet(self, sheet_name: str, start_row: int = 1) -> List[Dict[str, Any]]:
        """Parse a single sheet and extract all rows."""
        if not self.workbook:
            return []
        
        sheet = self.workbook[sheet_name]
        if sheet.max_row < 2:
            return []
        
        headers = self._get_headers(sheet, start_row)
        column_map = self._map_columns(headers)
        
        rows = []
        for row_idx in range(start_row + 1, sheet.max_row + 1):
            row_data = {}
            is_empty = True
            
            for col_idx in range(1, sheet.max_column + 1):
                cell_value = sheet.cell(row=row_idx, column=col_idx).value
                col_letter = self._get_column_letter(col_idx)
                
                if cell_value is not None and str(cell_value).strip():
                    is_empty = False
                
                row_data[col_letter] = cell_value
                
                for field, col_num in column_map.items():
                    if col_num == col_idx:
                        row_data[field] = cell_value
            
            if not is_empty:
                row_data["_row_number"] = row_idx
                row_data["_detected_period"] = self._detect_period(row_data)
                rows.append(row_data)
        
        return rows

    def parse_all_sheets(self) -> Dict[str, List[Dict[str, Any]]]:
        """Parse all sheets in the workbook."""
        if not self.workbook:
            return {}
        
        result = {}
        for sheet_name in self.sheets:
            rows = self.parse_sheet(sheet_name)
            if rows:
                result[sheet_name] = rows
        return result

    def extract_payroll_records(self, sheet_name: str = None) -> List[Dict[str, Any]]:
        """Extract payroll records with structured data."""
        if sheet_name:
            sheets_data = {sheet_name: self.parse_sheet(sheet_name)}
        else:
            sheets_data = self.parse_all_sheets()
        
        records = []
        for sheet_name, rows in sheets_data.items():
            for row in rows:
                record = {
                    "sheet_name": sheet_name,
                    "row_number": row.get("_row_number", 0),
                    "period": row.get("_detected_period"),
                    "employee_name": self._clean_text(row.get("employee_name", "")),
                    "employee_id": str(row.get("employee_id", "")).strip(),
                    "basic_salary": self._parse_number(row.get("basic_salary")),
                    "allowances": self._parse_number(row.get("allowances")),
                    "bonuses": self._parse_number(row.get("bonuses")),
                    "overtime": self._parse_number(row.get("overtime")),
                    "gross_salary": self._parse_number(row.get("gross_salary")),
                    "pension": self._parse_number(row.get("pension")),
                    "nhf": self._parse_number(row.get("nhf")),
                    "tax": self._parse_number(row.get("tax")),
                    "loan_deduction": self._parse_number(row.get("loan_deduction")),
                    "other_deductions": self._parse_number(row.get("other_deductions")),
                    "net_salary": self._parse_number(row.get("net_salary")),
                    "raw_data": row,
                }
                
                if record["employee_name"] or record["employee_id"]:
                    records.append(record)
        
        return records

    def _get_headers(self, sheet, start_row: int) -> List[Tuple[int, Any]]:
        headers = []
        for col_idx in range(1, sheet.max_column + 1):
            cell_value = sheet.cell(row=start_row, column=col_idx).value
            if cell_value:
                headers.append((col_idx, str(cell_value).strip()))
            else:
                headers.append((col_idx, f"Column_{col_idx}"))
        return headers

    def _map_columns(self, headers: List[Tuple[int, Any]]) -> Dict[str, int]:
        column_map = {}
        
        for col_idx, header in headers:
            header_lower = header.lower()
            
            for field, patterns in self.PAYROLL_COLUMN_PATTERNS.items():
                if field not in column_map:
                    for pattern in patterns:
                        if re.search(pattern, header_lower):
                            column_map[field] = col_idx
                            break
        
        return column_map

    def _detect_period(self, row_data: Dict) -> Optional[Dict]:
        for key, value in row_data.items():
            if not isinstance(value, str):
                continue
            
            value_lower = value.lower()
            
            year_match = re.search(r"20\d{2}", value)
            month_match = None
            for month_name, month_num in self.MONTH_NAMES.items():
                if month_name in value_lower:
                    month_match = month_num
                    break
            
            if year_match and month_match:
                return {"month": month_match, "year": int(year_match.group())}
            
            if year_match:
                compact_match = re.search(r"(0?[1-9]|1[0-2])20\d{2}", value)
                if compact_match:
                    compact = compact_match.group()
                    month = int(compact[:2] if compact[1].isdigit() else compact[0])
                    year = int(compact[-4:])
                    return {"month": month, "year": year}
        
        return None

    def _parse_number(self, value: Any) -> Optional[Decimal]:
        if value is None:
            return None
        
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        
        value_str = str(value).strip()
        value_str = re.sub(r"[,\s]", "", value_str)
        value_str = re.sub(r"[^\d.\-]", "", value_str)
        
        if not value_str or value_str in (".", "-", "-.", "."):
            return None
        
        try:
            return Decimal(value_str)
        except (InvalidOperation, ValueError):
            return None

    def _clean_text(self, value: Any) -> str:
        if not value:
            return ""
        return str(value).strip()

    def _get_column_letter(self, col_idx: int) -> str:
        result = ""
        while col_idx > 0:
            col_idx, remainder = divmod(col_idx - 1, 26)
            result = chr(65 + remainder) + result
        return result


def parse_excel_file(file_path: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Parse an Excel file and return structured data.
    Returns (success, result_dict) where result_dict contains sheets and records.
    """
    parser = ExcelParser(file_path)
    
    if not parser.load():
        return False, {"errors": parser.errors}
    
    sheet_info = parser.get_sheet_info()
    all_records = parser.extract_payroll_records()
    
    return True, {
        "sheets": sheet_info,
        "records": all_records,
        "total_rows": sum(len(records) for records in parser.parse_all_sheets().values()),
        "errors": parser.errors,
    }


def get_default_headers_for_template() -> List[str]:
    """Get default column headers for payroll Excel template."""
    return [
        "Employee Name", "Employee ID", "Basic Salary", "Allowances",
        "Bonuses", "Overtime", "Gross Salary", "Pension", "NHF",
        "Tax", "Loan Deduction", "Other Deductions", "Net Salary"
    ]
