import re
from typing import List, Dict, Any


class TemplateDetector:
    """Detects payroll template structure from Excel headers."""
    
    STANDARD_FIELDS = {
        "employee_name": ["employee name", "name", "employee", "full name", "fullname", "staff name"],
        "employee_id": ["employee id", "staff id", "employee_id", "staff_id", "emp id", "id number"],
        "basic_salary": ["basic salary", "basic", "base salary", "gross basic", "salary"],
        "housing_allowance": ["housing", "housing allowance", "housing allowance", "rent"],
        "transport_allowance": ["transport", "transport allowance", "transportation", "travel"],
        "meal_allowance": ["meal", "meal allowance", "meals", "lunch"],
        "other_allowance": ["other allowance", "other allowances", "allowance", "allowances", "misc"],
        "total_earnings": ["total earnings", "gross earnings", "total gross", "gross", "total pay"],
        "tax": ["tax", "paye", "income tax", "tax deduction"],
        "pension": ["pension", "pension contribution", "pencom"],
        "nhf": ["nhf", "national housing fund"],
        "loan_deduction": ["loan", "loan deduction", "loan repayment"],
        "other_deductions": ["other deductions", "other deduction", "misc deduction"],
        "total_deductions": ["total deductions", "total deduction", "deductions"],
        "net_pay": ["net pay", "net salary", "net", "take home", "amount paid"],
        "department": ["department", "dept", "division"],
        "position": ["position", "job title", "title", "role", "designation"],
        "bank_account": ["bank account", "account number", "bank", "account no"],
        "payment_date": ["payment date", "date paid", "paid date", "payment date"],
        "month": ["month"],
        "year": ["year"],
    }
    
    FIELD_TYPES = {
        "basic_salary": "decimal",
        "housing_allowance": "decimal",
        "transport_allowance": "decimal",
        "meal_allowance": "decimal",
        "other_allowance": "decimal",
        "total_earnings": "decimal",
        "tax": "decimal",
        "pension": "decimal",
        "nhf": "decimal",
        "loan_deduction": "decimal",
        "other_deductions": "decimal",
        "total_deductions": "decimal",
        "net_pay": "decimal",
        "employee_id": "text",
    }
    
    @classmethod
    def normalize_header(cls, header: str) -> str:
        """Normalize a header to lowercase and remove special characters."""
        return re.sub(r'[^a-z0-9\s]', '', header.lower().strip())
    
    @classmethod
    def detect_field_type(cls, header: str, sample_values: List[Any] = None) -> str:
        """Detect the field type from header name and sample values."""
        header_lower = cls.normalize_header(header)
        
        for field_key, type_name in cls.FIELD_TYPES.items():
            if field_key in header_lower:
                return type_name
        
        if sample_values:
            numeric_count = 0
            for val in sample_values[:10]:
                if val is not None:
                    try:
                        float(str(val).replace(',', ''))
                        numeric_count += 1
                    except:
                        pass
            
            if numeric_count / len(sample_values) > 0.7:
                return "decimal"
        
        return "text"
    
    @classmethod
    def detect_field_mapping(cls, headers: List[str]) -> Dict[str, str]:
        """Map headers to standard payroll field keys."""
        mapping = {}
        used_fields = set()
        
        for header in headers:
            header_normalized = cls.normalize_header(header)
            
            for field_key, field_names in cls.STANDARD_FIELDS.items():
                if field_key in used_fields:
                    continue
                
                for field_name in field_names:
                    if field_name in header_normalized:
                        mapping[header] = field_key
                        used_fields.add(field_key)
                        break
        
        return mapping
    
    @classmethod
    def generate_column_key(cls, header: str) -> str:
        """Generate a safe key from header name."""
        key = re.sub(r'[^a-zA-Z0-9\s]', '', header.strip())
        key = re.sub(r'\s+', '_', key.lower())
        key = re.sub(r'_+', '_', key)
        
        if key and key[0].isdigit():
            key = 'col_' + key
        
        return key[:50]
    
    @classmethod
    def detect_template(cls, headers: List[str], sample_data: List[Dict] = None) -> List[Dict[str, Any]]:
        """Detect template structure from Excel headers."""
        columns = []
        field_mapping = cls.detect_field_mapping(headers)
        
        for idx, header in enumerate(headers):
            key = field_mapping.get(header, cls.generate_column_key(header))
            field_type = cls.detect_field_type(header, [row.get(header) for row in (sample_data or [])])
            
            is_required = key in ["employee_name", "basic_salary", "net_pay"]
            
            columns.append({
                "key": key,
                "label": header,
                "type": field_type,
                "required": is_required,
                "order": idx,
            })
        
        return columns
    
    @classmethod
    def suggest_template_name(cls, headers: List[str]) -> str:
        """Suggest a template name based on headers."""
        headers_str = " ".join(headers).lower()
        
        if "payslip" in headers_str or "salary" in headers_str:
            return "Payroll Template"
        elif "attendance" in headers_str:
            return "Attendance Template"
        elif "bonus" in headers_str:
            return "Bonus Template"
        elif "loan" in headers_str:
            return "Loan Template"
        else:
            return "Custom Payroll Template"
