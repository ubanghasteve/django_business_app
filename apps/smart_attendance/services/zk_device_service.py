"""
ZKTeco device engine – full protocol integration.

Provides connect_device, disconnect_device, get_device_users, get_attendance_logs,
get_device_info, and ping_device for ZKTeco biometric devices.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("smart_attendance.device")


def _get_zk():
    try:
        from zk import ZK
        return ZK
    except ImportError:
        logger.error("pyzk not installed. Run: pip install pyzk")
        return None


def connect_device(ip: str, port: int = 4370, timeout: int = 5):
    """
    Connect to a ZKTeco device. Returns connection object or None.
    """
    ZK = _get_zk()
    if not ZK:
        return None
    try:
        zk = ZK(ip, port=port, timeout=timeout)
        conn = zk.connect()
        return conn
    except Exception as exc:
        logger.warning("ZKTeco connect failed ip=%s port=%s: %s", ip, port, exc)
        return None


def disconnect_device(conn) -> None:
    """
    Disconnect from a ZKTeco device.
    """
    if conn:
        try:
            conn.disconnect()
        except Exception:
            pass


def get_device_users(conn) -> List[Dict[str, Any]]:
    """
    Fetch enrolled users from device. Returns list of dicts with user_id, name, etc.
    """
    if not conn:
        return []
    try:
        conn.disable_device()
        users = conn.get_users()
        conn.enable_device()
        return [
            {
                "user_id": getattr(u, "user_id", getattr(u, "uid", "")),
                "name": getattr(u, "name", ""),
                "privilege": getattr(u, "privilege", 0),
                "password": getattr(u, "password", ""),
                "group_id": getattr(u, "group_id", ""),
                "card": getattr(u, "card", ""),
            }
            for u in (users or [])
        ]
    except Exception as exc:
        logger.warning("get_device_users failed: %s", exc)
        return []


def get_attendance_logs(conn) -> List[Dict[str, Any]]:
    """
    Fetch all attendance logs from device.
    """
    if not conn:
        return []
    try:
        conn.disable_device()
        attendances = conn.get_attendance()
        conn.enable_device()
        result = []
        for att in attendances or []:
            ts = att.timestamp
            result.append({
                "user_id": getattr(att, "user_id", getattr(att, "uid", "")),
                "timestamp": ts,
                "status": getattr(att, "status", 0),
                "punch": getattr(att, "punch", 0),
                "uid": getattr(att, "uid", 0),
            })
        return result
    except Exception as exc:
        logger.warning("get_attendance_logs failed: %s", exc)
        return []


def get_device_info(conn) -> Optional[Dict[str, Any]]:
    """
    Fetch device information (serial, platform, firmware, etc.).
    """
    if not conn:
        return None
    try:
        info = ""
        if hasattr(conn, "get_firmware_version"):
            info = conn.get_firmware_version() or ""
        platform = ""
        if hasattr(conn, "get_platform"):
            p = conn.get_platform
            platform = p() if callable(p) else str(p)
        return {
            "firmware": info,
            "platform": platform,
            "serial_number": getattr(conn, "serialnumber", "") or "",
            "device_name": getattr(conn, "device_name", "") or "",
        }
    except Exception as exc:
        logger.warning("get_device_info failed: %s", exc)
        return None


def ping_device(ip: str, port: int = 4370, timeout: int = 3) -> bool:
    """
    Check if device is reachable. Returns True if connection succeeds.
    """
    conn = connect_device(ip, port, timeout)
    if conn:
        disconnect_device(conn)
        return True
    return False
