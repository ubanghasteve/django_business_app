# -*- coding: utf-8 -*-
"""
Advanced OCR Module - Multi-engine OCR extraction with EasyOCR, RapidOCR, and PaddleOCR.

This module provides a unified interface for multiple OCR engines with automatic
fallback and quality-based selection. Supports:
- EasyOCR: Multi-language OCR with deep learning
- RapidOCR: Fast OCR using ONNX runtime
- PaddleOCR: Baidu's OCR with layout detection and table understanding

Usage:
    from apps.extraction.advanced_ocr import AdvancedOCR
    
    result = AdvancedOCR.extract_from_image(image_path)
    result = AdvancedOCR.extract_from_pdf(pdf_path)
    result = AdvancedOCR.extract_from_file(file_path)  # Auto-detect type
"""
import os
import io
import logging
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class OCREngine(Enum):
    """Available OCR engines."""
    EASYOCR = "easyocr"
    RAPIDOCR = "rapidocr"
    PADDLEOCR = "paddleocr"
    PYTESSERACT = "pytesseract"  # Fallback


@dataclass
class OCRResult:
    """Standardized OCR result from any engine."""
    text: str
    layout_lines: List[str]
    confidence: float
    engine: str
    tables: List[List[List[str]]]
    bounding_boxes: List[Dict]
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'text': self.text,
            'layout_lines': self.layout_lines,
            'confidence': self.confidence,
            'engine': self.engine,
            'tables': self.tables,
            'bounding_boxes': self.bounding_boxes,
            'error': self.error,
        }


