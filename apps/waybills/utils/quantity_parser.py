import re
from typing import Union


def extract_numeric_value(text: Union[str, float, int, None]) -> float:
    """
    Extract the first numeric value from a mixed string.

    Examples:
        "500kg"      -> 500.0
        "7.5 tons"   -> 7.5
        "300 bags"   -> 300.0
        "1000pcs"    -> 1000.0
        "no number"  -> 0.0

    - Returns 0.0 when no number is found or input is empty.
    - Does not modify the original text; callers should store the raw string separately.
    """
    if text is None:
        return 0.0

    # Allow passing numeric types directly
    if isinstance(text, (int, float)):
        try:
            return float(text)
        except (TypeError, ValueError):
            return 0.0

    # Normalize common thousands separators (commas) before parsing.
    # This lets inputs like "5,000kg" or "1,234.56 bags" be parsed correctly.
    value_str = str(text).replace(",", "").strip()
    if not value_str:
        return 0.0

    # Find the first integer or decimal number, including negative values
    match = re.search(r"-?\d+(\.\d+)?", value_str)
    if not match:
        return 0.0

    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return 0.0

