# -*- coding: utf-8 -*-
"""
Enhanced CV Extraction Service V2
Automatically extracts text and information from uploaded CVs
Supports: PDF, DOC, DOCX, XLSX, PPTX, Images (JPG, JPEG, PNG)
Handles long documents (20-30+ pages)
Smart structural detection and organization
Now with Smart Extraction support (Azure Document AI, Google Document AI) for handwriting and tables
"""
import re
import io
import logging
import os
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import smart extraction backends
SMART_EXTRACTION_AVAILABLE = False
try:
    from apps.extraction.smart_backends import run_smart_extraction
    SMART_EXTRACTION_AVAILABLE = True
except ImportError:
    run_smart_extraction = None
    logger.info("Smart extraction not available - using local OCR")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EnhancedCVExtractor:
    """Enhanced extractor with smart detection and structure recognition"""
    
    # Comprehensive skill database
    SKILL_DATABASE = {
        'programming': ['python', 'javascript', 'java', 'c++', 'c#', 'ruby', 'php', 'swift', 'kotlin', 'golang', 'rust', 'scala', 'perl', 'r', 'matlab', 'bash', 'powershell', 'typescript', 'dart', 'elixir', 'haskell', 'lua', 'julia', 'groovy'],
        'frameworks': ['react', 'angular', 'vue', 'django', 'flask', 'fastapi', 'spring', 'express', 'node.js', 'next.js', 'nuxt.js', 'gatsby', 'laravel', 'codeigniter', 'rails', 'asp.net', ' Xamarin', 'flutter', 'react native'],
        'databases': ['sql', 'mysql', 'postgresql', 'mongodb', 'oracle', 'redis', 'elasticsearch', 'cassandra', 'sqlite', 'mariadb', 'dynamodb', 'firebase', 'couchdb', 'neo4j', 'influxdb'],
        'cloud': ['aws', 'azure', 'gcp', 'docker', 'kubernetes', 'jenkins', 'terraform', 'ansible', 'cloudformation', 'gitlab ci', 'github actions', 'circleci', 'serverless', 'lambda', 'heroku'],
        'frontend': ['html', 'css', 'sass', 'less', 'bootstrap', 'tailwind', 'material ui', 'ant design', 'chakra ui', 'webpack', 'vite', 'gulp', 'figma', 'adobe xd', 'sketch'],
        'data_science': ['machine learning', 'deep learning', 'tensorflow', 'pytorch', 'keras', 'scikit-learn', 'pandas', 'numpy', 'scipy', 'jupyter', 'spark', 'hadoop', 'tableau', 'power bi', 'nlp', 'computer vision', 'opencv'],
        'soft_skills': ['leadership', 'communication', 'teamwork', 'problem solving', 'analytical', 'time management', 'project management', 'agile', 'scrum', 'kanban', 'mentoring', 'negotiation', 'presentation'],
        'languages': ['english', 'french', 'spanish', 'german', 'chinese', 'arabic', 'portuguese', 'italian', 'japanese', 'korean', 'hindi', 'russian', 'dutch', 'swedish'],
        'tools': ['git', 'github', 'gitlab', 'bitbucket', 'jira', 'confluence', 'slack', 'zoom', 'postman', 'swagger', 'linux', 'unix', 'windows server', 'networking'],
    }
    
    # Flat list for searching
    ALL_SKILLS = set()
    for category, skills in SKILL_DATABASE.items():
        ALL_SKILLS.update(skills)
    
    # Education keywords
    EDUCATION_KEYWORDS = [
        'university', 'college', 'institute', 'school', 'bachelor', 'master', 'phd', 'doctorate',
        'degree', 'diploma', 'certificate', 'bsc', 'msc', 'ba', 'ma', 'beng', 'meng', 'mba',
        'associate', 'graduate', 'undergraduate', 'honours', 'first class', 'second class',
        'gpa', 'cgpa', 'm.sc', 'b.sc', 'b.tech', 'm.tech', 'b.e', 'm.e'
    ]
    
    # Experience keywords
    EXPERIENCE_KEYWORDS = [
        'experience', 'work history', 'employment', 'career', 'professional', 'previously',
        'worked at', 'company', 'position', 'role', 'responsibilities', 'achievements',
        'duties', 'projects', 'internship', 'contract', 'freelance', 'consultant'
    ]
    
    @classmethod
    def extract_all(cls, file_content: bytes, filename: str) -> Dict:
        """
        Main extraction method - handles any file type
        """
        result = {
            'raw_text': '',
            'structured_text': {},
            'email': '',
            'phone': [],
            'name': '',
            'first_name': '',
            'last_name': '',
            'skills': {},
            'education': [],
            'work_experience': [],
            'position_applied': '',
            'years_of_experience': '',
            'address': '',
            'extraction_success': False,
            'error': None,
            'pages_processed': 0,
            'file_type': '',
            'metadata': {},
            'tables': [],
        }
        
        try:
            filename_lower = filename.lower()
            result['file_type'] = cls._get_file_type(filename_lower)
            logger.info(f"Starting extraction for {filename}, type: {result['file_type']}")
            
            # Try smart extraction first (Azure Document AI / Google Document AI)
            # This handles handwriting and tables much better
            text = ''
            tables = []
            layout_lines = []
            smart_extraction_used = False
            
            if SMART_EXTRACTION_AVAILABLE and os.environ.get('USE_SMART_EXTRACTION'):
                try:
                    # Create a file-like object for smart extraction
                    file_obj = io.BytesIO(file_content)
                    smart_result = run_smart_extraction(file_obj)
                    
                    if smart_result and isinstance(smart_result, dict):
                        smart_text = smart_result.get('text', '')
                        smart_tables = smart_result.get('tables', [])
                        smart_layout = smart_result.get('layout_lines', [])
                        
                        if smart_text and len(smart_text.strip()) > 10:
                            text = smart_text
                            tables = smart_tables if smart_tables else []
                            layout_lines = smart_layout if smart_layout else []
                            smart_extraction_used = True
                            logger.info(f"Smart extraction successful for {filename}: {len(text)} chars, {len(tables)} tables")
                        elif smart_result.get('error'):
                            logger.warning(f"Smart extraction returned error: {smart_result.get('error')}")
                except Exception as e:
                    logger.warning(f"Smart extraction failed for {filename}: {str(e)}")
            
            # Fall back to local extraction if smart extraction didn't work
            if not text or len(text.strip()) < 10:
                logger.info(f"Smart extraction not available or returned insufficient text, using local extraction for {filename}")
                if result['file_type'] == 'pdf':
                    text = cls._extract_pdf(file_content)
                elif result['file_type'] == 'docx':
                    text = cls._extract_docx(file_content)
                elif result['file_type'] == 'doc':
                    text = cls._extract_doc(file_content)
                elif result['file_type'] == 'xlsx':
                    text = cls._extract_xlsx(file_content)
                elif result['file_type'] == 'pptx':
                    text = cls._extract_pptx(file_content)
                elif result['file_type'] in ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'webp']:
                    text = cls._extract_image(file_content)
                elif result['file_type'] == 'txt':
                    text = cls._extract_text(file_content)
                else:
                    result['error'] = f'Unsupported file type: {result["file_type"]}'
                    return result
            
            logger.info(f"Final text extraction for {filename}: {len(text)} chars (smart: {smart_extraction_used})")
            
            result['raw_text'] = text
            result['pages_processed'] = cls._estimate_pages(text)
            
            # Parse structured information - be more lenient
            if text and len(text.strip()) > 5:
                result['email'] = cls._extract_email(text)
                result['phone'] = cls._extract_all_phones(text)
                result['name'] = cls._extract_name(text)
                first_last = cls._extract_first_last_name(text)
                result['first_name'] = first_last[0]
                result['last_name'] = first_last[1]
                result['skills'] = cls._extract_all_skills(text)
                result['education'] = cls._extract_all_education(text)
                result['work_experience'] = cls._extract_all_experience(text)
                result['position_applied'] = cls._extract_position(text)
                result['years_of_experience'] = cls._extract_years_of_experience(text)
                result['address'] = cls._extract_address(text)
                result['structured_text'] = cls._detect_structure(text)
                result['extraction_success'] = True
                
                # If smart extraction returned tables, use them for enhanced extraction
                if tables:
                    result['tables'] = tables
                    # Try to extract structured info from tables
                    table_education = cls._extract_education_from_tables(tables)
                    table_experience = cls._extract_experience_from_tables(tables)
                    
                    # Merge with text-based extraction
                    if table_education and not result['education']:
                        result['education'] = table_education
                    if table_experience and not result['work_experience']:
                        result['work_experience'] = table_experience
                
                logger.info(f"Successfully extracted from {filename}: pages={result['pages_processed']}, email={result['email']}, name={result['name']}, address={result['address']}")
            else:
                # Still mark as success if we got some text but it's very short
                if text and len(text.strip()) > 0:
                    result['raw_text'] = text
                    result['extraction_success'] = True
                    result['error'] = 'Document extracted but text is very short. Content: ' + text[:200]
                else:
                    result['error'] = 'Could not extract any text from the document. The file may be scanned/image-based requiring OCR, or it may be a corrupted file. Please try a different file format or ensure the PDF contains selectable text.'
                
        except Exception as e:
            logger.error(f"Extraction error for {filename}: {str(e)}")
            result['error'] = str(e)
        
        return result
    
    @classmethod
    def _get_file_type(cls, filename: str) -> str:
        """Detect file type from extension"""
        if filename.endswith('.pdf'):
            return 'pdf'
        elif filename.endswith('.docx'):
            return 'docx'
        elif filename.endswith('.doc'):
            return 'doc'
        elif filename.endswith('.xlsx'):
            return 'xlsx'
        elif filename.endswith('.xls'):
            return 'xls'
        elif filename.endswith('.pptx'):
            return 'pptx'
        elif filename.endswith('.ppt'):
            return 'ppt'
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            return 'jpg'
        elif filename.endswith('.png'):
            return 'png'
        elif filename.endswith('.gif'):
            return 'gif'
        elif filename.endswith('.bmp'):
            return 'bmp'
        elif filename.endswith('.tiff') or filename.endswith('.tif'):
            return 'tiff'
        elif filename.endswith('.webp'):
            return 'webp'
        elif filename.endswith('.txt'):
            return 'txt'
        return 'unknown'
    
    @classmethod
    def _extract_pdf(cls, file_content: bytes) -> str:
        """Extract text from PDF - handles multi-page documents"""
        text = ''
        
        # Try pdfplumber first (faster, more accurate)
        try:
            import pdfplumber
            
            with pdfplumber.open(io.BytesIO(file_content)) as pdf:
                logger.info(f"PDF opened with pdfplumber, pages: {len(pdf.pages)}")
                for page_num, page in enumerate(pdf.pages, 1):
                    page_text = page.extract_text()
                    if page_text:
                        text += f"\n\n--- Page {page_num} ---\n\n"
                        text += page_text
            
            if len(text.strip()) > 100:
                logger.info(f"pdfplumber extracted {len(text)} chars")
                return text
            else:
                logger.warning(f"pdfplumber extracted only {len(text)} chars, trying other methods")
                
        except ImportError as e:
            logger.warning(f"pdfplumber not installed: {e}")
        except Exception as e:
            logger.warning(f"pdfplumber failed: {e}")
        
        # Fallback: Try PyMuPDF (fitz) for PDFs with images
        try:
            import fitz
            doc = fitz.open(stream=io.BytesIO(file_content), doc_type='pdf')
            logger.info(f"PDF opened with PyMuPDF, pages: {len(doc)}")
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                page_text = page.get_text()
                if page_text and len(page_text.strip()) > 10:
                    text += f"\n\n--- Page {page_num + 1} ---\n\n"
                    text += page_text
            
            if len(text.strip()) > 100:
                logger.info(f"PyMuPDF extracted {len(text)} chars")
                return text
            else:
                logger.warning(f"PyMuPDF extracted only {len(text)} chars")
                
        except ImportError:
            logger.warning("PyMuPDF (fitz) not installed")
        except Exception as e:
            logger.warning(f"PyMuPDF failed: {e}")
        
        # Try OCR for scanned PDFs
        try:
            text = cls._extract_pdf_ocr(file_content)
            if text and len(text.strip()) > 100:
                logger.info(f"OCR extracted {len(text)} chars")
                return text
        except Exception as e:
            logger.error(f"OCR fallback failed: {e}")
        
        # Try pdftotext as last resort
        try:
            import subprocess
            with open('temp_pdf.pdf', 'wb') as f:
                f.write(file_content)
            result = subprocess.run(['pdftotext', 'temp_pdf.pdf', '-'], 
                                  capture_output=True, text=True, timeout=30)
            if result.stdout and len(result.stdout.strip()) > 100:
                logger.info(f"pdftotext extracted {len(result.stdout)} chars")
                return result.stdout
        except Exception as e:
            logger.warning(f"pdftotext failed: {e}")
        
        return text
    
    @classmethod
    def _extract_pdf_ocr(cls, file_content: bytes) -> str:
        """Extract text using OCR for scanned PDFs with enhanced handwriting support"""
        text = ''
        
        try:
            from pdf2image import convert_from_bytes
            import pytesseract
            from PIL import Image, ImageEnhance, ImageFilter
            
            # Convert PDF to images (batch for speed)
            images = convert_from_bytes(file_content, dpi=300, first_page=1, last_page=50)
            
            # OCR configurations for best results
            configs = [
                r'--oem 3 --psm 6',  # Default
                r'--oem 3 --psm 4',  # Columns
                r'--oem 1 --psm 11', # Sparse (handwriting)
            ]
            
            for page_num, image in enumerate(images, 1):
                page_texts = []
                
                # Try multiple OCR configs
                for config in configs:
                    try:
                        page_text = pytesseract.image_to_string(image, config=config, timeout=30)
                        if page_text.strip():
                            page_texts.append(page_text)
                    except:
                        continue
                
                # Also try enhanced image processing for handwriting
                try:
                    gray = image.convert('L')
                    enhanced = ImageEnhance.Contrast(gray).enhance(2.0)
                    enhanced = enhanced.filter(ImageFilter.SMOOTH)
                    page_text = pytesseract.image_to_string(enhanced, config=r'--oem 1 --psm 11', timeout=30)
                    if page_text.strip():
                        page_texts.append(page_text)
                except:
                    pass
                
                # Take the longest result
                if page_texts:
                    best_text = max(page_texts, key=len)
                    if best_text.strip():
                        text += f"\n\n--- Page {page_num} ---\n\n"
                        text += best_text
                        
        except ImportError:
            logger.warning("OCR libraries not available")
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
        
        return text
    
    @classmethod
    def _extract_docx(cls, file_content: bytes) -> str:
        """Extract from DOCX with formatting preserved"""
        text = ''
        
        try:
            import docx
            from docx.oxml.text.paragraph import CT_P
            from docx.oxml.table import CT_Tbl
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            
            doc = docx.Document(io.BytesIO(file_content))
            
            # Extract paragraphs with style detection
            for element in doc.element.body:
                if isinstance(element, CT_P):
                    para = Paragraph(element, doc)
                    style_name = para.style.name if para.style else 'Normal'
                    
                    if para.text.strip():
                        # Detect heading level
                        if 'Heading' in style_name:
                            level = style_name.replace('Heading ', '')
                            text += f"\n\n### HEADING {level}: {para.text}\n\n"
                        else:
                            text += para.text + "\n"
                
                elif isinstance(element, CT_Tbl):
                    # Extract tables
                    table = Table(element, doc)
                    for row in table.rows:
                        row_data = [cell.text.strip() for cell in row.cells]
                        if any(row_data):
                            text += " | ".join(row_data) + "\n"
                    text += "\n"
            
            # Also get all plain text
            full_text = "\n".join([p.text for p in doc.paragraphs])
            
            # Return combined
            return text if len(text) > len(full_text) else full_text
            
        except Exception as e:
            logger.error(f"DOCX extraction failed: {e}")
        
        return text
    
    @classmethod
    def _extract_doc(cls, file_content: bytes) -> str:
        """Extract from old DOC format"""
        # Note: .doc format is complex, try antiword or textract
        text = ''
        
        try:
            # Try python-docx after converting
            # For now, return empty - would need additional libraries
            logger.warning("Old .doc format may require additional libraries")
        except Exception as e:
            logger.error(f"DOC extraction failed: {e}")
        
        return text
    
    @classmethod
    def _extract_xlsx(cls, file_content: bytes) -> str:
        """Extract from Excel files"""
        text = ''
        
        try:
            import openpyxl
            
            wb = openpyxl.load_workbook(io.BytesIO(file_content), data_only=True)
            
            for sheet_name in wb.sheetnames:
                text += f"\n\n=== Sheet: {sheet_name} ===\n\n"
                sheet = wb[sheet_name]
                
                for row in sheet.iter_rows(values_only=True):
                    row_text = " | ".join([str(cell) if cell is not None else "" for cell in row])
                    if row_text.strip():
                        text += row_text + "\n"
            
        except Exception as e:
            logger.error(f"Excel extraction failed: {e}")
        
        return text
    
    @classmethod
    def _extract_pptx(cls, file_content: bytes) -> str:
        """Extract from PowerPoint"""
        text = ''
        
        try:
            from pptx import Presentation
            
            prs = Presentation(io.BytesIO(file_content))
            
            for slide_num, slide in enumerate(prs.slides, 1):
                text += f"\n\n--- Slide {slide_num} ---\n\n"
                
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        text += shape.text + "\n"
                    
                    # Extract tables
                    if shape.has_table:
                        for row in shape.table.rows:
                            row_text = " | ".join([cell.text for cell in row.cells])
                            text += row_text + "\n"
            
        except Exception as e:
            logger.error(f"PowerPoint extraction failed: {e}")
        
        return text
    
    @classmethod
    def _extract_image(cls, file_content: bytes) -> str:
        """Extract text from images using OCR with enhanced handwriting support"""
        text = ''
        
        # Try advanced OCR engines first (PaddleOCR, EasyOCR, RapidOCR)
        advanced_text = cls._extract_with_advanced_ocr(file_content)
        if advanced_text and len(advanced_text) > 100:
            logger.info(f"Advanced OCR extracted {len(advanced_text)} chars")
            return advanced_text
        
        # Fall back to traditional PyTesseract
        try:
            from PIL import Image, ImageEnhance, ImageFilter
            import pytesseract
            
            image = Image.open(io.BytesIO(file_content))
            
            # Convert to RGB if needed
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Try multiple OCR configurations for best results
            config_default = r'--oem 3 --psm 6'
            config_columns = r'--oem 3 --psm 4'
            config_sparse = r'--oem 1 --psm 11'
            config_uniform = r'--oem 3 --psm 3'
            
            results = []
            
            # Try default
            try:
                txt1 = pytesseract.image_to_string(image, config=config_default, lang='eng')
                if txt1.strip():
                    results.append(txt1)
            except:
                pass
            
            # Try with column detection
            try:
                txt2 = pytesseract.image_to_string(image, config=config_columns, lang='eng')
                if txt2.strip() and txt2 != results[0] if results else True:
                    results.append(txt2)
            except:
                pass
            
            # Try sparse text (better for handwriting)
            try:
                txt3 = pytesseract.image_to_string(image, config=config_sparse, lang='eng')
                if txt3.strip() and txt3 != results[0] if results else True:
                    results.append(txt3)
            except:
                pass
            
            # If no results from standard OCR, try enhanced preprocessing for handwriting
            if not results:
                try:
                    gray = image.convert('L')
                    enhancer = ImageEnhance.Contrast(gray)
                    enhanced = enhancer.enhance(2.0)
                    enhanced = enhanced.filter(ImageFilter.SMOOTH)
                    txt = pytesseract.image_to_string(enhanced, config=config_sparse, lang='eng')
                    if txt.strip():
                        results.append(txt)
                except Exception as e:
                    logger.warning(f"Enhanced OCR failed: {e}")
            
            if results:
                text = max(results, key=len)
            
        except ImportError:
            logger.warning("pytesseract not available")
        except Exception as e:
            logger.error(f"Image OCR failed: {e}")
        
        return text
    
    @classmethod
    def _extract_with_advanced_ocr(cls, file_content: bytes) -> str:
        """
        Extract text using advanced OCR engines (PaddleOCR, EasyOCR, RapidOCR).
        Returns the best result from all available engines.
        """
        all_results = []
        
        # Try PaddleOCR
        try:
            from paddleocr import PaddleOCR
            ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
            img = Image.open(io.BytesIO(file_content))
            result = ocr.ocr(img, cls=True)
            if result and result[0]:
                texts = []
                for line in result[0]:
                    if line and len(line) >= 2:
                        info = line[1]
                        text = info[0] if isinstance(info, tuple) else info
                        if text and str(text).strip():
                            texts.append(str(text).strip())
                if texts:
                    all_results.append(('\n'.join(texts), 'paddleocr'))
                    logger.info(f"PaddleOCR extracted {len(texts)} text blocks")
        except Exception as e:
            logger.debug(f"PaddleOCR failed: {e}")
        
        # Try EasyOCR
        try:
            import easyocr
            reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            result = reader.readtext(file_content)
            if result:
                texts = []
                for detection in result:
                    text = detection[1] if len(detection) > 1 else ''
                    if text and text.strip():
                        texts.append(text.strip())
                if texts:
                    all_results.append((' '.join(texts), 'easyocr'))
                    logger.info(f"EasyOCR extracted {len(texts)} text blocks")
        except Exception as e:
            logger.debug(f"EasyOCR failed: {e}")
        
        # Try RapidOCR
        try:
            from rapidocr_onnxruntime import RapidOCR
            ocr = RapidOCR()
            result, elapsed = ocr(file_content)
            if result:
                texts = []
                for detection in result:
                    text = detection[1] if len(detection) > 1 else ''
                    if text and str(text).strip():
                        texts.append(str(text).strip())
                if texts:
                    all_results.append(('\n'.join(texts), 'rapidocr'))
                    logger.info(f"RapidOCR extracted {len(texts)} text blocks in {elapsed:.2f}s")
        except Exception as e:
            logger.debug(f"RapidOCR failed: {e}")
        
        # Return the longest result
        if all_results:
            best = max(all_results, key=lambda x: len(x[0]))
            logger.info(f"Best advanced OCR: {best[1]} with {len(best[0])} chars")
            return best[0]
        
        return ''
    
    @classmethod
    def _extract_text(cls, file_content: bytes) -> str:
        """Extract plain text"""
        return file_content.decode('utf-8', errors='ignore')
    
    @classmethod
    def _estimate_pages(cls, text: str) -> int:
        """Estimate number of pages from text length"""
        # Average page has ~3000 characters
        page_size = 3000
        return max(1, len(text) // page_size)
    
    # ========== INFORMATION EXTRACTION ==========
    
    @classmethod
    def _extract_email(cls, text: str) -> str:
        """Extract email address"""
        # Multiple patterns for better detection
        patterns = [
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            r'Email[:\s]*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
            r'E-mail[:\s]*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return matches[0]
        return ''
    
    @classmethod
    def _extract_all_phones(cls, text: str) -> List[str]:
        """Extract phone numbers - ONLY from contact section, very strict patterns"""
        phones = []
        
        # Only look at first 20 lines (contact info section)
        lines = text.split('\n')
        contact_lines = []
        
        # Find contact section by looking for contact-related keywords
        contact_start = -1
        contact_keywords = ['contact', 'phone', 'mobile', 'email', 'address', 'tel']
        
        for i, line in enumerate(lines[:30]):
            line_lower = line.lower().strip()
            # Check if this is a contact header or contains contact info
            if any(kw in line_lower for kw in contact_keywords):
                if len(line_lower) < 30 or re.match(r'^(contact|phone|mobile|tel|address|details)', line_lower):
                    contact_start = i
                    break
        
        # Extract only from contact section (lines after header)
        if contact_start >= 0:
            contact_section_lines = []
            for i in range(contact_start, min(contact_start + 20, len(lines))):
                line = lines[i].strip()
                line_lower = line.lower()
                # Stop if we hit a non-contact section
                if i > contact_start and any(kw in line_lower for kw in ['summary', 'experience', 'education', 'skills', 'objective']):
                    if len(line_lower) < 30:
                        break
                if line:
                    contact_section_lines.append(line)
            contact_text = ' '.join(contact_section_lines)
        else:
            # If no header found, use first 15 lines
            contact_text = ' '.join(lines[:15])
        
        # STRICT phone patterns - must have proper format
        phone_patterns = [
            # Standard US format: (123) 456-7890 or 123-456-7890
            r'(?:\+?1[-.\s]?)?\((\d{3})\)\s*[-.]?\s*(\d{3})[-.\s]?(\d{4})',
            # With "Phone:", "Mobile:", "Tel:" prefix
            r'(?:Phone|Mobile|Cell|Tel|Telephone|M)[:\s]*(\+?[\d\s\-\(\)]{10,20})',
            # Direct format: +1 123 456 7890 or +1-123-456-7890
            r'\+?1\s+\d{3}\s+\d{3}\s+\d{4}',
            # International with + prefix
            r'\+\d{1,3}[-.\s]?\d{2,4}[-.\s]?\d{2,4}[-.\s]?\d{2,4}',
        ]
        
        found_phones = set()
        
        for pattern in phone_patterns:
            matches = re.findall(pattern, contact_text, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    # Reconstruct from groups
                    phone = ''.join([g for g in match if g])
                else:
                    phone = match
                
                # Clean and validate
                digits = re.sub(r'[^\d]', '', str(phone))
                
                # Must be valid phone length (7-15 digits)
                if 7 <= len(digits) <= 15:
                    # Format nicely
                    if len(digits) == 10:
                        formatted = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
                        found_phones.add(formatted)
                    elif len(digits) == 11 and digits[0] == '1':
                        formatted = f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
                        found_phones.add(formatted)
                    elif len(digits) == 7:
                        formatted = f"{digits[:3]}-{digits[3:]}"
                        found_phones.add(formatted)
                    elif len(digits) > 10:
                        # International - keep as-is with +
                        formatted = f"+{digits}"
                        found_phones.add(formatted)
        
        # Remove any false positives - filter out if it looks like a year or date
        final_phones = []
        for phone in found_phones:
            # Skip if it looks like a year (19xx or 20xx)
            digits = re.sub(r'[^\d]', '', phone)
            if len(digits) >= 4:
                year_candidate = digits[:4]
                if year_candidate.startswith('19') or year_candidate.startswith('20'):
                    if 1980 <= int(year_candidate) <= 2026:
                        # Check if remaining digits could be something else
                        remaining = digits[4:]
                        if len(remaining) < 7:  # Looks more like a year
                            continue
            
            # Skip if it's just too short to be meaningful
            if len(phone) < 7:
                continue
                
            final_phones.append(phone)
        
        return final_phones[:5]  # Return max 5
    
    @classmethod
    def _extract_position(cls, text: str) -> str:
        """Extract position applied/job title"""
        lines = text.split('\n')
        text_lower = text.lower()
        
        position_keywords = ['position', 'applying for', 'job title', 'desired position', 
                           'applying to', 'role', 'desired role', 'target position']
        
        for i, line in enumerate(lines[:20]):
            line_lower = line.lower()
            if any(kw in line_lower for kw in position_keywords):
                # Try to extract the position from this line
                cleaned = re.sub(r'(position|applying for|job title|desired|role|applying to|target)[:\s]*', '', line_lower, flags=re.IGNORECASE).strip()
                if cleaned and len(cleaned) > 2 and len(cleaned) < 100:
                    return cleaned.title()
        
        common_titles = ['software engineer', 'software developer', 'web developer', 'data scientist',
                       'data analyst', 'project manager', 'product manager', 'designer', 'ux designer',
                       'ui designer', 'full stack developer', 'frontend developer', 'backend developer',
                       'devops engineer', 'qa engineer', 'accountant', 'hr manager', 'marketing manager',
                       'sales manager', 'business analyst', 'consultant', 'architect', 'technical lead']
        
        for title in common_titles:
            if title in text_lower:
                return title.title()
        
        return ''
    
    @classmethod
    def _extract_years_of_experience(cls, text: str) -> str:
        """Extract years of experience"""
        text_lower = text.lower()
        
        patterns = [
            r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s*)?experience',
            r'experience[:\s]*(\d+)\+?\s*(?:years?|yrs?)',
            r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s*)?exp',
            r'(?:total|overall)[:\s]*(\d+)\+?\s*(?:years?|yrs?)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                return f"{match.group(1)} years"
        
        # Try to calculate from date ranges
        date_patterns = [
            r'(present|current)\s*[-–—to]+\s*(\d{4})',
            r'(\d{4})\s*[-–—to]+\s*(present|current)',
        ]
        
        years_list = []
        for pattern in date_patterns:
            matches = re.findall(pattern, text_lower)
            for m in matches:
                try:
                    year = int(m[1]) if m[1].isdigit() else int(m[0])
                    if year > 1990 and year <= 2026:
                        years_list.append(2026 - year)
                except:
                    pass
        
        if years_list:
            return f"{max(years_list)} years"
        
        return ''
    
    @classmethod
    def _extract_address(cls, text: str) -> str:
        """Extract address - ONLY actual address, not phone or email"""
        lines = text.split('\n')
        
        # Look ONLY in first 15 lines (contact section)
        for i, line in enumerate(lines[:15]):
            line_stripped = line.strip()
            
            # Skip empty lines
            if not line_stripped or len(line_stripped) < 5:
                continue
            
            # Remove phone/email info from the line FIRST
            # Work with a copy
            working_line = line_stripped
            
            # DEBUG
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"DEBUG address: line={repr(line_stripped)}")
            
            # Remove everything after Tel:, Phone:, Mobile:
            for suffix in ['Tel:', 'Phone:', 'Mobile:']:
                if suffix in working_line:
                    logger.info(f"DEBUG: Found suffix {suffix}")
                    working_line = working_line.split(suffix)[0].strip()
                    logger.info(f"DEBUG: After split: {repr(working_line)}")
            
            # Remove everything after Email:
            if 'Email:' in working_line:
                working_line = working_line.split('Email:')[0].strip()
            
            # Remove phone numbers (patterns like +234, (123), etc.)
            import re
            working_line = re.sub(r'\s*\+\d{3,}[\s\d,]*', '', working_line)
            working_line = re.sub(r'\s*\(\d{3}\)\s*[\d-]+', '', working_line)
            working_line = re.sub(r'\s*\d{3}[-.\s]\d{3}[-.\s]\d{4}', '', working_line)
            
            # Remove @ email addresses
            if '@' in working_line:
                working_line = working_line.split('@')[0].strip()
            
            # Skip if nothing left or too short
            if not working_line or len(working_line) < 5:
                continue
            
            # Now check if what remains is a valid address
            
            # Skip if contains summary/objective keywords
            keywords_to_skip = ['summary', 'objective', 'experience', 'education', 'skills', 
                             'profile', 'developer', 'engineer', 'manager']
            if any(kw in working_line.lower() for kw in keywords_to_skip):
                # But still check if it starts with digits (address)
                if not re.match(r'^\d', working_line):
                    continue
            
            # Pattern: Street address (starts with number)
            if re.match(r'^\d+\s+\w+', working_line):
                street_types = ['street', 'st', 'avenue', 'ave', 'road', 'rd', 'drive', 'dr', 
                             'lane', 'ln', 'court', 'ct', 'place', 'pl', 'boulevard', 'blvd',
                             'close', 'way', 'crescent', 'cres']
                if any(st in working_line.lower() for st in street_types):
                    return working_line
            
            # Pattern: City, State (like "New York, NY")
            if re.search(r'[A-Za-z]+,\s+[A-Z]{2}\s*\d?', working_line):
                return working_line
            
            # Pattern: Just city, country (like "Abuja, Nigeria")
            if re.match(r'^[A-Z][a-z]+,\s+[A-Za-z]+$', working_line):
                return working_line
        
        return ''
    
    @classmethod
    def _extract_name(cls, text: str) -> str:
        """Extract person name - improved algorithm"""
        lines = text.split('\n')
        
        # Look in first 15 lines
        for i, line in enumerate(lines[:15]):
            line = line.strip()
            line_clean = re.sub(r'[^\w\s]', '', line)
            words = line_clean.split()
            
            # Skip if too short or contains keywords
            skip_words = ['resume', 'cv', 'curriculum', 'vitae', 'profile', 'summary', 
                         'email', 'phone', 'mobile', 'address', 'contact']
            if any(w.lower() in skip_words for w in words):
                continue
            
            # Name patterns: 2-4 capitalized words
            if 2 <= len(words) <= 4:
                # Check if all words look like name parts
                name_parts = 0
                for word in words:
                    if word and word[0].isupper() and len(word) > 1:
                        # Not a common word
                        if word.lower() not in ['the', 'and', 'for', 'with', 'from', 'this', 'that']:
                            name_parts += 1
                
                if name_parts >= 2:
                    return line.title()
        
        return ''
    
    @classmethod
    def _extract_first_last_name(cls, text: str) -> tuple:
        """Extract first and last name separately"""
        full_name = cls._extract_name(text)
        if not full_name:
            return ('', '')
        
        parts = full_name.strip().split()
        if len(parts) >= 2:
            return (parts[0], ' '.join(parts[1:]))
        elif len(parts) == 1:
            return (parts[0], '')
        return ('', '')
    
    @classmethod
    def _extract_position(cls, text: str) -> str:
        """Extract position applied/job title"""
        lines = text.split('\n')
        text_lower = text.lower()
        
        position_keywords = ['position', 'applying for', 'job title', 'desired position', 
                           'applying to', 'role', 'desired role', 'target position']
        
        for i, line in enumerate(lines[:20]):
            line_lower = line.lower()
            if any(kw in line_lower for kw in position_keywords):
                # Try to extract the position from this line
                cleaned = re.sub(r'(position|applying for|job title|desired|role|applying to|target)[:\s]*', '', line_lower, flags=re.IGNORECASE).strip()
                if cleaned and len(cleaned) > 2 and len(cleaned) < 100:
                    return cleaned.title()
        
        common_titles = ['software engineer', 'software developer', 'web developer', 'data scientist',
                       'data analyst', 'project manager', 'product manager', 'designer', 'ux designer',
                       'ui designer', 'full stack developer', 'frontend developer', 'backend developer',
                       'devops engineer', ' QA engineer', 'accountant', 'hr manager', 'marketing manager',
                       'sales manager', 'business analyst', 'consultant', 'architect', 'technical lead']
        
        for title in common_titles:
            if title in text_lower:
                return title.title()
        
        return ''
    
    @classmethod
    def _extract_years_of_experience(cls, text: str) -> str:
        """Extract years of experience"""
        text_lower = text.lower()
        
        patterns = [
            r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s*)?experience',
            r'experience[:\s]*(\d+)\+?\s*(?:years?|yrs?)',
            r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s*)?exp',
            r'(?:total|overall)[:\s]*(\d+)\+?\s*(?:years?|yrs?)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text_lower)
            if match:
                return f"{match.group(1)} years"
        
        exp_indicators = [
            (r'(\d{4})\s*[-–—to]+\s*(present|current)', 'calculate'),
            (r'(present|current)\s*[-–—to]+\s*(\d{4})', 'calculate'),
        ]
        
        years_list = []
        for pattern, mode in exp_indicators:
            matches = re.findall(pattern, text_lower)
            for m in matches:
                try:
                    if mode == 'calculate':
                        start_year = int(m[0]) if m[0].isdigit() else None
                        end_year = int(m[1]) if len(m) > 1 and m[1].isdigit() else None
                        if start_year and end_year:
                            years_list.append(abs(end_year - start_year))
                except:
                    pass
        
        if years_list:
            return f"{max(years_list)} years"
        
        return ''
    
    @classmethod
    def _extract_address(cls, text: str) -> str:
        """Extract address"""
        lines = text.split('\n')
        text_lower = text.lower()
        
        address_keywords = ['address', 'street', 'city', 'location', 'residence']
        
        address_parts = []
        
        for i, line in enumerate(lines[:30]):
            line_lower = line.lower()
            
            if any(kw in line_lower for kw in address_keywords):
                # Extract after the keyword
                for kw in address_keywords:
                    if kw in line_lower:
                        parts = line.split(kw, 1)
                        if len(parts) > 1:
                            addr = parts[1].strip(':, ')
                            if len(addr) > 3:
                                address_parts.append(addr)
                        break
            
            # Look for address patterns (city, state, zip)
            addr_pattern = r'([A-Za-z\s]+),\s*([A-Za-z]{2,})\s*(\d{5,})?'
            match = re.search(addr_pattern, line)
            if match:
                address_parts.append(line.strip())
        
        if address_parts:
            return ' '.join(address_parts[:3])
        
        return ''
    
    @classmethod
    def _extract_all_skills(cls, text: str) -> Dict[str, List[str]]:
        """Extract skills organized by category"""
        text_lower = text.lower()
        found_skills = {category: [] for category in cls.SKILL_DATABASE.keys()}
        found_skills['other'] = []
        
        # Search for each skill
        for category, skills in cls.SKILL_DATABASE.items():
            for skill in skills:
                # Word boundary search for accuracy
                pattern = r'\b' + re.escape(skill) + r'\b'
                if re.search(pattern, text_lower):
                    if skill.title() not in found_skills[category]:
                        found_skills[category].append(skill.title())
        
        # Remove empty categories
        return {k: v for k, v in found_skills.items() if v}
    
    @classmethod
    def _extract_education_from_tables(cls, tables: List) -> List[Dict]:
        """Extract education information from tables detected by smart extraction"""
        education = []
        education_keywords = ['university', 'college', 'degree', 'bachelor', 'master', 'phd', 'diploma', 'gpa', 'grade', 'education']
        
        for table in tables:
            if not table:
                continue
            for row in table:
                row_text = ' '.join([str(cell).lower() for cell in row if cell])
                if any(kw in row_text for kw in education_keywords):
                    entry = {}
                    for cell in row:
                        cell_text = str(cell).strip() if cell else ''
                        if cell_text:
                            if 'university' in cell_text.lower() or 'college' in cell_text.lower():
                                entry['institution'] = cell_text
                            elif 'bachelor' in cell_text.lower() or 'master' in cell_text.lower() or 'phd' in cell_text.lower():
                                entry['degree'] = cell_text
                            elif any(yr in cell_text for yr in ['201', '202', '200']) and any(m in cell_text for m in ['-', '/']):
                                entry['year'] = cell_text
                            elif 'gpa' in cell_text.lower() or 'cgpa' in cell_text.lower():
                                entry['grade'] = cell_text
                            else:
                                if 'institution' not in entry and 'degree' not in entry and 'year' not in entry and 'grade' not in entry:
                                    entry['description'] = cell_text
                    if entry:
                        education.append(entry)
        return education
    
    @classmethod
    def _extract_experience_from_tables(cls, tables: List) -> List[Dict]:
        """Extract work experience from tables detected by smart extraction"""
        experience = []
        exp_keywords = ['experience', 'work', 'company', 'position', 'job', 'role', 'employment', 'duration', 'year']
        
        for table in tables:
            if not table:
                continue
            for row in table:
                row_text = ' '.join([str(cell).lower() for cell in row if cell])
                if any(kw in row_text for kw in exp_keywords):
                    entry = {}
                    for cell in row:
                        cell_text = str(cell).strip() if cell else ''
                        if cell_text:
                            if 'company' in cell_text.lower() or 'organization' in cell_text.lower():
                                entry['company'] = cell_text
                            elif 'position' in cell_text.lower() or 'role' in cell_text.lower() or 'job' in cell_text.lower():
                                entry['position'] = cell_text
                            elif any(yr in cell_text for yr in ['201', '202', '200']) and any(m in cell_text for m in ['-', '/', 'to']):
                                entry['duration'] = cell_text
                            elif 'present' in cell_text.lower():
                                entry['duration'] = cell_text
                            else:
                                if 'company' not in entry and 'position' not in entry and 'duration' not in entry:
                                    entry['description'] = cell_text
                    if entry:
                        experience.append(entry)
        return experience
    
    @classmethod
    def _extract_all_education(cls, text: str) -> List[Dict]:
        """Extract COMPLETE education section - all content between headers"""
        education = []
        lines = text.split('\n')
        
        # Find education section - look for section headers
        education_section_start = -1
        education_headers = [
            'education', 'educational', 'academic', 'qualification', 
            'degree', 'university', 'college', 'school'
        ]
        
        for i, line in enumerate(lines[:60]):
            line_lower = line.lower().strip()
            if any(h in line_lower for h in education_headers):
                # Make sure it's likely a header (not just the word in text)
                if len(line_lower) < 35 or re.match(r'^(education|qualifications?|academic|educational)\s*$', line_lower):
                    education_section_start = i + 1
                    break
        
        # If no header found, try searching for education content anywhere
        if education_section_start < 0:
            return cls._extract_education_fallback(text)
        
        # Extract COMPLETE education section content
        education_full_text = []
        section_headers = [
            'experience', 'employment', 'work history', 'professional',
            'skills', 'projects', 'references', 'certifications', 'languages'
        ]
        
        for i in range(education_section_start, len(lines)):
            line = lines[i].strip()
            line_lower = line.lower()
            
            # Stop at other major sections
            if any(h in line_lower for h in section_headers):
                # Make sure it's a header (not just text mentioning it)
                if len(line_lower) < 30:
                    break
            
            if line and len(line) > 2:
                education_full_text.append(line)
        
        if education_full_text:
            # Return as a single comprehensive entry with ALL content
            full_text = '\n'.join(education_full_text)
            education.append({
                'full_text': full_text,
                'text': full_text,
                'all_entries': education_full_text
            })
        
        return education
    
    @classmethod
    def _extract_education_fallback(cls, text: str) -> List[Dict]:
        """Fallback: extract education content by searching for keywords anywhere"""
        education = []
        lines = text.split('\n')
        
        # Keywords that indicate education content
        edu_keywords = [
            'university', 'college', 'institute', 'bachelor', 'master', 'phd', 
            'bsc', 'msc', 'mba', 'b.tech', 'm.tech', 'degree', 'diploma',
            'certificate', 'graduated', 'graduation', 'gpa', 'cgpa'
        ]
        
        edu_lines = []
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(kw in line_lower for kw in edu_keywords):
                edu_lines.append(line.strip())
        
        if edu_lines:
            # Also include surrounding context (lines around education keywords)
            for i, line in enumerate(lines):
                line_lower = line.lower()
                # Look for year patterns typical in education
                if re.search(r'(19|20)\d{2}\s*[-–—to]+\s*(19|20)\d{2}|present|current', line_lower):
                    if line.strip() not in edu_lines:
                        edu_lines.append(line.strip())
            
            full_text = '\n'.join(edu_lines[:30])  # Limit to 30 lines
            education.append({
                'full_text': full_text,
                'text': full_text,
                'all_entries': edu_lines
            })
        
        return education
    
    @classmethod
    def _extract_all_experience(cls, text: str) -> List[Dict]:
        """Extract COMPLETE work experience section - all content between headers"""
        experience = []
        lines = text.split('\n')
        
        # Find experience section
        exp_section_start = -1
        exp_headers = [
            'experience', 'employment', 'work history', 'work experience', 
            'professional experience', 'career', 'job history'
        ]
        
        for i, line in enumerate(lines[:60]):
            line_lower = line.lower().strip()
            if any(h in line_lower for h in exp_headers):
                if len(line_lower) < 40:
                    exp_section_start = i + 1
                    break
        
        # If no header found, try fallback
        if exp_section_start < 0:
            return cls._extract_experience_fallback(text)
        
        # Extract COMPLETE experience section content
        exp_full_text = []
        stop_headers = [
            'education', 'skills', 'projects', 'references', 
            'certifications', 'languages', 'awards', 'publications'
        ]
        
        for i in range(exp_section_start, len(lines)):
            line = lines[i].strip()
            line_lower = line.lower()
            
            # Stop at other major sections
            if any(h in line_lower for h in stop_headers):
                if len(line_lower) < 30:
                    break
            
            if line and len(line) > 2:
                exp_full_text.append(line)
        
        if exp_full_text:
            # Return as a single comprehensive entry with ALL content
            full_text = '\n'.join(exp_full_text)
            experience.append({
                'full_text': full_text,
                'text': full_text,
                'all_entries': exp_full_text
            })
        
        return experience
    
    @classmethod
    def _extract_experience_fallback(cls, text: str) -> List[Dict]:
        """Fallback: extract experience content by searching for keywords anywhere"""
        experience = []
        lines = text.split('\n')
        
        # Keywords that indicate work experience
        exp_keywords = [
            'company', 'worked', 'working', 'employment', 'position', 'role',
            'manager', 'engineer', 'developer', 'analyst', 'designer', 'consultant',
            'intern', 'contract', 'freelance', 'team lead', 'senior', 'junior'
        ]
        
        exp_lines = []
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(kw in line_lower for kw in exp_keywords):
                exp_lines.append(line.strip())
        
        if exp_lines:
            # Also include date patterns
            for i, line in enumerate(lines):
                line_lower = line.lower()
                # Look for date patterns typical in work history
                if re.search(r'(19|20)\d{2}\s*[-–—to]+\s*(present|current|19|20)\d{2}', line_lower):
                    if line.strip() not in exp_lines:
                        exp_lines.append(line.strip())
            
            full_text = '\n'.join(exp_lines[:40])  # Limit to 40 lines
            experience.append({
                'full_text': full_text,
                'text': full_text,
                'all_entries': exp_lines
            })
        
        return experience
        
        # Extract experience section content
        exp_lines = []
        if exp_section_start > 0:
            in_exp = True
            for i in range(exp_section_start, min(exp_section_start + 100, len(lines))):
                line = lines[i].strip()
                line_lower = line.lower()
                
                # Stop at other sections
                if any(kw in line_lower for kw in ['education', 'skills', 'references', 'projects', 'certifications']):
                    if len(exp_lines) > 2:
                        break
                
                if line and len(line) > 3:
                    exp_lines.append(line)
        else:
            # Fallback
            for i, line in enumerate(lines):
                line_lower = line.lower()
                if any(kw in line_lower for kw in cls.EXPERIENCE_KEYWORDS):
                    if line.strip():
                        exp_lines.append(line.strip())
        
        # Parse experience entries
        current_entry = {}
        for line in exp_lines:
            line_lower = line.lower()
            
            # Check for date patterns
            date_patterns = [
                r'((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(?:19|20)\d{2})\s*[-–—to]+\s*((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(?:19|20)\d{2}|present|current)',
                r'((?:19|20)\d{2})\s*[-–—to]+\s*((?:19|20)\d{2}|present|current)',
            ]
            date_found = None
            for pattern in date_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    date_found = match.group()
                    break
            
            # Check for company
            company_found = None
            company_patterns = [
                r'((?:at|@|working at|employed at)\s+)?([A-Z][A-Za-z0-9\s&]+(?:Inc|LLC|Corp|Ltd|Company|Technologies|Solutions|Services|Group))',
            ]
            for pattern in company_patterns:
                match = re.search(pattern, line)
                if match:
                    company_found = match.group(2) if match.group(2) else match.group(1)
                    break
            
            # Check for position/title
            position_found = None
            position_keywords = ['engineer', 'developer', 'manager', 'analyst', 'designer', 'consultant', 'architect', 'lead', 'senior', 'junior', 'intern', 'associate', 'specialist', 'coordinator', 'supervisor', 'director']
            for kw in position_keywords:
                if kw in line_lower:
                    position_found = line
                    break
            
            # If we found significant info, create entry
            if date_found or company_found or position_found:
                if current_entry and (current_entry.get('period') or current_entry.get('company')):
                    experience.append(current_entry)
                current_entry = {
                    'period': date_found or '',
                    'company': company_found or '',
                    'position': position_found or '',
                    'text': line
                }
            elif current_entry and line and len(line) > 10:
                current_entry['text'] += ' | ' + line
        
        if current_entry and (current_entry.get('period') or current_entry.get('company') or current_entry.get('text')):
            experience.append(current_entry)
        
        # Fallback: return raw lines
        if not experience and exp_lines:
            for line in exp_lines[:8]:
                if len(line) > 10:
                    experience.append({'text': line})
        
        return experience[:8]
    
    @classmethod
    def _detect_structure(cls, text: str) -> Dict:
        """Detect and organize document structure"""
        structure = {
            'titles': [],
            'headings': [],
            'paragraphs': [],
            'lists': [],
            'quotes': [],
            'sections': {}
        }
        
        lines = text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Title: Short, all caps or numbered
            if len(line) < 100 and (line.isupper() or re.match(r'^\d+\.', line)):
                structure['titles'].append(line)
                # Create section
                section_key = line.lower().replace('.', '').replace(' ', '_')[:30]
                structure['sections'][section_key] = {'title': line, 'content': []}
            
            # Heading: Contains specific keywords
            elif any(kw in line.lower() for kw in ['summary', 'objective', 'experience', 'education', 'skills', 'contact', 'profile']):
                structure['headings'].append(line)
                section_key = line.lower().replace(':', '').replace(' ', '_')[:30]
                if section_key not in structure['sections']:
                    structure['sections'][section_key] = {'title': line, 'content': []}
            
            # List item
            elif re.match(r'^[\•\-\*\→\✓\▪\▸]\s*', line):
                structure['lists'].append(line)
                # Add to current section
                if structure['sections']:
                    last_section = list(structure['sections'].keys())[-1]
                    structure['sections'][last_section]['content'].append(line)
            
            # Quote
            elif line.startswith('"') or line.startswith('"') or line.startswith('"'):
                structure['quotes'].append(line.strip('"'))
            
            # Regular paragraph
            elif len(line) > 50:
                structure['paragraphs'].append(line)
                if structure['sections']:
                    last_section = list(structure['sections'].keys())[-1]
                    structure['sections'][last_section]['content'].append(line)
        
        return structure


