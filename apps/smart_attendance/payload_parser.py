"""
Flexible biometric payload parser – accepts all device formats and passes through all data.

Supports:
- JSON, form-urlencoded, query params
- device_serial from: body, X-Device-Serial header, SN query param
- device_secret from: body, X-Device-Secret header
- uid from: uid, biometric_uid, user_id, PIN, UserID (case-insensitive)
- timestamp: Unix (int/float), ISO, "YYYY-MM-DD HH:MM:SS", etc.
- Preserves ALL extra fields in the payload for full data capture.
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from django.http import HttpRequest
from django.utils import timezone

logger = logging.getLogger("smart_attendance.sync")

# All known aliases for user identifier (case-insensitive keys)
UID_ALIASES = (
    "uid",
    "biometric_uid",
    "user_id",
    "userid",
    "pin",
    "PIN",
    "UserID",
    "employee_id",
    "employeeid",
    "badge_no",
    "badgeno",
    "card_no",
    "cardno",
)


def _get_case_insensitive(data: dict, keys: tuple, default=None) -> Any:
    """Get value from dict using any of the keys (case-insensitive)."""
    if not isinstance(data, dict):
        return default
    data_lower = {k.lower() if isinstance(k, str) else k: v for k, v in data.items()}
    for key in keys:
        if key in data:
            return data[key]
        key_lower = key.lower() if isinstance(key, str) else key
        for k, v in data_lower.items():
            if isinstance(k, str) and k.lower() == key_lower:
                return v
    return default


def _extract_uid(payload: dict) -> Optional[str]:
    """Extract user identifier from payload using all known aliases."""
    for alias in UID_ALIASES:
        val = _get_case_insensitive(payload, (alias,))
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _normalize_timestamp_flexible(value: Any) -> Optional[datetime]:
    """Parse timestamp from various formats: Unix, ISO, string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        try:
            if value > 1e12:  # milliseconds
                value = value / 1000.0
            elif value > 1e9:  # seconds
                pass
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (ValueError, OSError):
            return None
    else:
        s = str(value).strip()
        if not s:
            return None
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d-%m-%Y %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(s[:26], fmt)  # truncate microseconds if needed
                break
            except ValueError:
                continue
        else:
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    return dt


def _normalize_punch_type(value: Any) -> str:
    """ZKTeco often sends 0=Check In, 1=Check Out; normalize for display."""
    if value is None or value == "":
        return ""
    v = str(value).strip().lower()
    if v in ("0", "in", "checkin", "check_in", "1"):
        if v == "1":
            return "Check Out"
        return "Check In" if v in ("0", "in", "checkin", "check_in") else v
    if v in ("2", "out", "checkout", "check_out"):
        return "Check Out"
    return value.strip()


def _parse_tab_separated(line: str) -> Optional[dict]:
    """Parse ZKTeco tab-separated: PIN\\ttimestamp\\tpunch\\t... or PIN\\tDateTime\\tPunchType\\tDeviceID\\t..."""
    parts = line.strip().split("\t")
    if len(parts) < 2:
        return None
    punch_raw = parts[2].strip() if len(parts) > 2 else ""
    return {
        "uid": parts[0].strip(),
        "timestamp": parts[1].strip(),
        "punch_type": _normalize_punch_type(punch_raw) if punch_raw else "",
        "verify_mode": parts[3].strip() if len(parts) > 3 else "",
    }


def _parse_request_body(request: HttpRequest) -> Tuple[dict, dict]:
    """
    Parse request body into (data, raw_dict).
    Tries JSON, form data, then raw text (tab-separated ZKTeco format).
    """
    data = {}
    raw = {}
    content_type = (request.content_type or "").lower()

    try:
        body = request.body.decode("utf-8", errors="replace").strip() if request.body else ""
        if body and ("application/json" in content_type or body.startswith("{")):
            try:
                data = json.loads(body)
                raw = dict(data) if isinstance(data, dict) else {"_raw": data}
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
    except Exception:
        pass

    if not data and hasattr(request, "POST") and request.POST:
        data = dict(request.POST)
        raw = dict(data)
        for k, v in list(data.items()):
            if isinstance(v, (list, tuple)) and len(v) == 1:
                data[k] = v[0]
                raw[k] = v[0]

    if not data and hasattr(request, "GET") and request.GET:
        data = dict(request.GET)
        raw = dict(data)
        for k, v in list(data.items()):
            if isinstance(v, (list, tuple)) and len(v) == 1:
                data[k] = v[0]
                raw[k] = v[0]

    if not data and request.body:
        try:
            body = request.body.decode("utf-8", errors="replace")
            ts_parsed = _parse_tab_separated(body)
            if ts_parsed:
                data = ts_parsed
                raw = dict(ts_parsed)
        except Exception:
            pass

    return data, raw


