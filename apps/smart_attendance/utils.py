import hashlib
from datetime import datetime
from typing import Any, Dict

from django.utils import timezone


def compute_queue_hash(employee_id: str, timestamp: datetime, device_id: int) -> str:
    """
    Generate SHA256 hash of (employee + timestamp + device_id) for duplicate detection.
    """
    ts_str = timestamp.astimezone(timezone.utc).isoformat()
    raw = f"{employee_id}|{ts_str}|{device_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_timestamp(value: Any) -> datetime:
    """
    Convert various timestamp representations to aware datetime.
    Supports: datetime, Unix (int/float), ISO string, "YYYY-MM-DD HH:MM:SS".
    """
    if value is None:
        raise ValueError("timestamp is required")
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        try:
            if value > 1e12:
                value = value / 1000.0
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (ValueError, OSError) as e:
            raise ValueError(f"Invalid timestamp: {e}") from e
    else:
        s = str(value).strip()
        if not s:
            raise ValueError("timestamp is required")
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(s[:29].rstrip("Z"), fmt)
                break
            except ValueError:
                continue
        else:
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError as e:
                raise ValueError(f"Invalid timestamp format: {e}") from e
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    return dt


def safe_get(d: Dict[str, Any], key: str, default=None):
    """Small helper for dict access."""
    return d.get(key, default)

