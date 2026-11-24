# -*- coding: utf-8 -*-
"""
Document Layout Analysis Module - AI-powered document structure detection.

This module uses doclayout-yolo for state-of-the-art document layout analysis:
- Detects headings, paragraphs, tables, figures, and other layout elements
- Identifies reading order for complex documents
- Handles invisible border tables and grid layouts
- Works with PDF pages and images

Usage:
    from apps.extraction.layout_analyzer import LayoutAnalyzer
    
    # Analyze document layout
    result = LayoutAnalyzer.analyze_image(image_path)
    result = LayoutAnalyzer.analyze_pdf(pdf_path)
    
    # Get structured layout elements
    elements = LayoutAnalyzer.get_layout_elements(image_path)
"""
import os
import io
import logging
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class LayoutElementType(Enum):
    """Document layout element types detected by doclayout-yolo."""
    TITLE = "title"
    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"
    TABLE_OF_CONTENTS = "table_of_contents"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"
    FOOTNOTE = "footnote"
    REFERENCE = "reference"
    LIST = "list"
    CAPTION = "caption"
    SEPARATOR = "separator"
    UNKNOWN = "unknown"


@dataclass
class LayoutElement:
    """A detected layout element with position and content."""
    element_type: LayoutElementType
    text: str
    bbox: List[float]  # [x1, y1, x2, y2] normalized 0-1
    confidence: float
    page: int = 1
    children: List['LayoutElement'] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'type': self.element_type.value,
            'text': self.text,
            'bbox': self.bbox,
            'confidence': self.confidence,
            'page': self.page,
            'children': [c.to_dict() if isinstance(c, LayoutElement) else c for c in self.children],
        }


@dataclass
class LayoutAnalysisResult:
    """Result of document layout analysis."""
    elements: List[LayoutElement]
    pages: List[Dict]
    full_text: str
    tables: List[List[List[str]]]
    layout_lines: List[str]
    engine: str
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'elements': [e.to_dict() if isinstance(e, LayoutElement) else e for e in self.elements],
            'pages': self.pages,
            'full_text': self.full_text,
            'tables': self.tables,
            'layout_lines': self.layout_lines,
            'engine': self.engine,
            'error': self.error,
        }


