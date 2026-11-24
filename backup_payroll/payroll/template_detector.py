import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Any, Tuple
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


class TemplateDetector:
    """
    Smart detector that studies Excel file structures and creates templates.
    It analyzes patterns in column names and data to generate dynamic forms.
    """

    STANDARD_FIELDS = {
        "employee_name": {
            "patterns": [r"name", r"employee\s*name", r"staff\s*name", r"full\s*name", 
                        r"beneficiary", r"worker"],
            "type": "text",
            "category": "employee_info",
            "required": True,
            "label": "Employee Name",
        },
        "employee_id": {
            "patterns": [r"employee\s*id", r"staff\s*id", r"emp\s*id", r"emp\s*no",
                        r"staff\s*no", r"personnel\s*no", r"id\s*no"],
            "type": "text",
            "category": "employee_info",
            "required": False,
            "label": "Employee ID",
        },
        "email": {
            "patterns": [r"email", r"e-mail", r"mail"],
            "type": "text",
            "category": "employee_info",
            "required": False,
            "label": "Email",
        },
        "department": {
            "patterns": [r"department", r"dept", r"unit", r"section", r"division"],
            "type": "text",
            "category": "employee_info",
            "required": False,
            "label": "Department",
        },
        "position": {
            "patterns": [r"position", r"job\s*title", r"role", r"designation", r"grade"],
            "type": "text",
            "category": "employee_info",
            "required": False,
            "label": "Position",
        },
        "basic_salary": {
            "patterns": [r"basic", r"basic\s*salary", r"consolidated\s*salary"],
            "type": "decimal",
            "category": "earnings",
            "required": True,
            "label": "Basic Salary",
            "is_currency": True,
        },
        "housing": {
            "patterns": [r"housing", r"rent\s*allowance", r"housing\s*allowance"],
            "type": "decimal",
            "category": "earnings",
            "required": False,
            "label": "Housing Allowance",
            "is_currency": True,
        },
        "transport": {
            "patterns": [r"transport", r"transport\s*allowance", r"transportation"],
            "type": "decimal",
            "category": "earnings",
            "required": False,
            "label": "Transport Allowance",
            "is_currency": True,
        },
        "meal_allowance": {
            "patterns": [r"meal", r"meal\s*allowance", r"meal\s*subsidy"],
            "type": "decimal",
            "category": "earnings",
            "required": False,
            "label": "Meal Allowance",
            "is_currency": True,
        },
        "utility_allowance": {
            "patterns": [r"utility", r"utility\s*allowance", r"utilities"],
            "type": "decimal",
            "category": "earnings",
            "required": False,
            "label": "Utility Allowance",
            "is_currency": True,
        },
        "other_allowance": {
            "patterns": [r"other\s*allowance", r"other\s*earning", r"misc", r"miscellaneous\s*allowance"],
            "type": "decimal",
            "category": "earnings",
            "required": False,
            "label": "Other Allowance",
            "is_currency": True,
        },
        "overtime": {
            "patterns": [r"overtime", r"overtime\s*pay", r"ot", r"extra\s*hours"],
            "type": "decimal",
            "category": "earnings",
            "required": False,
            "label": "Overtime",
            "is_currency": True,
        },
        "bonus": {
            "patterns": [r"bonus", r"13th\s*salary", r"leave\s*allowance", r"end\s*of\s*year"],
            "type": "decimal",
            "category": "earnings",
            "required": False,
            "label": "Bonus",
            "is_currency": True,
        },
        "gross_salary": {
            "patterns": [r"gross", r"gross\s*pay", r"total\s*earning", r"total\s*pay", 
                        r"gross\s*salary", r"total\s*salary"],
            "type": "decimal",
            "category": "earnings",
            "required": True,
            "label": "Gross Salary",
            "is_currency": True,
            "is_calculated": True,
        },
        "pension": {
            "patterns": [r"pension", r"pension\s*contribution", r"retirement", r"pf", r"provident\s*fund"],
            "type": "decimal",
            "category": "deductions",
            "required": False,
            "label": "Pension (Employee)",
            "is_currency": True,
        },
        "pension_employer": {
            "patterns": [r"employer\s*pension", r"employer\s*pf", r"pens\s*employer"],
            "type": "decimal",
            "category": "deductions",
            "required": False,
            "label": "Pension (Employer)",
            "is_currency": True,
        },
        "nhf": {
            "patterns": [r"nhf", r"national\s*housing", r"housing\s*fund", r"n_h_f"],
            "type": "decimal",
            "category": "deductions",
            "required": False,
            "label": "NHF",
            "is_currency": True,
        },
        "tax": {
            "patterns": [r"tax", r"paye", r"withholding\s*tax", r"income\s*tax", 
                        r"tax\s*deduction", r"taxes"],
            "type": "decimal",
            "category": "deductions",
            "required": False,
            "label": "Tax (PAYE)",
            "is_currency": True,
        },
        "loan": {
            "patterns": [r"loan", r"loan\s*repayment", r"loan\s*deduction"],
            "type": "decimal",
            "category": "deductions",
            "required": False,
            "label": "Loan Repayment",
            "is_currency": True,
        },
        "advance": {
            "patterns": [r"advance", r"salary\s*advance", r"savings"],
            "type": "decimal",
            "category": "deductions",
            "required": False,
            "label": "Salary Advance",
            "is_currency": True,
        },
        "union_dues": {
            "patterns": [r"union", r"union\s*due", r"association\s*due", r"levy"],
            "type": "decimal",
            "category": "deductions",
            "required": False,
            "label": "Union Dues",
            "is_currency": True,
        },
        "other_deduction": {
            "patterns": [r"other\s*deduction", r"misc\s*deduction", r"adjustment"],
            "type": "decimal",
            "category": "deductions",
            "required": False,
            "label": "Other Deductions",
            "is_currency": True,
        },
        "total_deductions": {
            "patterns": [r"total\s*deduction", r"total\s*deductions", r"all\s*deductions"],
            "type": "decimal",
            "category": "deductions",
            "required": False,
            "label": "Total Deductions",
            "is_currency": True,
            "is_calculated": True,
        },
        "net_salary": {
            "patterns": [r"net", r"net\s*pay", r"net\s*salary", r"take\s*home", 
                        r"amount\s*paid", r"net\s*amount"],
            "type": "decimal",
            "category": "net_pay",
            "required": True,
            "label": "Net Salary",
            "is_currency": True,
            "is_calculated": True,
        },
        "bank_name": {
            "patterns": [r"bank\s*name", r"bank"],
            "type": "text",
            "category": "employee_info",
            "required": False,
            "label": "Bank Name",
        },
        "account_number": {
            "patterns": [r"account\s*no", r"account\s*number", r"acct\s*no", r"acct\s*number"],
            "type": "text",
            "category": "employee_info",
            "required": False,
            "label": "Account Number",
        },
    }

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.workbook = None
        self.sheets = []
        self.detected_columns = []
        self.custom_columns = []

    def load(self) -> bool:
        try:
            self.workbook = load_workbook(self.file_path, data_only=True)
            self.sheets = self.workbook.sheetnames
            return True
        except InvalidFileException:
            return False
        except Exception:
            return False

    def detect_template(self) -> Dict[str, Any]:
        """Analyze the Excel file and create a template configuration."""
        if not self.workbook:
            return {"error": "File not loaded"}

        all_columns = []
        
        for sheet_name in self.sheets:
            sheet = self.workbook[sheet_name]
            columns = self._analyze_sheet(sheet, sheet_name)
            all_columns.extend(columns)

        columns_config = self._build_columns_config(all_columns)
        
        sample_data = self._extract_sample_data(all_columns[:10] if all_columns else [])

        template = {
            "columns": columns_config,
            "column_order": [col["key"] for col in columns_config],
            "sample_data": sample_data,
            "total_columns": len(columns_config),
            "employee_columns": [c for c in columns_config if c["category"] == "employee_info"],
            "earnings_columns": [c for c in columns_config if c["category"] == "earnings"],
            "deductions_columns": [c for c in columns_config if c["category"] == "deductions"],
            "net_pay_columns": [c for c in columns_config if c["category"] == "net_pay"],
        }
        
        return template

    def _analyze_sheet(self, sheet, sheet_name: str) -> List[Dict]:
        """Analyze a single sheet and detect columns."""
        columns = []
        
        if sheet.max_row < 2:
            return columns

        for col_idx in range(1, min(sheet.max_column + 1, 50)):
            header_value = sheet.cell(row=1, column=col_idx).value
            
            if header_value is None:
                continue
            
            header_str = str(header_value).strip()
            col_letter = self._get_column_letter(col_idx)
            
            sample_values = []
            for row_idx in range(2, min(sheet.max_row + 1, 11)):
                val = sheet.cell(row=row_idx, column=col_idx).value
                if val is not None:
                    sample_values.append(val)

            column_info = self._detect_column_type(header_str, sample_values, col_letter)
            column_info["sheet"] = sheet_name
            column_info["column_index"] = col_idx
            
            columns.append(column_info)
        
        return columns

    def _detect_column_type(self, header: str, sample_values: List, col_letter: str) -> Dict:
        """Detect the type and category of a column based on header and sample data."""
        header_lower = header.lower()
        
        for field_key, field_config in self.STANDARD_FIELDS.items():
            for pattern in field_config["patterns"]:
                if re.search(pattern, header_lower):
                    return {
                        "key": field_key,
                        "header": header,
                        "col_letter": col_letter,
                        "type": field_config["type"],
                        "category": field_config["category"],
                        "label": field_config.get("label", header),
                        "required": field_config.get("required", False),
                        "is_currency": field_config.get("is_currency", False),
                        "is_calculated": field_config.get("is_calculated", False),
                        "is_standard": True,
                        "sample_values": sample_values[:5],
                    }
        
        detected_type = self._infer_type_from_data(sample_values)
        
        return {
            "key": f"custom_{col_letter.lower()}",
            "header": header,
            "col_letter": col_letter,
            "type": detected_type,
            "category": "custom",
            "label": header,
            "required": False,
            "is_currency": detected_type == "decimal",
            "is_calculated": False,
            "is_standard": False,
            "sample_values": sample_values[:5],
        }

    def _infer_type_from_data(self, sample_values: List) -> str:
        """Infer the data type from sample values."""
        if not sample_values:
            return "text"
        
        decimal_count = 0
        text_count = 0
        date_count = 0
        
        for val in sample_values:
            val_str = str(val).strip()
            
            if self._is_date(val_str):
                date_count += 1
            elif self._is_decimal(val_str):
                decimal_count += 1
            else:
                text_count += 1
        
        total = len(sample_values)
        
        if date_count / total > 0.5:
            return "date"
        elif decimal_count / total > 0.5:
            return "decimal"
        elif text_count / total > 0.5:
            return "text"
        
        return "text"

    def _is_date(self, val: str) -> bool:
        date_patterns = [
            r"\d{1,2}/\d{1,2}/\d{2,4}",
            r"\d{1,2}-\d{1,2}-\d{2,4}",
            r"\d{4}-\d{2}-\d{2}",
        ]
        for pattern in date_patterns:
            if re.match(pattern, val):
                return True
        return False

    def _is_decimal(self, val: str) -> bool:
        cleaned = re.sub(r"[,\s$]", "", val)
        try:
            Decimal(cleaned)
            return True
        except (InvalidOperation, ValueError):
            return False

    def _build_columns_config(self, columns: List[Dict]) -> List[Dict]:
        """Build the final column configuration with ordering."""
        config = []
        
        priority_order = [
            "employee_name", "employee_id", "email", "department", "position",
            "bank_name", "account_number",
            "basic_salary", "housing", "transport", "meal_allowance", 
            "utility_allowance", "other_allowance", "overtime", "bonus", "gross_salary",
            "pension", "pension_employer", "nhf", "tax", "loan", "advance",
            "union_dues", "other_deduction", "total_deductions",
            "net_salary",
        ]
        
        standard_cols = [c for c in columns if c.get("is_standard")]
        custom_cols = [c for c in columns if not c.get("is_standard")]
        
        for key in priority_order:
            for col in standard_cols:
                if col["key"] == key:
                    config.append(col)
                    standard_cols.remove(col)
                    break
        
        config.extend(standard_cols)
        config.extend(custom_cols)
        
        return config

    def _extract_sample_data(self, columns: List[Dict], max_rows: int = 3) -> List[Dict]:
        """Extract sample data rows from the spreadsheet."""
        if not self.workbook or not columns:
            return []
        
        sheet = self.workbook[self.sheets[0]]
        sample_rows = []
        
        for row_idx in range(2, min(sheet.max_row + 1, max_rows + 2)):
            row_data = {}
            is_empty = True
            
            for col in columns:
                col_idx = col["column_index"]
                val = sheet.cell(row=row_idx, column=col_idx).value
                row_data[col["key"]] = val
                if val is not None and str(val).strip():
                    is_empty = False
            
            if not is_empty:
                sample_rows.append(row_data)
        
        return sample_rows

    def _get_column_letter(self, col_idx: int) -> str:
        result = ""
        while col_idx > 0:
            col_idx, remainder = divmod(col_idx - 1, 26)
            result = chr(65 + remainder) + result
        return result


