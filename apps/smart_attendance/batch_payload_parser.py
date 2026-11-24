"""
Flexible batch payload parser – accepts array of logs in any format.
Extracts device_serial and device_secret, normalizes each log, preserves all extra fields.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple

from django.http import HttpRequest

from .payload_parser import (
    UID_ALIASES,
    _extract_uid,
    _get_case_insensitive,
    _normalize_timestamp_flexible,
    _parse_request_body,
)

logger = logging.getLogger("smart_attendance.sync")


def parse_batch_push_payload(request: HttpRequest) -> Tuple[Optional[str], Optional[str], List[dict], Optional[str]]:
    """
    Parse batch push request.

    Returns: (device_serial, device_secret, logs, error_message)
    - logs: List of normalized payload dicts (full data preserved)
    - On error: (None, None, [], "error message")
    """
    body_data, raw_body = _parse_request_body(request)
    payload = dict(raw_body)

    if request.GET:
        for k, v in request.GET.items():
            if k not in payload:
                payload[k] = v

    # Extract device_serial
    device_serial = (
        _get_case_insensitive(payload, ("device_serial", "serial", "sn", "device_sn"))
        or (request.headers.get("X-Device-Serial") or request.headers.get("X-SN"))
        or request.GET.get("SN")
        or request.GET.get("sn")
    )
    if device_serial and not isinstance(device_serial, str):
        device_serial = str(device_serial)
    if not device_serial:
        return None, None, [], "device_serial required"

    # Extract device_secret
    device_secret = (
        _get_case_insensitive(payload, ("device_secret", "secret", "token", "api_key"))
        or request.headers.get("X-Device-Secret")
        or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
        or request.GET.get("secret")
    )
    device_secret = str(device_secret) if device_secret else ""

    # Get logs array – multiple possible keys
    logs_raw = None
    for key in ("logs", "log", "data", "records", "attendance", "attendance_logs", "items"):
        val = payload.get(key)
        if isinstance(val, list):
            logs_raw = val
            break

    if not logs_raw:
        return None, None, [], "logs array required (logs, log, data, records, etc.)"

    logs = []
    for i, item in enumerate(logs_raw):
        if not isinstance(item, dict):
            continue
        log = dict(item)
        uid = _extract_uid(log)
        if not uid:
            logger.debug("Skipping batch item %s: no uid", i)
            continue
        log["uid"] = uid
        ts_raw = _get_case_insensitive(
            log,
            ("timestamp", "time", "datetime", "punch_time", "punchtime", "created_at"),
        )
        ts = _normalize_timestamp_flexible(ts_raw)
        if not ts:
            logger.debug("Skipping batch item %s: invalid timestamp", i)
            continue
        log["timestamp"] = ts.isoformat()
        for field, aliases in (
            ("verify_mode", ("verify_mode", "verifymode", "verify", "status")),
            ("punch_type", ("punch_type", "punchtype", "punch", "type", "inout")),
            ("work_code", ("work_code", "workcode")),
        ):
            if field not in log or not str(log.get(field, "")).strip():
                val = _get_case_insensitive(log, aliases)
                if val is not None:
                    log[field] = str(val) if val else ""
            if field not in log:
                log[field] = ""
        log["device_serial"] = device_serial
        logs.append(log)

    return device_serial, device_secret, logs, None