def parse_push_payload(request: HttpRequest) -> Tuple[Optional[dict], Optional[str], Optional[str], Optional[str]]:
    """
    Parse biometric push request into normalized payload + device_serial + device_secret.

    Returns: (payload, device_serial, device_secret, error_message)
    - payload: Full dict with all fields, normalized uid/timestamp
    - On error: (None, None, None, "error message")
    """
    body_data, raw_body = _parse_request_body(request)

    # Merge: body + query params + any single-log wrapper
    payload = dict(raw_body)
    if request.GET:
        for k, v in request.GET.items():
            if k not in payload:
                payload[k] = v

    # Handle wrapped formats: { "log": {...} } or { "data": {...} }
    for wrapper in ("log", "data", "attendance", "record", "payload"):
        val = payload.get(wrapper)
        if isinstance(val, dict):
            payload = {**payload, **val}
            break
        if isinstance(val, str) and "\t" in val:
            ts_parsed = _parse_tab_separated(val)
            if ts_parsed:
                payload = {**payload, **ts_parsed}
            break

    # Handle array format: [{...}] – take first item
    if isinstance(payload.get("logs"), list) and payload["logs"]:
        first = payload["logs"][0]
        if isinstance(first, dict):
            payload = {**payload, **first}

    # Extract device_serial from multiple sources (strip so device/app stay in sync)
    device_serial = (
        _get_case_insensitive(payload, ("device_serial", "serial", "sn", "device_sn"))
        or (request.headers.get("X-Device-Serial") or request.headers.get("X-SN"))
        or request.GET.get("SN")
        or request.GET.get("sn")
    )
    if device_serial is not None:
        device_serial = str(device_serial).strip() if device_serial else ""
    else:
        device_serial = ""

    # Extract device_secret from multiple sources (strip for consistent auth)
    device_secret = (
        _get_case_insensitive(payload, ("device_secret", "secret", "token", "api_key"))
        or request.headers.get("X-Device-Secret")
        or (request.headers.get("Authorization") or "").replace("Bearer ", "").strip()
        or request.GET.get("secret")
    )
    if device_secret is not None:
        device_secret = str(device_secret).strip() if device_secret else ""
    else:
        device_secret = ""

    # Extract and normalize uid
    uid = _extract_uid(payload)
    if not uid:
        return None, device_serial, device_secret, "User identifier required (uid, biometric_uid, user_id, PIN, etc.)"

    payload["uid"] = uid

    # Extract and normalize timestamp
    ts_raw = _get_case_insensitive(
        payload,
        ("timestamp", "time", "datetime", "punch_time", "punchtime", "created_at"),
    )
    ts = _normalize_timestamp_flexible(ts_raw)
    if not ts:
        return None, device_serial, device_secret, "Valid timestamp required"

    payload["timestamp"] = ts.isoformat()

    # Normalize optional fields (preserve originals if different)
    for field, aliases in (
        ("verify_mode", ("verify_mode", "verifymode", "verify", "status")),
        ("punch_type", ("punch_type", "punchtype", "punch", "type", "inout")),
        ("work_code", ("work_code", "workcode", "work_code")),
    ):
        if field not in payload or not str(payload.get(field, "")).strip():
            val = _get_case_insensitive(payload, aliases)
            if val is not None:
                payload[field] = str(val) if val else ""
        if field not in payload:
            payload[field] = ""
    # ZKTeco: normalize punch_type 0/1 to Check In / Check Out
    if payload.get("punch_type"):
        payload["punch_type"] = _normalize_punch_type(payload["punch_type"])

    payload["device_serial"] = device_serial or ""
    if not device_serial:
        return None, None, device_secret, "device_serial required (body, X-Device-Serial header, or SN query param)"

    return payload, device_serial, device_secret, None
