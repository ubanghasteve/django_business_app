# -*- coding: utf-8 -*-
"""
Advanced Table Extraction Module - Multi-engine PDF table extraction.

This module provides unified table extraction from PDFs using multiple engines:
- Tabula-py: Java-based table extraction (most accurate for bordered tables)
- Camelot-py: Python table extraction with lattice and stream modes
- PDFPlumber: Python-native table extraction (already used, enhanced here)

Usage:
    from apps.extraction.table_extractor import TableExtractor
    
    # Extract all tables from PDF
    tables = TableExtractor.extract_all_tables(pdf_path)
    
    # Extract with specific engine
    tables = TableExtractor.extract_with_tabula(pdf_path)
    tables = TableExtractor.extract_with_camelot(pdf_path, flavor='lattice')
    
    # Best quality extraction (tries all engines)
    tables = TableExtractor.extract_best_tables(pdf_path)
"""
import os
import io
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TableExtractionEngine(Enum):
    """Available table extraction engines."""
    TABULA = "tabula"
    CAMELOT = "camelot"
    PDFPLUMBER = "pdfplumber"


@dataclass
class TableExtractionResult:
    """Standardized table extraction result from any engine."""
    tables: List[List[List[str]]]
    engine: str
    page_count: int
    table_count: int
    error: Optional[str] = None
    extraction_time: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            'tables': self.tables,
            'engine': self.engine,
            'page_count': self.page_count,
            'table_count': self.table_count,
            'error': self.error,
            'extraction_time': self.extraction_time,
        }


