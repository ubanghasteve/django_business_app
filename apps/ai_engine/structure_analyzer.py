# -*- coding: utf-8 -*-
"""
Document structure analyzer - ENHANCED VERSION

Given raw text, this module:
- Splits content into paragraphs (using blank lines as separators)
- Detects heading-like paragraphs using layout and casing heuristics
- Computes character offsets so callers know exact positioning
- Enhanced to detect more heading types including resume/CV sections

It is intentionally rule-based, fast, and dependency-free so it works
reliably on all deployments (including Windows) without extra models.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any


@dataclass
class ParagraphInfo:
    index: int
    text: str
    char_start: int
    char_end: int
    is_heading: bool
    heading_level: int


# Expanded set of heading keywords for better detection
HEADING_KEYWORDS = {
    # Resume/CV keywords
    'summary', 'professional summary', 'profile', 'career profile',
    'objective', 'career objective', 'employment objective',
    'experience', 'work experience', 'professional experience',
    'employment history', 'work history', 'career history',
    'education', 'educational background', 'academic background',
    'skills', 'technical skills', 'key skills', 'core competencies',
    'strengths', 'competencies', 'expertise',
    'certifications', 'certificates', 'licenses', 'credentials',
    'projects', 'key projects', 'notable projects',
    'publications', 'research', 'papers',
    'languages', 'language skills', 'language proficiency',
    'interests', 'hobbies', 'activities',
    'referees', 'references', 'recommendations',
    'personal details', 'personal information', 'contact information',
    'contact info', 'contact details', 'address',
    'date of birth', 'dob', 'nationality', 'gender',
    'marital status', 'religion', 'race',
    'work experience', 'internship', 'training',
    'awards', 'achievements', 'honors', 'recognitions',
    'volunteer', 'volunteering', 'community service',
    'leadership', 'extra curricular',
    
    # Business document keywords
    'invoice', 'tax invoice', 'proforma invoice', 'receipt',
    'statement', 'account statement', 'bank statement',
    'transaction', 'transactions', 'ledger',
    'balance', 'balance sheet', 'income statement',
    'profit', 'loss', 'cash flow',
    'customer', 'supplier', 'vendor', 'client',
    'payment', 'due date', 'terms', 'conditions',
    'total', 'subtotal', 'tax', 'vat', 'gst',
    'bill to', 'ship to', 'from', 'to',
    'date', 'invoice number', 'reference', 'order number',
    'description', 'quantity', 'unit price', 'amount', 'rate',
    
    # Report/section keywords
    'introduction', 'background', 'overview', 'executive summary',
    'methodology', 'methods', 'approach',
    'findings', 'results', 'analysis',
    'discussion', 'recommendations', 'conclusion',
    'appendix', 'annex', 'references', 'bibliography',
    'table of contents', 'contents',
    
    # Common section headers
    'header', 'footer', 'page', 'section',
    'note', 'notes', 'remark', 'remarks',
    'important', 'attention', 'warning',
}


def _is_all_caps(token: str) -> bool:
    cleaned = ''.join(ch for ch in token if ch.isalpha())
    if not cleaned:
        return False
    # Consider it all-caps if most letters are uppercase
    upper_count = sum(1 for ch in cleaned if ch.isupper())
    return upper_count / len(cleaned) >= 0.8


def _is_title_case(text: str) -> bool:
    """Check if text is Title Case (first letter of each word capitalized)"""
    if not text:
        return False
    words = text.split()
    if len(words) <= 1:
        return False
    title_count = sum(1 for w in words if w and w[0].isupper())
    return title_count / len(words) >= 0.7


def _looks_like_numbered_heading(line: str) -> bool:
    """
    Detect classic numbered headings like:
    - "1. Introduction"
    - "2.1 Scope"
    - "III. Methodology"
    - "(a) First item"
    - "A. Section A"
    """
    stripped = line.strip()
    if not stripped:
        return False
    import re

    patterns = [
        r"^\d+\.\s+\S+",
        r"^\d+(\.\d+)+\s+\S+",
        r"^[IVXLCDM]+\.\s+\S+",  # Roman numerals
        r"^[A-Z]\.\s+\S+",  # "A. Section"
        r"^\([a-z]\)\s+\S+",  # "(a) item"
    ]
    for pat in patterns:
        if re.match(pat, stripped):
            return True
    return False


def _estimate_heading_level(text: str) -> int:
    """
    Enhanced heading level estimation:
    - Level 1: ALL CAPS short headings
    - Level 2: Title Case or numbered headings
    - Level 3: Smaller / fallback
    """
    stripped = text.strip()
    if not stripped:
        return 3
    
    # Check for numbered headings
    if _looks_like_numbered_heading(stripped):
        return 2
    
    tokens = stripped.split()
    
    # ALL CAPS short headings = Level 1
    if len(tokens) <= 8 and all(_is_all_caps(tok) for tok in tokens if tok.isalpha()):
        return 1
    
    # Title Case short headings = Level 2
    if len(tokens) <= 8 and _is_title_case(stripped):
        return 2
    
    # Short regular text = Level 2
    if len(tokens) <= 6:
        return 2
    
    return 3


def _is_heading_paragraph(paragraph: str, prev_blank: bool, next_blank: bool) -> bool:
    """
    Enhanced heading detection with more heuristics.
    """
    text = (paragraph or "").strip()
    if not text:
        return False

    # Very long paragraphs are unlikely to be headings
    if len(text) > 150:
        return False

    # Heuristic: headings often have no trailing full stop
    if text.endswith(".") and len(text.split()) > 3:
        return False

    # Check for numbered headings
    if _looks_like_numbered_heading(text):
        return True

    # Check against expanded keyword list
    lower_text = text.lower().strip().rstrip(':')
    
    # Exact match or contained in keyword
    for keyword in HEADING_KEYWORDS:
        if lower_text == keyword or lower_text.startswith(keyword + ' '):
            return True
    
    tokens = text.split()
    word_count = len(tokens)

    # Short blocks with strong separation are likely headings
    separation_bonus = prev_blank and next_blank

    # Measure capitalization
    cap_tokens = [tok for tok in tokens if any(ch.isalpha() for ch in tok)]
    upper_like = sum(1 for tok in cap_tokens if _is_all_caps(tok))
    cap_ratio = (upper_like / len(cap_tokens)) if cap_tokens else 0.0

    # Strong heading signals
    if separation_bonus and word_count <= 12 and cap_ratio >= 0.4:
        return True
    
    if separation_bonus and word_count <= 8:
        return True

    # ALL CAPS without perfect separation
    if word_count <= 6 and cap_ratio >= 0.6:
        return True

    # Title Case even without blank lines
    if word_count <= 6 and _is_title_case(text) and not text.endswith('.'):
        return True

    return False


def _split_paragraphs_with_offsets(text: str) -> List[ParagraphInfo]:
    """
    Split text into paragraphs using blank lines.
    Track character offsets for each paragraph in the original text.
    """
    paragraphs: List[ParagraphInfo] = []
    if not text:
        return paragraphs

    lines = text.splitlines(keepends=True)
    buffer: List[str] = []
    buffer_start_char = 0
    current_char = 0
    index = 0

    def flush_buffer() -> None:
        nonlocal index, buffer, buffer_start_char, paragraphs
        if not buffer:
            return
        para_text = "".join(buffer)
        para = ParagraphInfo(
            index=index,
            text=para_text.rstrip("\n"),
            char_start=buffer_start_char,
            char_end=buffer_start_char + len(para_text),
            is_heading=False,  # filled later
            heading_level=3,
        )
        paragraphs.append(para)
        index += 1
        buffer = []

    for line in lines:
        stripped = line.strip()
        if stripped == "":
            # Blank line -> paragraph boundary
            flush_buffer()
            current_char += len(line)
            buffer_start_char = current_char
            continue
        if not buffer:
            buffer_start_char = current_char
        buffer.append(line)
        current_char += len(line)

    flush_buffer()
    return paragraphs


def analyze_document_structure(text: str) -> Dict[str, Any]:
    """
    Main entry point.

    Returns:
        {
          "paragraphs": [
            {
              "index": 0,
              "text": "...",
              "char_start": 0,
              "char_end": 123,
              "is_heading": true,
              "heading_level": 1
            },
            ...
          ],
          "headings": [
            {
              "title": "...",
              "paragraph_index": 0,
              "char_start": 0,
              "char_end": 20,
              "level": 1
            },
            ...
          ]
        }
    """
    text = text or ""
    paragraphs = _split_paragraphs_with_offsets(text)
    if not paragraphs:
        return {"paragraphs": [], "headings": []}

    # Determine blank-line separation context for each paragraph
    # by looking at surrounding text between char_end and next char_start.
    headings: List[Dict[str, Any]] = []
    total_len = len(text)

    def has_blank_range(start: int, end: int) -> bool:
        if start >= end:
            return False
        segment = text[start:end]
        # True if there's at least one completely blank line
        for line in segment.splitlines():
            if not line.strip():
                return True
        return False

    for i, para in enumerate(paragraphs):
        before_start = paragraphs[i - 1].char_end if i > 0 else 0
        after_end = paragraphs[i + 1].char_start if i + 1 < len(paragraphs) else total_len
        prev_blank = has_blank_range(before_start, para.char_start)
        next_blank = has_blank_range(para.char_end, after_end)

        is_heading = _is_heading_paragraph(para.text, prev_blank=prev_blank, next_blank=next_blank)
        level = _estimate_heading_level(para.text) if is_heading else 3
        para.is_heading = is_heading
        para.heading_level = level

        if is_heading:
            headings.append(
                {
                    "title": para.text.strip(),
                    "paragraph_index": para.index,
                    "char_start": para.char_start,
                    "char_end": para.char_end,
                    "level": level,
                }
            )

    return {
        "paragraphs": [asdict(p) for p in paragraphs],
        "headings": headings,
    }

