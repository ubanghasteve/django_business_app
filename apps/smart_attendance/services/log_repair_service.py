"""
Log repair service – detects missing/corrupted logs and auto-repairs attendance gaps.

Alias for corrupted_log_repair with audit-compliant naming.
"""
from ..corrupted_log_repair import attempt_repair

__all__ = ["attempt_repair"]
