"""
Duplicate guard – prevents duplicate attendance logs by device_id, device_user_id, timestamp.

Alias for duplicate_detector with audit-compliant naming.
"""
from ..duplicate_detector import (
    generate_hash_from_payload,
    is_duplicate_attendance,
    is_duplicate_queue_item,
)

__all__ = [
    "generate_hash_from_payload",
    "is_duplicate_attendance",
    "is_duplicate_queue_item",
]