class TableExtractor:
    """
    Multi-engine table extraction with automatic engine selection.
    
    Engines are tried in order of accuracy and the combined result is returned.
    """
    
    @classmethod
    def extract_with_tabula(cls, pdf_path_or_file, 
                           pages: str = 'all',
                           pandas_options: Dict = None) -> TableExtractionResult:
        """
        Extract tables using Tabula-py (Java-based, most accurate for bordered tables).
        
        Args:
            pdf_path_or_file: Path to PDF or file-like object
            pages: Pages to extract from ('all' or '1,2,3' format)
            pandas_options: Options to pass to pandas DataFrame
            
        Returns:
            TableExtractionResult with tables and metadata
        """
        import time
        start_time = time.time()
        
        try:
            from tabula import read_pdf
            import pandas as pd
        except ImportError as e:
            logger.error(f"Tabula-py not available: {e}")
            return TableExtractionResult(
                tables=[],
                engine='tabula',
                page_count=0,
                table_count=0,
                error=f"Tabula-py not installed: {e}"
            )
        
        try:
            logger.info(f"Extracting tables with Tabula from PDF...")
            
            # Convert file object to path if needed
            pdf_path = None
            if hasattr(pdf_path_or_file, 'read'):
                pdf_path_or_file.seek(0)
                # Save to temp file for tabula
                import tempfile
                temp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
                temp.write(pdf_path_or_file.read())
                temp.close()
                pdf_path = temp.name
            else:
                pdf_path = pdf_path_or_file
            
            pandas_options = pandas_options or {}
            
            # Read tables from PDF
            dfs = read_pdf(
                pdf_path,
                pages=pages,
                pandas_options=pandas_options,
                multiple_tables=True
            )
            
            # Clean up temp file
            if hasattr(pdf_path_or_file, 'read'):
                try:
                    os.unlink(pdf_path)
                except:
                    pass
            
            # Convert DataFrames to list of lists
            tables = []
            for df in dfs:
                if df is not None and not df.empty:
                    # Replace NaN with empty string
                    df = df.fillna('')
                    # Convert to list of lists
                    rows = df.values.tolist()
                    # Convert all cells to strings
                    rows = [[str(cell).strip() for cell in row] for row in rows]
                    # Skip empty rows
                    rows = [row for row in rows if any(cell for cell in row)]
                    if rows:
                        tables.append(rows)
            
            extraction_time = time.time() - start_time
            
            return TableExtractionResult(
                tables=tables,
                engine='tabula',
                page_count=len(set(df.page for df in dfs)) if hasattr(dfs[0], 'page') else 0,
                table_count=len(tables),
                error=None,
                extraction_time=extraction_time
            )
            
        except Exception as e:
            logger.error(f"Tabula extraction error: {e}")
            return TableExtractionResult(
                tables=[],
                engine='tabula',
                page_count=0,
                table_count=0,
                error=str(e),
                extraction_time=time.time() - start_time
            )
    
    @classmethod
    def extract_with_camelot(cls, pdf_path_or_file,
                             flavor: str = 'lattice',
                             pages: str = 'all') -> TableExtractionResult:
        """
        Extract tables using Camelot-py (Python-native with lattice/stream modes).
        
        Args:
            pdf_path_or_file: Path to PDF or file-like object
            flavor: 'lattice' (for bordered tables) or 'stream' (for borderless)
            pages: Pages to extract from ('all' or comma-separated)
            
        Returns:
            TableExtractionResult with tables and metadata
        """
        import time
        start_time = time.time()
        
        try:
            import camelot
        except ImportError as e:
            logger.error(f"Camelot-py not available: {e}")
            return TableExtractionResult(
                tables=[],
                engine='camelot',
                page_count=0,
                table_count=0,
                error=f"Camelot-py not installed: {e}"
            )
        
        try:
            logger.info(f"Extracting tables with Camelot ({flavor}) from PDF...")
            
            # Convert file object to path if needed
            pdf_path = None
            if hasattr(pdf_path_or_file, 'read'):
                pdf_path_or_file.seek(0)
                # Save to temp file for camelot
                import tempfile
                temp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
                temp.write(pdf_path_or_file.read())
                temp.close()
                pdf_path = temp.name
            else:
                pdf_path = pdf_path_or_file
            
            # Parse pages
            if pages == 'all':
                page_spec = '1-end'
            else:
                page_spec = pages
            
            # Extract tables
            tables_obj = camelot.read_pdf(
                pdf_path,
                pages=page_spec,
                flavor=flavor
            )
            
            # Clean up temp file
            if hasattr(pdf_path_or_file, 'read'):
                try:
                    os.unlink(pdf_path)
                except:
                    pass
            
            # Convert to list of lists
            tables = []
            for table in tables_obj:
                df = table.df
                if df is not None and not df.empty:
                    rows = df.values.tolist()
                    rows = [[str(cell).strip() for cell in row] for row in rows]
                    rows = [row for row in rows if any(cell for cell in row)]
                    if rows:
                        tables.append(rows)
            
            extraction_time = time.time() - start_time
            
            return TableExtractionResult(
                tables=tables,
                engine=f'camelot-{flavor}',
                page_count=len(tables_obj),
                table_count=len(tables),
                error=None,
                extraction_time=extraction_time
            )
            
        except Exception as e:
            logger.error(f"Camelot extraction error: {e}")
            return TableExtractionResult(
                tables=[],
                engine=f'camelot-{flavor}',
                page_count=0,
                table_count=0,
                error=str(e),
                extraction_time=time.time() - start_time
            )
    
    @classmethod
    def extract_with_pdfplumber(cls, pdf_path_or_file) -> TableExtractionResult:
        """
        Extract tables using PDFPlumber (Python-native, good for complex layouts).
        
        Args:
            pdf_path_or_file: Path to PDF or file-like object
            
        Returns:
            TableExtractionResult with tables and metadata
        """
        import time
        start_time = time.time()
        
        try:
            import pdfplumber
        except ImportError as e:
            logger.error(f"PDFPlumber not available: {e}")
            return TableExtractionResult(
                tables=[],
                engine='pdfplumber',
                page_count=0,
                table_count=0,
                error=f"PDFPlumber not installed: {e}"
            )
        
        try:
            logger.info("Extracting tables with PDFPlumber from PDF...")
            
            if hasattr(pdf_path_or_file, 'read'):
                pdf_path_or_file.seek(0)
                pdf = pdfplumber.open(pdf_path_or_file)
            else:
                pdf = pdfplumber.open(pdf_path_or_file)
            
            tables = []
            page_count = 0
            
            with pdf as p:
                for page in p.pages:
                    page_count += 1
                    page_tables = page.extract_tables()
                    
                    if page_tables:
                        for t in page_tables:
                            if t:
                                rows = [[str(cell).strip() if cell is not None else '' for cell in row] for row in t]
                                rows = [row for row in rows if any(cell for cell in row)]
                                if rows:
                                    tables.append(rows)
            
            pdf.close()
            
            extraction_time = time.time() - start_time
            
            return TableExtractionResult(
                tables=tables,
                engine='pdfplumber',
                page_count=page_count,
                table_count=len(tables),
                error=None,
                extraction_time=extraction_time
            )
            
        except Exception as e:
            logger.error(f"PDFPlumber extraction error: {e}")
            return TableExtractionResult(
                tables=[],
                engine='pdfplumber',
                page_count=0,
                table_count=0,
                error=str(e),
                extraction_time=time.time() - start_time
            )
    
    @classmethod
    def extract_all_tables(cls, pdf_path_or_file) -> TableExtractionResult:
        """
        Extract tables using all available engines and combine results.
        
        Best quality extraction - combines tables from multiple engines
        and removes duplicates.
        
        Returns:
            TableExtractionResult with combined tables from all engines
        """
        import time
        start_time = time.time()
        
        all_tables = []
        engines_used = []
        total_pages = 0
        errors = []
        
        # Try each engine and collect results
        engines = [
            ('pdfplumber', cls.extract_with_pdfplumber),
            ('tabula', cls.extract_with_tabula),
            ('camelot-lattice', lambda f: cls.extract_with_camelot(f, flavor='lattice')),
            ('camelot-stream', lambda f: cls.extract_with_camelot(f, flavor='stream')),
        ]
        
        for engine_name, extractor_func in engines:
            result = extractor_func(pdf_path_or_file)
            
            if result.error:
                errors.append(f"{engine_name}: {result.error}")
                continue
            
            if result.tables:
                engines_used.append(engine_name)
                total_pages = max(total_pages, result.page_count)
                
                for table in result.tables:
                    # Check if this table is a duplicate
                    is_duplicate = False
                    for existing in all_tables:
                        if cls._tables_match(table, existing):
                            is_duplicate = True
                            break
                    
                    if not is_duplicate:
                        all_tables.append(table)
                
                logger.info(f"{engine_name}: found {result.table_count} tables")
        
        extraction_time = time.time() - start_time
        
        if not engines_used:
            error_msg = "; ".join(errors) if errors else "No table extraction engine available"
            return TableExtractionResult(
                tables=[],
                engine='none',
                page_count=0,
                table_count=0,
                error=error_msg,
                extraction_time=extraction_time
            )
        
        return TableExtractionResult(
            tables=all_tables,
            engine='+'.join(engines_used),
            page_count=total_pages,
            table_count=len(all_tables),
            error=None if engines_used else error_msg,
            extraction_time=extraction_time
        )
    
    @classmethod
    def extract_best_tables(cls, pdf_path_or_file) -> TableExtractionResult:
        """
        Extract tables using the best available engine.
        
        Strategy: Try PDFPlumber first (fastest), then Tabula (most accurate),
        then Camelot stream (best for borderless).
        
        Returns first successful result with good quality tables.
        """
        import time
        start_time = time.time()
        
        # Strategy: Try engines in order of best quality
        engines = [
            ('tabula', cls.extract_with_tabula, 0.6),
            ('pdfplumber', cls.extract_with_pdfplumber, 0.5),
            ('camelot-stream', lambda f: cls.extract_with_camelot(f, flavor='stream'), 0.4),
            ('camelot-lattice', lambda f: cls.extract_with_camelot(f, flavor='lattice'), 0.3),
        ]
        
        for engine_name, extractor_func, quality_threshold in engines:
            result = extractor_func(pdf_path_or_file)
            
            if result.error:
                continue
            
            if result.tables:
                # Check table quality
                avg_row_count = sum(len(t) for t in result.tables) / len(result.tables) if result.tables else 0
                
                if avg_row_count >= 2:  # At least 2 rows on average
                    result.extraction_time = time.time() - start_time
                    return result
        
        return TableExtractionResult(
            tables=[],
            engine='none',
            page_count=0,
            table_count=0,
            error='No suitable table extraction engine available',
            extraction_time=time.time() - start_time
        )
    
    @classmethod
    def _tables_match(cls, table1: List[List[str]], table2: List[List[str]], 
                     similarity: float = 0.8) -> bool:
        """
        Check if two tables are similar (likely duplicates).
        
        Args:
            table1: First table
            table2: Second table
            similarity: Minimum similarity threshold (0-1)
            
        Returns:
            True if tables are likely the same
        """
        if not table1 or not table2:
            return False
        
        if len(table1) != len(table2):
            return False
        
        if not table1[0] or not table2[0]:
            return False
        
        # Compare first row (headers) - they should be similar
        header1 = table1[0]
        header2 = table2[0]
        
        if len(header1) != len(header2):
            return False
        
        matches = sum(1 for c1, c2 in zip(header1, header2) if c1.strip() == c2.strip())
        header_similarity = matches / len(header1) if header1 else 0
        
        return header_similarity >= similarity


# Convenience functions
def extract_tables_from_pdf(pdf_path: str, engine: str = 'best') -> Dict:
    """
    Simple interface for table extraction.
    
    Args:
        pdf_path: Path to PDF file
        engine: 'tabula', 'camelot', 'pdfplumber', 'all', or 'best'
        
    Returns:
        Dict with tables and metadata
    """
    engine_map = {
        'tabula': TableExtractor.extract_with_tabula,
        'camelot': lambda f: TableExtractor.extract_with_camelot(f, flavor='stream'),
        'pdfplumber': TableExtractor.extract_with_pdfplumber,
        'all': TableExtractor.extract_all_tables,
        'best': TableExtractor.extract_best_tables,
    }
    
    extractor = engine_map.get(engine.lower(), TableExtractor.extract_best_tables)
    result = extractor(pdf_path)
    return result.to_dict()