# Convenience function
def extract_cv_information(file_content: bytes, filename: str) -> Dict:
    """Main entry point for CV extraction"""
    return EnhancedCVExtractor.extract_all(file_content, filename)


def extract_multiple_files(files: List[tuple]) -> Dict:
    """Extract from multiple files and combine"""
    combined = {
        'raw_text': '',
        'structured_text': {},
        'email': '',
        'phone': [],
        'name': '',
        'skills': {},
        'education': [],
        'work_experience': [],
        'extraction_success': False,
        'files_processed': 0,
        'files_failed': 0,
    }
    
    all_phones = set()
    all_skills = {}
    all_education = []
    all_experience = []
    all_texts = []
    
    for file_content, filename in files:
        try:
            result = extract_cv_information(file_content, filename)
            combined['files_processed'] += 1
            
            all_texts.append(result.get('raw_text', ''))
            
            if result.get('email') and not combined.get('email'):
                combined['email'] = result['email']
            
            all_phones.update(result.get('phone', []))
            
            # Merge skills by category
            for category, skills in result.get('skills', {}).items():
                if category not in all_skills:
                    all_skills[category] = []
                all_skills[category].extend(skills)
            
            all_education.extend(result.get('education', []))
            all_experience.extend(result.get('work_experience', []))
            
        except Exception as e:
            combined['files_failed'] += 1
            logger.error(f"Failed to process {filename}: {e}")
    
    # Combine results
    combined['raw_text'] = '\n\n=== Document ===\n\n'.join(all_texts)
    combined['phone'] = list(all_phones)[:5]
    combined['skills'] = {k: list(set(v)) for k, v in all_skills.items() if v}
    combined['education'] = all_education[:5]
    combined['work_experience'] = all_experience[:8]
    combined['extraction_success'] = combined['files_processed'] > 0
    
    # Try to get name from first successful result
    for file_content, filename in files:
        result = extract_cv_information(file_content, filename)
        if result.get('name'):
            combined['name'] = result['name']
            break
    
    return combined
