"""
Device auto-discovery – scans network for biometric devices and auto-registers.

Scans 192.168.0.1–192.168.0.255 by default (configurable).
"""
from ..device_discovery import discover_devices_for_tenant

__all__ = ["discover_devices_for_tenant"]