class AdvancedOCR:
    """
    Advanced OCR with multiple engine support and automatic quality selection.
    
    Engines are tried in order of accuracy (PaddleOCR > EasyOCR > RapidOCR > PyTesseract)
    and the best result is selected based on text length and confidence.
    """
    
    _easyocr_reader = None
    _paddleocr_model = None
    _rapidocr_model = None
    
    @classmethod
    def _get_easyocr_reader(cls, languages: List[str] = None) -> Any:
        """Lazy-load EasyOCR reader."""
        if cls._easyocr_reader is None:
            try:
                import easyocr
                languages = languages or ['en']
                cls._easyocr_reader = easyocr.Reader(languages, gpu=False, verbose=False)
                logger.info(f"EasyOCR initialized with languages: {languages}")
            except Exception as e:
                logger.error(f"Failed to initialize EasyOCR: {e}")
                return None
        return cls._easyocr_reader
    
    @classmethod
    def _get_rapidocr_model(cls) -> Any:
        """Lazy-load RapidOCR model."""
        if cls._rapidocr_model is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
                cls._rapidocr_model = RapidOCR()
                logger.info("RapidOCR initialized")
            except Exception as e:
                logger.error(f"Failed to initialize RapidOCR: {e}")
                return None
        return cls._rapidocr_model
    
    @classmethod
    def _get_paddleocr_model(cls) -> Any:
        """Lazy-load PaddleOCR model."""
        if cls._paddleocr_model is None:
            try:
                from paddleocr import PaddleOCR
                cls._paddleocr_model = PaddleOCR(
                    use_angle_cls=True,
                    lang='en',
                    use_gpu=False,
                    show_log=False,
                    table=True,  # Enable table detection
                    table_max_len=500,
                )
                logger.info("PaddleOCR initialized with table detection")
            except Exception as e:
                logger.error(f"Failed to initialize PaddleOCR: {e}")
                return None
        return cls._paddleocr_model
    
    @classmethod
    def _ocr_with_easyocr(cls, image_source: Union[str, io.BytesIO, Any]) -> OCRResult:
        """
        Perform OCR using EasyOCR.
        
        Returns:
            OCRResult with detected text, layout lines, and confidence scores.
        """
        try:
            reader = cls._get_easyocr_reader()
            if reader is None:
                return OCRResult(
                    text='',
                    layout_lines=[],
                    confidence=0.0,
                    engine='easyocr',
                    tables=[],
                    bounding_boxes=[],
                    error='EasyOCR not available'
                )
            
            logger.info("Running EasyOCR extraction...")
            result = reader.readtext(image_source)
            
            if not result:
                return OCRResult(
                    text='',
                    layout_lines=[],
                    confidence=0.0,
                    engine='easyocr',
                    tables=[],
                    bounding_boxes=[],
                    error='No text detected'
                )
            
            # Process EasyOCR results
            text_parts = []
            layout_lines = []
            bounding_boxes = []
            confidences = []
            
            for detection in result:
                bbox = detection[0]  # Bounding box coordinates
                text = detection[1]  # Detected text
                confidence = detection[2] if len(detection) > 2 else 1.0
                
                if text and text.strip():
                    text_parts.append(text)
                    layout_lines.append(text.strip())
                    confidences.append(confidence)
                    bounding_boxes.append({
                        'bbox': bbox,
                        'text': text,
                        'confidence': confidence
                    })
            
            # Try to detect tables from aligned text
            tables = cls._detect_tables_from_ocr(bounding_boxes)
            
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            return OCRResult(
                text=' '.join(text_parts),
                layout_lines=layout_lines,
                confidence=avg_confidence,
                engine='easyocr',
                tables=tables,
                bounding_boxes=bounding_boxes,
                error=None
            )
            
        except Exception as e:
            logger.error(f"EasyOCR error: {e}")
            return OCRResult(
                text='',
                layout_lines=[],
                confidence=0.0,
                engine='easyocr',
                tables=[],
                bounding_boxes=[],
                error=str(e)
            )
    
    @classmethod
    def _ocr_with_rapidocr(cls, image_source: Union[str, io.BytesIO, Any]) -> OCRResult:
        """
        Perform OCR using RapidOCR (ONNX-based, very fast).
        
        Returns:
            OCRResult with detected text, layout lines, and confidence scores.
        """
        try:
            model = cls._get_rapidocr_model()
            if model is None:
                return OCRResult(
                    text='',
                    layout_lines=[],
                    confidence=0.0,
                    engine='rapidocr',
                    tables=[],
                    bounding_boxes=[],
                    error='RapidOCR not available'
                )
            
            logger.info("Running RapidOCR extraction...")
            result, elapsed = model(image_source)
            
            if not result:
                return OCRResult(
                    text='',
                    layout_lines=[],
                    confidence=0.0,
                    engine='rapidocr',
                    tables=[],
                    bounding_boxes=[],
                    error='No text detected'
                )
            
            # Process RapidOCR results
            text_parts = []
            layout_lines = []
            bounding_boxes = []
            confidences = []
            
            for detection in result:
                bbox = detection[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                text = detection[1]  # Detected text
                confidence = detection[2] if len(detection) > 2 else 1.0
                
                if text and text.strip():
                    text_parts.append(text)
                    layout_lines.append(text.strip())
                    confidences.append(float(confidence))
                    bounding_boxes.append({
                        'bbox': bbox,
                        'text': text,
                        'confidence': float(confidence)
                    })
            
            # Try to detect tables from aligned text
            tables = cls._detect_tables_from_ocr(bounding_boxes)
            
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            return OCRResult(
                text='\n'.join(text_parts),
                layout_lines=layout_lines,
                confidence=avg_confidence,
                engine='rapidocr',
                tables=tables,
                bounding_boxes=bounding_boxes,
                error=None
            )
            
        except Exception as e:
            logger.error(f"RapidOCR error: {e}")
            return OCRResult(
                text='',
                layout_lines=[],
                confidence=0.0,
                engine='rapidocr',
                tables=[],
                bounding_boxes=[],
                error=str(e)
            )
    
    @classmethod
    def _ocr_with_paddleocr(cls, image_source: Union[str, io.BytesIO]) -> OCRResult:
        """
        Perform OCR using PaddleOCR with layout detection and table understanding.
        
        This is the most powerful OCR engine for document extraction as it includes:
        - Layout analysis (text blocks, tables, images)
        - Table detection and structure preservation
        - Direction detection
        - Text recognition
        
        Returns:
            OCRResult with detected text, layout lines, tables, and confidence scores.
        """
        try:
            model = cls._get_paddleocr_model()
            if model is None:
                return OCRResult(
                    text='',
                    layout_lines=[],
                    confidence=0.0,
                    engine='paddleocr',
                    tables=[],
                    bounding_boxes=[],
                    error='PaddleOCR not available'
                )
            
            logger.info("Running PaddleOCR extraction with layout analysis...")
            result = model.ocr(image_source, cls=True)
            
            if not result or not result[0]:
                return OCRResult(
                    text='',
                    layout_lines=[],
                    confidence=0.0,
                    engine='paddleocr',
                    tables=[],
                    bounding_boxes=[],
                    error='No text detected'
                )
            
            # Process PaddleOCR results
            text_parts = []
            layout_lines = []
            bounding_boxes = []
            confidences = []
            all_result = result[0] if result else []
            
            for line in all_result:
                if not line:
                    continue
                bbox = line[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                info = line[1]  # (text, confidence)
                text = info[0] if isinstance(info, tuple) else info
                confidence = float(info[1]) if isinstance(info, tuple) and len(info) > 1 else 1.0
                
                if text and str(text).strip():
                    text_str = str(text).strip()
                    text_parts.append(text_str)
                    layout_lines.append(text_str)
                    confidences.append(confidence)
                    bounding_boxes.append({
                        'bbox': bbox,
                        'text': text_str,
                        'confidence': confidence
                    })
            
            # Try to detect tables from aligned text
            tables = cls._detect_tables_from_ocr(bounding_boxes)
            
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            return OCRResult(
                text='\n'.join(text_parts),
                layout_lines=layout_lines,
                confidence=avg_confidence,
                engine='paddleocr',
                tables=tables,
                bounding_boxes=bounding_boxes,
                error=None
            )
            
        except Exception as e:
            logger.error(f"PaddleOCR error: {e}")
            return OCRResult(
                text='',
                layout_lines=[],
                confidence=0.0,
                engine='paddleocr',
                tables=[],
                bounding_boxes=[],
                error=str(e)
            )
    
    @classmethod
    def _detect_tables_from_ocr(cls, bounding_boxes: List[Dict]) -> List[List[List[str]]]:
        """
        Detect tables from OCR bounding boxes by finding aligned text.
        
        Uses spatial analysis to find rows and columns in the detected text.
        """
        if len(bounding_boxes) < 3:
            return []
        
        try:
            tables = []
            
            # Extract y-coordinates for row detection
            rows_data = []
            for box in bounding_boxes:
                bbox = box['bbox']
                # Get top y-coordinate (average of top corners)
                top_y = (bbox[0][1] + bbox[1][1]) / 2
                rows_data.append({
                    'top_y': top_y,
                    'text': box['text'],
                    'bbox': bbox
                })
            
            # Sort by y-coordinate
            rows_data.sort(key=lambda x: x['top_y'])
            
            # Group into rows (lines with similar y-coordinates)
            row_groups = []
            current_row = [rows_data[0]]
            y_threshold = 10  # Pixels threshold for same row
            
            for i in range(1, len(rows_data)):
                if abs(rows_data[i]['top_y'] - current_row[0]['top_y']) < y_threshold:
                    current_row.append(rows_data[i])
                else:
                    row_groups.append(current_row)
                    current_row = [rows_data[i]]
            if current_row:
                row_groups.append(current_row)
            
            # Check if this looks like a table (multiple rows with similar structure)
            if len(row_groups) < 2:
                return []
            
            # Sort items within each row by x-coordinate
            for row in row_groups:
                row.sort(key=lambda x: x['bbox'][0][0])
            
            # Check for consistent column structure
            first_row_cols = len(row_groups[0])
            consistent_cols = all(len(row) >= 2 for row in row_groups if len(row) >= 2)
            
            if consistent_cols and len(row_groups) >= 2:
                # This looks like a table - extract it
                table = []
                for row in row_groups:
                    if len(row) >= 2:  # At least 2 columns
                        table.append([item['text'] for item in row])
                if len(table) >= 2:
                    tables.append(table)
            
            return tables
            
        except Exception as e:
            logger.debug(f"Table detection error: {e}")
            return []
    
    @classmethod
    def extract_from_image(cls, image_source: Union[str, io.BytesIO, Any], 
                          engine: Optional[OCREngine] = None) -> OCRResult:
        """
        Extract text from an image using the best available OCR engine.
        
        Args:
            image_source: Path to image file, BytesIO object, or PIL Image
            engine: Specific OCR engine to use (None = auto-select best)
            
        Returns:
            OCRResult with extracted text, layout, tables, and confidence
        """
        if engine == OCREngine.EASYOCR:
            return cls._ocr_with_easyocr(image_source)
        elif engine == OCREngine.RAPIDOCR:
            return cls._ocr_with_rapidocr(image_source)
        elif engine == OCREngine.PADDLEOCR:
            return cls._ocr_with_paddleocr(image_source)
        
        # Auto-select: Try PaddleOCR first (best for documents), then EasyOCR, then RapidOCR
        engines_to_try = [
            (OCREngine.PADDLEOCR, cls._ocr_with_paddleocr),
            (OCREngine.EASYOCR, cls._ocr_with_easyocr),
            (OCREngine.RAPIDOCR, cls._ocr_with_rapidocr),
        ]
        
        best_result = None
        best_score = 0
        
        for ocr_engine, ocr_func in engines_to_try:
            try:
                result = ocr_func(image_source)
                if result.error:
                    continue
                    
                # Score based on text length and confidence
                score = len(result.text) * result.confidence
                
                if score > best_score:
                    best_score = score
                    best_result = result
                    
                # If we got a good result, stop trying
                if score > 500 and result.confidence > 0.8:
                    break
                    
            except Exception as e:
                logger.debug(f"{ocr_engine.value} failed: {e}")
                continue
        
        # Final fallback to PyTesseract
        if best_result is None or not best_result.text:
            try:
                import pytesseract
                from PIL import Image
                
                if hasattr(image_source, 'read'):
                    image_source.seek(0)
                    img = Image.open(image_source)
                else:
                    img = Image.open(image_source)
                
                text = pytesseract.image_to_string(img)
                if text and text.strip():
                    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
                    best_result = OCRResult(
                        text=text.strip(),
                        layout_lines=lines,
                        confidence=0.7,
                        engine='pytesseract',
                        tables=[],
                        bounding_boxes=[],
                        error=None
                    )
            except Exception as e:
                logger.error(f"PyTesseract fallback failed: {e}")
        
        return best_result or OCRResult(
            text='',
            layout_lines=[],
            confidence=0.0,
            engine='none',
            tables=[],
            bounding_boxes=[],
            error='No OCR engine available'
        )
    
    @classmethod
    def extract_from_pdf(cls, pdf_path_or_file) -> OCRResult:
        """
        Extract text from PDF using PaddleOCR (best for scanned PDFs).
        
        Renders each page as an image and runs OCR on it.
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return OCRResult(
                text='',
                layout_lines=[],
                confidence=0.0,
                engine='paddleocr',
                tables=[],
                bounding_boxes=[],
                error='PyMuPDF (fitz) not installed'
            )
        
        try:
            if hasattr(pdf_path_or_file, 'read'):
                pdf_path_or_file.seek(0)
                doc = fitz.open(stream=pdf_path_or_file.read(), filetype='pdf')
            else:
                doc = fitz.open(pdf_path_or_file)
            
            all_text = []
            all_layout_lines = []
            all_tables = []
            all_bboxes = []
            total_confidence = 0
            page_count = 0
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Render page to image (150 DPI for OCR)
                mat = fitz.Matrix(150/72, 150/72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                
                # Run OCR on this page
                img_io = io.BytesIO(img_bytes)
                result = cls.extract_from_image(img_io, engine=OCREngine.PADDLEOCR)
                
                if result.text:
                    all_text.append(result.text)
                    all_layout_lines.extend(result.layout_lines)
                    all_tables.extend(result.tables)
                    all_bboxes.extend(result.bounding_boxes)
                    total_confidence += result.confidence
                    page_count += 1
            
            doc.close()
            
            avg_confidence = total_confidence / page_count if page_count > 0 else 0.0
            
            return OCRResult(
                text='\n\n'.join(all_text),
                layout_lines=all_layout_lines,
                confidence=avg_confidence,
                engine='paddleocr',
                tables=all_tables,
                bounding_boxes=all_bboxes,
                error=None
            )
            
        except Exception as e:
            logger.error(f"PDF OCR error: {e}")
            return OCRResult(
                text='',
                layout_lines=[],
                confidence=0.0,
                engine='paddleocr',
                tables=[],
                bounding_boxes=[],
                error=str(e)
            )
    
    @classmethod
    def extract_from_file(cls, file_path: str) -> OCRResult:
        """
        Auto-detect file type and extract text using appropriate method.
        """
        lower = file_path.lower()
        
        if lower.endswith(('.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.gif')):
            return cls.extract_from_image(file_path)
        elif lower.endswith('.pdf'):
            return cls.extract_from_pdf(file_path)
        else:
            return OCRResult(
                text='',
                layout_lines=[],
                confidence=0.0,
                engine='none',
                tables=[],
                bounding_boxes=[],
                error=f'Unsupported file type'
            )


# Convenience function for simple usage
def extract_text_from_image(image_path: str, engine: str = 'auto') -> Dict:
    """
    Simple interface for OCR extraction.
    
    Args:
        image_path: Path to image file
        engine: 'easyocr', 'rapidocr', 'paddleocr', or 'auto'
        
    Returns:
        Dict with text, layout_lines, confidence, tables
    """
    engine_map = {
        'easyocr': OCREngine.EASYOCR,
        'rapidocr': OCREngine.RAPIDOCR,
        'paddleocr': OCREngine.PADDLEOCR,
        'auto': None,
    }
    
    ocr_engine = engine_map.get(engine.lower(), None)
    result = AdvancedOCR.extract_from_image(image_path, engine=ocr_engine)
    return result.to_dict()


def extract_text_from_pdf(pdf_path: str) -> Dict:
    """
    Simple interface for PDF OCR extraction.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Dict with text, layout_lines, confidence, tables
    """
    result = AdvancedOCR.extract_from_pdf(pdf_path)
    return result.to_dict()