class LayoutAnalyzer:
    """
    Document layout analysis using doclayout-yolo.
    
    doclayout-yolo is a state-of-the-art model trained on millions of documents
    that can accurately detect:
    - Titles and headings (multiple levels)
    - Paragraphs and text blocks
    - Tables (with and without borders)
    - Figures and images
    - Lists
    - Headers and footers
    - Footnotes and references
    
    It preserves reading order and spatial relationships.
    """
    
    _model = None
    
    @classmethod
    def _get_model(cls, model_name: str = "doclayout-yolo/doclayout_yolo_tabular"):
        """
        Lazy-load the doclayout-yolo model.
        
        Args:
            model_name: Model name or path. Default is optimized for tabular data.
        """
        if cls._model is None:
            try:
                import doclayout_yolo
                cls._model = doclayout_yolo.YOLO(model_name)
                logger.info(f"doclayout-yolo model loaded: {model_name}")
            except Exception as e:
                logger.error(f"Failed to load doclayout-yolo model: {e}")
                return None
        return cls._model
    
    @classmethod
    def analyze_image(cls, image_source: Union[str, io.BytesIO, Any],
                     model_name: str = "doclayout-yolo/doclayout_yolo_tabular") -> LayoutAnalysisResult:
        """
        Analyze layout of a document image.
        
        Args:
            image_source: Path to image, BytesIO object, or PIL Image/numpy array
            model_name: doclayout-yolo model to use
            
        Returns:
            LayoutAnalysisResult with detected elements and text
        """
        try:
            model = cls._get_model(model_name)
            if model is None:
                return LayoutAnalysisResult(
                    elements=[],
                    pages=[],
                    full_text='',
                    tables=[],
                    layout_lines=[],
                    engine='doclayout-yolo',
                    error='doclayout-yolo model not available'
                )
            
            logger.info("Running doclayout-yolo layout analysis...")
            
            # Run inference
            results = model.predict(source=image_source, verbose=False, save=False)
            
            if not results or len(results) == 0:
                return LayoutAnalysisResult(
                    elements=[],
                    pages=[],
                    full_text='',
                    tables=[],
                    layout_lines=[],
                    engine='doclayout-yolo',
                    error='No layout detected'
                )
            
            # Process results
            result = results[0]
            elements = []
            tables = []
            layout_lines = []
            
            # Get boxes and classes
            if hasattr(result, 'boxes') and result.boxes is not None:
                boxes = result.boxes
                
                # Get class names
                class_names = boxes.cls.tolist() if hasattr(boxes.cls, 'tolist') else boxes.cls
                confs = boxes.conf.tolist() if hasattr(boxes.conf, 'tolist') else boxes.conf
                xyxy = boxes.xyxy.tolist() if hasattr(boxes.xyxy, 'tolist') else boxes.xyxy
                
                # Map class IDs to names
                class_map = {
                    0: LayoutElementType.TITLE,
                    1: LayoutElementType.TEXT,
                    2: LayoutElementType.TABLE,
                    3: LayoutElementType.FIGURE,
                    4: LayoutElementType.TABLE_OF_CONTENTS,
                    5: LayoutElementType.PAGE_HEADER,
                    6: LayoutElementType.PAGE_FOOTER,
                    7: LayoutElementType.FOOTNOTE,
                    8: LayoutElementType.REFERENCE,
                    9: LayoutElementType.LIST,
                    10: LayoutElementType.CAPTION,
                    11: LayoutElementType.SEPARATOR,
                }
                
                for i, (cls_id, conf, bbox) in enumerate(zip(class_names, confs, xyxy)):
                    element_type = class_map.get(int(cls_id), LayoutElementType.UNKNOWN)
                    
                    # Extract text from this region using OCR
                    text = cls._extract_text_from_bbox(image_source, bbox)
                    
                    element = LayoutElement(
                        element_type=element_type,
                        text=text,
                        bbox=bbox,
                        confidence=float(conf),
                        page=1
                    )
                    elements.append(element)
                    
                    # Collect tables
                    if element_type == LayoutElementType.TABLE:
                        # Try to parse table content
                        table_content = cls._extract_table_content(image_source, bbox)
                        if table_content:
                            tables.append(table_content)
                    
                    # Collect text for layout_lines
                    if text:
                        layout_lines.append(text)
            
            # Sort elements by position (top-to-bottom, left-to-right)
            elements.sort(key=lambda e: (e.bbox[1], e.bbox[0]))
            
            # Build full text
            full_text = '\n'.join(layout_lines)
            
            return LayoutAnalysisResult(
                elements=elements,
                pages=[{
                    'page_number': 1,
                    'elements': [e.to_dict() for e in elements],
                    'text': full_text
                }],
                full_text=full_text,
                tables=tables,
                layout_lines=layout_lines,
                engine='doclayout-yolo',
                error=None
            )
            
        except Exception as e:
            logger.error(f"Layout analysis error: {e}")
            return LayoutAnalysisResult(
                elements=[],
                pages=[],
                full_text='',
                tables=[],
                layout_lines=[],
                engine='doclayout-yolo',
                error=str(e)
            )
    
    @classmethod
    def analyze_pdf(cls, pdf_path_or_file) -> LayoutAnalysisResult:
        """
        Analyze layout of all pages in a PDF document.
        
        Args:
            pdf_path_or_file: Path to PDF or file-like object
            
        Returns:
            LayoutAnalysisResult with layout analysis for all pages
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return LayoutAnalysisResult(
                elements=[],
                pages=[],
                full_text='',
                tables=[],
                layout_lines=[],
                engine='doclayout-yolo',
                error='PyMuPDF (fitz) not installed'
            )
        
        try:
            if hasattr(pdf_path_or_file, 'read'):
                pdf_path_or_file.seek(0)
                doc = fitz.open(stream=pdf_path_or_file.read(), filetype='pdf')
            else:
                doc = fitz.open(pdf_path_or_file)
            
            all_elements = []
            all_pages = []
            all_text = []
            all_tables = []
            all_layout_lines = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Render page to image
                mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better detection
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                img_io = io.BytesIO(img_bytes)
                
                # Analyze this page
                page_result = cls.analyze_image(img_io)
                
                # Update page numbers
                for element in page_result.elements:
                    element.page = page_num + 1
                
                all_elements.extend(page_result.elements)
                all_pages.append({
                    'page_number': page_num + 1,
                    'elements': [e.to_dict() for e in page_result.elements],
                    'text': page_result.full_text
                })
                
                if page_result.full_text:
                    all_text.append(page_result.full_text)
                all_layout_lines.extend(page_result.layout_lines)
                all_tables.extend(page_result.tables)
            
            doc.close()
            
            return LayoutAnalysisResult(
                elements=all_elements,
                pages=all_pages,
                full_text='\n\n'.join(all_text),
                tables=all_tables,
                layout_lines=all_layout_lines,
                engine='doclayout-yolo',
                error=None
            )
            
        except Exception as e:
            logger.error(f"PDF layout analysis error: {e}")
            return LayoutAnalysisResult(
                elements=[],
                pages=[],
                full_text='',
                tables=[],
                layout_lines=[],
                engine='doclayout-yolo',
                error=str(e)
            )
    
    @classmethod
    def get_layout_elements(cls, image_source: Union[str, io.BytesIO]) -> List[LayoutElement]:
        """
        Get structured layout elements from an image.
        
        Args:
            image_source: Path to image or BytesIO object
            
        Returns:
            List of LayoutElement objects sorted by position
        """
        result = cls.analyze_image(image_source)
        return result.elements
    
    @classmethod
    def _extract_text_from_bbox(cls, image_source: Union[str, io.BytesIO, Any], 
                                bbox: List[float]) -> str:
        """
        Extract text from a bounding box region using OCR.
        
        Uses PaddleOCR for best results on document text.
        """
        try:
            from paddleocr import PaddleOCR
            import numpy as np
            from PIL import Image
            
            # Load image
            if hasattr(image_source, 'read'):
                image_source.seek(0)
                img = Image.open(image_source)
                img = np.array(img)
            else:
                img = Image.open(image_source)
                img = np.array(img)
            
            # Convert bbox to pixel coordinates
            h, w = img.shape[:2]
            x1, y1, x2, y2 = [int(coord) for coord in bbox]
            
            # Crop region
            crop = img[y1:y2, x1:x2]
            
            # Quick OCR on region
            ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
            result = ocr.ocr(crop, cls=True)
            
            if result and result[0]:
                texts = []
                for line in result[0]:
                    if line and len(line) >= 2:
                        text = line[1][0] if isinstance(line[1], tuple) else line[1]
                        if text:
                            texts.append(str(text).strip())
                return ' '.join(texts)
            
            return ''
            
        except Exception as e:
            logger.debug(f"BBox text extraction error: {e}")
            return ''
    
    @classmethod
    def _extract_table_content(cls, image_source: Union[str, io.BytesIO, Any],
                              bbox: List[float]) -> Optional[List[List[str]]]:
        """
        Extract table content from a detected table region.
        
        Uses table detection to parse the table structure.
        """
        try:
            import numpy as np
            from PIL import Image
            
            # Load image
            if hasattr(image_source, 'read'):
                image_source.seek(0)
                img = Image.open(image_source)
                img = np.array(img)
            else:
                img = Image.open(image_source)
                img = np.array(img)
            
            # Convert bbox to pixel coordinates
            h, w = img.shape[:2]
            x1, y1, x2, y2 = [int(coord) for coord in bbox]
            
            # Crop region
            crop = img[y1:y2, x1:x2]
            
            # Use PaddleOCR table mode
            from paddleocr import PaddleOCR
            ocr = PaddleOCR(use_angle_cls=True, lang='en', table=True, show_log=False)
            result = ocr.table(crop)
            
            if result and len(result) > 0:
                table_result = result[0]
                if isinstance(table_result, dict):
                    html_table = table_result.get('res', {})
                    html = html_table.get('html', '')
                    # Parse HTML table to list of lists
                    return cls._parse_html_table(html)
            
            return None
            
        except Exception as e:
            logger.debug(f"Table content extraction error: {e}")
            return None
    
    @classmethod
    def _parse_html_table(cls, html: str) -> List[List[str]]:
        """Parse HTML table to list of lists."""
        try:
            from bs4 import BeautifulSoup
            
            soup = BeautifulSoup(html, 'html.parser')
            table = soup.find('table')
            
            if not table:
                return []
            
            rows = []
            for tr in table.find_all('tr'):
                cells = []
                for td in tr.find_all(['td', 'th']):
                    cells.append(td.get_text(strip=True))
                if cells:
                    rows.append(cells)
            
            return rows
            
        except Exception:
            return []


# Convenience function
def analyze_document_layout(file_path: str) -> Dict:
    """
    Analyze document layout for images or PDFs.
    
    Args:
        file_path: Path to document (PDF or image)
        
    Returns:
        Dict with layout analysis results
    """
    lower = file_path.lower()
    
    if lower.endswith('.pdf'):
        result = LayoutAnalyzer.analyze_pdf(file_path)
    else:
        result = LayoutAnalyzer.analyze_image(file_path)
    
    return result.to_dict()