def create_template_from_excel(file_path: str, company_id: int, user_id: int, 
                                template_name: str = None) -> Tuple[bool, Dict]:
    """
    Create a payroll template from an Excel file.
    Returns (success, result_dict) where result_dict contains template config.
    """
    detector = TemplateDetector(file_path)
    
    if not detector.load():
        return False, {"error": "Failed to load Excel file"}
    
    template_data = detector.detect_template()
    
    if "error" in template_data:
        return False, template_data
    
    template_data["name"] = template_name or f"Template from {detector.sheets[0]}"
    template_data["company_id"] = company_id
    template_data["user_id"] = user_id
    template_data["source_sheets"] = detector.sheets
    
    return True, template_data


def generate_form_fields(columns: List[Dict]) -> List[Dict]:
    """Generate form field configuration from column definitions."""
    fields = []
    
    for col in columns:
        field = {
            "name": col["key"],
            "label": col["label"],
            "type": col["type"],
            "required": col.get("required", False),
            "is_currency": col.get("is_currency", False),
            "category": col.get("category", "custom"),
        }
        
        if col["type"] == "decimal":
            field["widget_type"] = "number"
            field["step"] = "0.01"
        elif col["type"] == "integer":
            field["widget_type"] = "number"
            field["step"] = "1"
        elif col["type"] == "date":
            field["widget_type"] = "date"
        else:
            field["widget_type"] = "text"
        
        fields.append(field)
    
    return fields
