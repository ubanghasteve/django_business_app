import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from datetime import datetime, date
from decimal import Decimal
from typing import Dict, List, Any, Optional
import re


class SmartExcelParser:
    """Intelligently parses Excel files and extracts data from all sheets."""
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.workbook = None
        self.sheet_analysis = []
    
    def load(self) -> bool:
        """Load the Excel file."""
        try:
            self.workbook = openpyxl.load_workbook(self.file_path, data_only=True, read_only=False)
            return True
        except Exception as e:
            print(f"Error loading Excel file: {e}")
            return False
    
    def get_sheet_names(self) -> List[str]:
        """Get all sheet names."""
        if self.workbook:
            return self.workbook.sheetnames
        return []
    
    def _clean_cell_value(self, cell_value: Any) -> Any:
        """Clean and normalize cell values."""
        if cell_value is None:
            return None
        
        if isinstance(cell_value, (datetime, date)):
            if isinstance(cell_value, datetime):
                return cell_value.strftime("%Y-%m-%d %H:%M")
            return cell_value.strftime("%Y-%m-%d")
        
        if isinstance(cell_value, float):
            if cell_value == int(cell_value):
                return int(cell_value)
            return round(cell_value, 2)
        
        if isinstance(cell_value, Decimal):
            return float(cell_value)
        
        if isinstance(cell_value, str):
            cell_value = cell_value.strip()
            if cell_value == "":
                return None
            return cell_value
        
        return cell_value
    
    def _is_row_empty(self, row: tuple) -> bool:
        """Check if a row is completely empty."""
        return all(cell is None or str(cell).strip() == "" for cell in row)
    
    def _is_row_meaningful(self, row: tuple, min_non_empty: int = 2) -> bool:
        """Check if a row has meaningful data (not just empty or numbers)."""
        non_empty = 0
        for cell in row:
            if cell is not None and str(cell).strip() != "":
                non_empty += 1
        return non_empty >= min_non_empty
    
    def _get_sheet_stats(self, sheet_name: str) -> Dict[str, Any]:
        """Analyze a sheet and return statistics about it."""
        if not self.workbook:
            return {"name": sheet_name, "has_data": False}
        
        try:
            sheet = self.workbook[sheet_name]
            stats = {
                "name": sheet_name,
                "type": type(sheet).__name__,
                "max_row": sheet.max_row or 0,
                "max_column": sheet.max_column or 0,
                "total_cells": 0,
                "non_empty_cells": 0,
                "text_cells": 0,
                "number_cells": 0,
                "has_header": False,
                "estimated_data_rows": 0,
            }
            
            if stats["max_row"] == 0 or stats["max_column"] == 0:
                return stats
            
            stats["total_cells"] = stats["max_row"] * stats["max_column"]
            
            max_rows_to_scan = min(stats["max_row"], 50)
            for row_idx, row in enumerate(sheet.iter_rows(max_row=max_rows_to_scan, values_only=True)):
                for cell in row:
                    if cell is not None and str(cell).strip() != "":
                        stats["non_empty_cells"] += 1
                        if isinstance(cell, str):
                            stats["text_cells"] += 1
                        elif isinstance(cell, (int, float)):
                            stats["number_cells"] += 1
            
            text_density = stats["text_cells"] / max(stats["non_empty_cells"], 1)
            stats["has_header"] = text_density > 0.3 and stats["text_cells"] >= 2
            
            stats["estimated_data_rows"] = stats["max_row"] - 1 if stats["has_header"] else stats["max_row"]
            
            return stats
        except Exception as e:
            return {"name": sheet_name, "has_data": False, "error": str(e)}
    
    def _rank_sheets_for_payroll(self, stats_list: List[Dict]) -> List[Dict]:
        """Rank sheets by likelihood of containing payroll data."""
        payroll_keywords = [
            'payroll', 'salary', 'wage', 'employee', 'payslip', 'payslip',
            'pay', ' deduction', 'allowance', 'bonus', 'net', 'gross',
            'basic', 'housing', 'transport', 'tax', 'pension', 'nhf'
        ]
        
        ranked = []
        for stats in stats_list:
            score = 0
            name_lower = stats["name"].lower()
            
            for keyword in payroll_keywords:
                if keyword in name_lower:
                    score += 10
            
            score += stats.get("text_cells", 0) * 0.5
            score += stats.get("estimated_data_rows", 0) * 0.1
            
            if stats.get("has_header", False):
                score += 20
            
            if stats.get("non_empty_cells", 0) > 10:
                score += 5
            
            stats["payroll_score"] = score
            stats["is_chart_sheet"] = stats["type"] in ["Chartsheet", "Chart"]
            stats["is_empty"] = stats["non_empty_cells"] == 0 or stats["max_row"] == 0
            
            ranked.append(stats)
        
        ranked.sort(key=lambda x: x["payroll_score"], reverse=True)
        return ranked
    
    def _find_header_row(self, sheet) -> tuple:
        """Intelligently find the header row."""
        best_header_row = 0
        best_header = None
        best_score = 0
        
        max_rows_to_check = min(sheet.max_row or 10, 20)
        
        for row_idx, row in enumerate(sheet.iter_rows(max_row=max_rows_to_check, values_only=True)):
            if self._is_row_empty(row):
                continue
            
            score = 0
            text_headers = 0
            all_headers = []
            
            for cell in row:
                if cell is not None and str(cell).strip():
                    all_headers.append(str(cell).strip())
                    if isinstance(cell, str):
                        text_headers += 1
            
            if text_headers >= 2:
                score = text_headers * 10
                
                unique_ratio = len(set(all_headers)) / len(all_headers) if all_headers else 0
                score += unique_ratio * 20
                
                short_headers = sum(1 for h in all_headers if len(h) < 30)
                score += short_headers * 2
                
                header_keywords = ['name', 'id', 'amount', 'salary', 'date', 'employee', 'basic', 'allowance', 'deduction', 'net', 'gross', 'total']
                keyword_matches = sum(1 for h in all_headers if any(kw in h.lower() for kw in header_keywords))
                score += keyword_matches * 15
            
            if score > best_score:
                best_score = score
                best_header_row = row_idx
                best_header = row
        
        return best_header_row, best_header if best_header else []
    
    def parse_sheet(self, sheet_name: str) -> Dict[str, Any]:
        """Parse a single sheet and return headers and data."""
        if not self.workbook:
            return {"headers": [], "data": [], "row_count": 0, "sheet_name": sheet_name}
        
        try:
            sheet = self.workbook[sheet_name]
            
            stats = self._get_sheet_stats(sheet_name)
            if stats.get("is_empty", False) or stats.get("is_chart_sheet", False):
                return {
                    "headers": [],
                    "data": [],
                    "row_count": 0,
                    "sheet_name": sheet_name,
                    "is_empty": True,
                    "is_chart": stats.get("is_chart_sheet", False),
                    "message": "This sheet is empty or contains only charts."
                }
            
            headers = []
            data = []
            all_rows = list(sheet.iter_rows(values_only=True))
            
            if not all_rows:
                return {"headers": [], "data": [], "row_count": 0, "sheet_name": sheet_name}
            
            header_row_idx, header_row = self._find_header_row(sheet)
            
            headers = []
            for i, cell in enumerate(header_row):
                if cell is not None and str(cell).strip():
                    header_text = str(cell).strip()
                    headers.append(header_text)
                else:
                    headers.append(f"Column_{i+1}")
            
            headers = self._normalize_headers(headers)
            
            for row_idx, row in enumerate(all_rows):
                if row_idx <= header_row_idx:
                    continue
                
                if self._is_row_empty(row):
                    continue
                
                row_data = {}
                has_data = False
                
                for i, cell in enumerate(row):
                    if i < len(headers):
                        cleaned_value = self._clean_cell_value(cell)
                        row_data[headers[i]] = cleaned_value
                        if cleaned_value is not None and cleaned_value != "":
                            has_data = True
                
                if has_data:
                    data.append(row_data)
            
            return {
                "headers": headers,
                "data": data,
                "row_count": len(data),
                "sheet_name": sheet_name,
                "total_rows": len(all_rows),
                "header_row_index": header_row_idx,
                "is_primary": stats.get("payroll_score", 0) == max(s.get("payroll_score", 0) for s in self.sheet_analysis) if self.sheet_analysis else True
            }
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"headers": [], "data": [], "row_count": 0, "sheet_name": sheet_name, "error": str(e)}
    
    def _normalize_headers(self, headers: List[str]) -> List[str]:
        """Normalize headers to be unique and valid dict keys."""
        normalized = []
        seen = {}
        
        for header in headers:
            key = self._header_to_key(header)
            
            if key in seen:
                seen[key] += 1
                key = f"{key}_{seen[key]}"
            else:
                seen[key] = 0
            
            normalized.append(key)
        
        return normalized
    
    def _header_to_key(self, header: str) -> str:
        """Convert header text to a valid dict key."""
        if not header:
            return "unnamed"
        
        key = header.lower().strip()
        key = re.sub(r'[^a-z0-9\s]', '', key)
        key = '_'.join(key.split())
        
        if not key:
            return "unnamed"
        
        return key
    
    def parse_all_sheets(self) -> List[Dict[str, Any]]:
        """Parse all sheets in the workbook, ranked by importance."""
        result = []
        sheet_names = self.get_sheet_names()
        
        self.sheet_analysis = [self._get_sheet_stats(name) for name in sheet_names]
        ranked_sheets = self._rank_sheets_for_payroll(self.sheet_analysis)
        
        sheet_order = [s["name"] for s in ranked_sheets]
        
        for sheet_name in sheet_order:
            sheet_data = self.parse_sheet(sheet_name)
            result.append(sheet_data)
        
        return result
    
    def get_smart_summary(self) -> Dict[str, Any]:
        """Get a smart summary of the Excel file."""
        sheet_names = self.get_sheet_names()
        
        if not sheet_names:
            return {"total_sheets": 0, "message": "No sheets found"}
        
        self.sheet_analysis = [self._get_sheet_stats(name) for name in sheet_names]
        ranked_sheets = self._rank_sheets_for_payroll(self.sheet_analysis)
        
        data_sheets = [s for s in ranked_sheets if not s.get("is_empty") and not s.get("is_chart_sheet")]
        sheet_order = [s["name"] for s in ranked_sheets]
        
        return {
            "total_sheets": len(sheet_names),
            "data_sheets": len(data_sheets),
            "chart_sheets": len([s for s in ranked_sheets if s.get("is_chart_sheet")]),
            "empty_sheets": len([s for s in ranked_sheets if s.get("is_empty")]),
            "recommended_sheet": data_sheets[0]["name"] if data_sheets else None,
            "all_sheets": sheet_order,
            "sheet_info": ranked_sheets
        }
    
    def close(self):
        """Close the workbook."""
        if self.workbook:
            try:
                self.workbook.close()
            except:
                pass


def parse_excel_file(file_path: str) -> List[Dict[str, Any]]:
    """Parse an Excel file and return data from all sheets."""
    parser = SmartExcelParser(file_path)
    if parser.load():
        result = parser.parse_all_sheets()
        parser.close()
        return result
    return []
