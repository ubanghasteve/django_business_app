"""
Security Utilities for Device Detection, IP Geolocation, and Session Tracking.

This module provides functions for:
- Extracting client IP addresses from requests
- Parsing user agent strings to detect device/browser/OS info
- Looking up geographic location from IP addresses
- Creating and managing user sessions

IMPORTANT: Each login creates a unique session entry. Even if the same user
logs in from multiple devices (mobile, desktop), each device's IP address
and session is tracked separately with individual login/logout timestamps.
"""

import re
import requests
import logging
import socket
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger(__name__)


def get_account_for_activity(request=None, user=None):
    """
    Get the Account for activity logging. Prefer request.company.account (tenant context)
    so team members and owners are scoped to the same account. Fall back to user.account.
    """
    if request and getattr(request, 'company', None):
        company = request.company
        if getattr(company, 'account_id', None):
            return company.account
        if hasattr(company, 'account') and company.account_id:
            return company.account
    if user and getattr(user, 'account_id', None):
        return user.account
    return None


def is_valid_ip(ip_address):
    """
    Validate if the given string is a valid IP address (IPv4 or IPv6).
    
    Args:
        ip_address: String to validate
        
    Returns:
        bool: True if valid IP address, False otherwise
    """
    if not ip_address:
        return False
    
    # Try IPv4
    try:
        socket.inet_pton(socket.AF_INET, ip_address)
        return True
    except socket.error:
        pass
    
    # Try IPv6
    try:
        socket.inet_pton(socket.AF_INET6, ip_address)
        return True
    except socket.error:
        pass
    
    return False


def is_private_ip(ip_address):
    """
    Check if an IP address is a private/local IP.
    
    Private IP ranges:
    - 10.0.0.0 to 10.255.255.255
    - 172.16.0.0 to 172.31.255.255
    - 192.168.0.0 to 192.168.255.255
    - 127.0.0.0 to 127.255.255.255 (loopback)
    - ::1 (IPv6 loopback)
    
    Args:
        ip_address: IP address to check
        
    Returns:
        bool: True if private IP, False otherwise
    """
    if not ip_address:
        return True
    
    private_patterns = [
        r'^127\.',           # Loopback
        r'^10\.',            # Class A private
        r'^192\.168\.',      # Class C private
        r'^172\.(1[6-9]|2[0-9]|3[0-1])\.',  # Class B private
        r'^0\.',             # Current network
        r'^169\.254\.',      # Link-local
        r'^::1$',            # IPv6 loopback
        r'^fe80:',           # IPv6 link-local
        r'^fc00:',           # IPv6 unique local
        r'^fd',              # IPv6 unique local
        r'^localhost$',
    ]
    
    ip_str = str(ip_address).lower()
    for pattern in private_patterns:
        if re.match(pattern, ip_str):
            return True
    
    return False


def get_client_ip(request):
    """
    Extract the client's ACTUAL IP address from the request.
    
    This function is critical for security tracking. It handles:
    - Direct connections (REMOTE_ADDR)
    - Connections through proxies/load balancers (X-Forwarded-For)
    - Connections through CDNs like Cloudflare (CF-Connecting-IP)
    
    The function prioritizes getting the ORIGINAL client IP, not the proxy IP.
    
    IMPORTANT: For accurate IP tracking:
    - Mobile devices will show their cellular or WiFi network IP
    - Desktop/laptop will show their network's public IP
    - Each device behind a router shares the same public IP
    - VPN users will show their VPN's IP
    
    Args:
        request: Django HttpRequest object
        
    Returns:
        str: Client IP address or None
    """
    ip_address = None
    
    # Priority order for extracting client IP (most reliable first)
    # 1. Cloudflare (most reliable if using Cloudflare)
    cf_ip = request.META.get('HTTP_CF_CONNECTING_IP')
    if cf_ip and is_valid_ip(cf_ip.split(',')[0].strip()):
        ip_address = cf_ip.split(',')[0].strip()
        logger.debug(f"IP from Cloudflare CF-Connecting-IP: {ip_address}")
        return ip_address
    
    # 2. X-Real-IP (commonly set by Nginx/reverse proxies)
    real_ip = request.META.get('HTTP_X_REAL_IP')
    if real_ip and is_valid_ip(real_ip.strip()):
        ip_address = real_ip.strip()
        logger.debug(f"IP from X-Real-IP: {ip_address}")
        return ip_address
    
    # 3. X-Forwarded-For (standard proxy header)
    # Format: client, proxy1, proxy2, ...
    # We want the FIRST IP which is the original client
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # Split and get all IPs
        forwarded_ips = [ip.strip() for ip in x_forwarded_for.split(',')]
        # Get the first valid, non-private IP (the actual client)
        for ip in forwarded_ips:
            if is_valid_ip(ip):
                # In production, prefer the first IP (actual client)
                # unless it's a private IP (internal proxy)
                if not is_private_ip(ip):
                    ip_address = ip
                    logger.debug(f"IP from X-Forwarded-For (public): {ip_address}")
                    return ip_address
        # If all IPs are private, use the first one
        if forwarded_ips and is_valid_ip(forwarded_ips[0]):
            ip_address = forwarded_ips[0]
            logger.debug(f"IP from X-Forwarded-For (first): {ip_address}")
            return ip_address
    
    # 4. Forwarded header (RFC 7239) - for="client"
    forwarded = request.META.get('HTTP_FORWARDED')
    if forwarded:
        for part in forwarded.split(';'):
            part = part.strip().lower()
            if part.startswith('for='):
                ip = part[4:].strip().strip('"[]')
                if ip and is_valid_ip(ip) and not is_private_ip(ip):
                    ip_address = ip
                    logger.debug(f"IP from Forwarded header: {ip_address}")
                    return ip_address
    
    # 5. Other proxy headers
    other_headers = [
        'HTTP_CLIENT_IP',
        'HTTP_X_CLIENT_IP',
        'HTTP_X_CLUSTER_CLIENT_IP',
        'HTTP_FORWARDED_FOR',
        'HTTP_TRUE_CLIENT_IP',  # Akamai
        'HTTP_X_FORWARDED',
    ]
    
    for header in other_headers:
        header_value = request.META.get(header)
        if header_value:
            ip = header_value.split(',')[0].strip()
            if is_valid_ip(ip):
                ip_address = ip
                logger.debug(f"IP from {header}: {ip_address}")
                return ip_address
    
    # 6. Fall back to REMOTE_ADDR (direct connection)
    remote_addr = request.META.get('REMOTE_ADDR')
    if remote_addr and is_valid_ip(remote_addr):
        ip_address = remote_addr
        logger.debug(f"IP from REMOTE_ADDR: {ip_address}")
    
    return ip_address


def parse_user_agent(user_agent_string):
    """
    Parse the user agent string to extract device, browser, and OS information.
    
    Args:
        user_agent_string: The User-Agent header string
        
    Returns:
        dict: Dictionary containing device, browser, and OS information
    """
    result = {
        'device_type': 'Desktop',
        'device_brand': '',
        'device_model': '',
        'browser_name': '',
        'browser_version': '',
        'os_name': '',
        'os_version': '',
        'is_mobile': False,
        'is_tablet': False,
        'is_bot': False,
    }
    
    if not user_agent_string:
        return result
    
    ua = user_agent_string.lower()
    
    # Detect if it's a bot/crawler
    bot_indicators = ['bot', 'crawler', 'spider', 'scraper', 'headless', 'phantom']
    if any(bot in ua for bot in bot_indicators):
        result['is_bot'] = True
        result['device_type'] = 'Bot/Crawler'
        return result
    
    # Detect device type and brand
    if 'iphone' in ua:
        result['device_type'] = 'Mobile'
        result['device_brand'] = 'Apple'
        result['device_model'] = 'iPhone'
        result['is_mobile'] = True
        # Try to extract iPhone model
        iphone_match = re.search(r'iphone\s*([\d,]+)?', ua)
        if iphone_match and iphone_match.group(1):
            result['device_model'] = f"iPhone {iphone_match.group(1)}"
    elif 'ipad' in ua:
        result['device_type'] = 'Tablet'
        result['device_brand'] = 'Apple'
        result['device_model'] = 'iPad'
        result['is_tablet'] = True
    elif 'android' in ua:
        # Android tablets: tablet, pad, sm-t, sm-p, gt-p, nexus 7/9, kindle, silk
        tablet_indicators = (
            'tablet' in ua or 'sm-t' in ua or 'sm-p' in ua or 'gt-p' in ua or
            'pad' in ua or 'kindle' in ua or 'silk' in ua or 'nexus 7' in ua or
            'nexus 9' in ua or 'tab a' in ua or 'tab s' in ua
        )
        # Android without "Mobile" often indicates tablet
        if tablet_indicators:
            result['device_type'] = 'Tablet'
            result['is_tablet'] = True
        elif 'mobile' in ua:
            result['device_type'] = 'Mobile'
            result['is_mobile'] = True
        else:
            # Android UA without "Mobile" - often tablet; default Mobile if unclear
            # Client-side hint (device_type_hint) provides accurate detection for tablets
            result['device_type'] = 'Mobile'
            result['is_mobile'] = True
        
        # Try to detect Android device brand
        if 'samsung' in ua or 'sm-' in ua:
            result['device_brand'] = 'Samsung'
            model_match = re.search(r'(sm-[a-z]\d+)', ua)
            if model_match:
                result['device_model'] = model_match.group(1).upper()
        elif 'pixel' in ua:
            result['device_brand'] = 'Google'
            result['device_model'] = 'Pixel'
        elif 'huawei' in ua:
            result['device_brand'] = 'Huawei'
        elif 'xiaomi' in ua or 'redmi' in ua or 'mi ' in ua:
            result['device_brand'] = 'Xiaomi'
        elif 'oppo' in ua:
            result['device_brand'] = 'Oppo'
        elif 'vivo' in ua:
            result['device_brand'] = 'Vivo'
        elif 'oneplus' in ua:
            result['device_brand'] = 'OnePlus'
        elif 'lg' in ua:
            result['device_brand'] = 'LG'
        elif 'nokia' in ua:
            result['device_brand'] = 'Nokia'
        elif 'motorola' in ua or 'moto' in ua:
            result['device_brand'] = 'Motorola'
        elif 'tecno' in ua:
            result['device_brand'] = 'Tecno'
        elif 'infinix' in ua:
            result['device_brand'] = 'Infinix'
        elif 'itel' in ua:
            result['device_brand'] = 'Itel'
        else:
            result['device_brand'] = 'Android'
    elif 'windows phone' in ua:
        result['device_type'] = 'Mobile'
        result['device_brand'] = 'Windows'
        result['device_model'] = 'Phone'
        result['is_mobile'] = True
    elif 'macintosh' in ua or 'mac os' in ua:
        result['device_type'] = 'Desktop'
        result['device_brand'] = 'Apple'
        result['device_model'] = 'Mac'
    elif 'windows' in ua:
        result['device_type'] = 'Desktop'
        result['device_brand'] = 'PC'
        result['device_model'] = 'Windows PC'
    elif 'linux' in ua:
        result['device_type'] = 'Desktop'
        result['device_brand'] = 'PC'
        result['device_model'] = 'Linux PC'
    
    # Detect operating system
    if 'windows nt 10' in ua:
        result['os_name'] = 'Windows'
        result['os_version'] = '10/11'
    elif 'windows nt 6.3' in ua:
        result['os_name'] = 'Windows'
        result['os_version'] = '8.1'
    elif 'windows nt 6.2' in ua:
        result['os_name'] = 'Windows'
        result['os_version'] = '8'
    elif 'windows nt 6.1' in ua:
        result['os_name'] = 'Windows'
        result['os_version'] = '7'
    elif 'mac os x' in ua:
        result['os_name'] = 'macOS'
        os_match = re.search(r'mac os x (\d+[._]\d+(?:[._]\d+)?)', ua)
        if os_match:
            result['os_version'] = os_match.group(1).replace('_', '.')
    elif 'android' in ua:
        result['os_name'] = 'Android'
        android_match = re.search(r'android (\d+(?:\.\d+)?)', ua)
        if android_match:
            result['os_version'] = android_match.group(1)
    elif 'iphone os' in ua or 'cpu os' in ua:
        result['os_name'] = 'iOS'
        ios_match = re.search(r'(?:iphone os|cpu os) (\d+[._]\d+)', ua)
        if ios_match:
            result['os_version'] = ios_match.group(1).replace('_', '.')
    elif 'linux' in ua:
        result['os_name'] = 'Linux'
    
    # Detect browser
    if 'edg/' in ua or 'edge/' in ua:
        result['browser_name'] = 'Microsoft Edge'
        edge_match = re.search(r'edg[e]?/(\d+(?:\.\d+)?)', ua)
        if edge_match:
            result['browser_version'] = edge_match.group(1)
    elif 'opr/' in ua or 'opera' in ua:
        result['browser_name'] = 'Opera'
        opera_match = re.search(r'(?:opr|opera)[/\s](\d+(?:\.\d+)?)', ua)
        if opera_match:
            result['browser_version'] = opera_match.group(1)
    elif 'chrome' in ua and 'safari' in ua:
        result['browser_name'] = 'Chrome'
        chrome_match = re.search(r'chrome/(\d+(?:\.\d+)?)', ua)
        if chrome_match:
            result['browser_version'] = chrome_match.group(1)
    elif 'firefox' in ua:
        result['browser_name'] = 'Firefox'
        ff_match = re.search(r'firefox/(\d+(?:\.\d+)?)', ua)
        if ff_match:
            result['browser_version'] = ff_match.group(1)
    elif 'safari' in ua and 'chrome' not in ua:
        result['browser_name'] = 'Safari'
        safari_match = re.search(r'version/(\d+(?:\.\d+)?)', ua)
        if safari_match:
            result['browser_version'] = safari_match.group(1)
    elif 'msie' in ua or 'trident' in ua:
        result['browser_name'] = 'Internet Explorer'
        ie_match = re.search(r'(?:msie |rv:)(\d+(?:\.\d+)?)', ua)
        if ie_match:
            result['browser_version'] = ie_match.group(1)
    
    return result


def _reverse_geocode_coordinates(lat, lon):
    """
    Server-side reverse geocode of GPS coordinates to get city/region/country.
    Used as fallback when client-side Nominatim returns empty address.
    
    Args:
        lat: Latitude (float)
        lon: Longitude (float)
        
    Returns:
        dict with city, region, country keys, or None on failure
    """
    try:
        url = (
            f'https://nominatim.openstreetmap.org/reverse'
            f'?format=json&lat={lat}&lon={lon}&zoom=10&addressdetails=1'
        )
        resp = requests.get(
            url,
            timeout=5,
            headers={'User-Agent': 'BusinessApp/1.0 (Location-Security)'}
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        addr = data.get('address') or {}
        city = (
            addr.get('city') or addr.get('town') or addr.get('village')
            or addr.get('municipality') or addr.get('county')
            or addr.get('state_district') or addr.get('suburb')
            or addr.get('neighbourhood') or ''
        )
        region = addr.get('state') or addr.get('region') or addr.get('province') or ''
        country = addr.get('country') or ''
        if city or region or country:
            return {'city': city, 'region': region, 'country': country}
    except Exception as e:
        logger.debug(f"Server reverse geocode failed: {e}")
    return None


def get_ip_geolocation(ip_address):
    """
    Get geographic location information from an IP address.
    Uses free IP geolocation API (ip-api.com).
    
    IMPORTANT: This provides the location of the IP address, which represents:
    - For public IPs: The approximate geographic location of the network
    - For mobile data: The carrier's IP location (may not be exact user location)
    - For WiFi: The ISP's assigned IP location
    
    Args:
        ip_address: The IP address to lookup
        
    Returns:
        dict: Dictionary containing location information
    """
    result = {
        'city': '',
        'region': '',
        'country': '',
        'country_code': '',
        'latitude': None,
        'longitude': None,
        'timezone': '',
        'isp': '',
        'success': False,
        'ip_type': 'unknown',  # 'public', 'private', 'unknown'
    }
    
    if not ip_address:
        result['city'] = 'Unknown'
        result['country'] = 'Unknown'
        result['ip_type'] = 'unknown'
        return result
    
    # Check for private/local IPs
    if is_private_ip(ip_address):
        result['city'] = 'Local Network'
        result['country'] = 'Local'
        result['ip_type'] = 'private'
        result['isp'] = 'Local/Private Network'
        logger.info(f"Private IP detected: {ip_address} - Location set to Local Network")
        return result
    
    result['ip_type'] = 'public'
    
    def _apply_ipapi_data(data):
        """Apply ip-api.com response to result."""
        result['city'] = data.get('city') or data.get('cityName') or 'Unknown City'
        result['region'] = data.get('regionName') or data.get('region') or ''
        result['country'] = data.get('country') or 'Unknown Country'
        result['country_code'] = data.get('countryCode') or ''
        result['latitude'] = data.get('lat')
        result['longitude'] = data.get('lon')
        result['timezone'] = data.get('timezone') or ''
        result['isp'] = (data.get('isp') or data.get('org') or '').strip()
        result['success'] = True
    
    # Country code to full name (for ipinfo fallback which returns codes only)
    _country_names = {
        'US': 'United States', 'GB': 'United Kingdom', 'NG': 'Nigeria', 'KE': 'Kenya',
        'GH': 'Ghana', 'ZA': 'South Africa', 'EG': 'Egypt', 'ET': 'Ethiopia',
        'TZ': 'Tanzania', 'UG': 'Uganda', 'IN': 'India', 'PK': 'Pakistan',
        'BD': 'Bangladesh', 'PH': 'Philippines', 'VN': 'Vietnam', 'ID': 'Indonesia',
        'MY': 'Malaysia', 'SG': 'Singapore', 'AU': 'Australia', 'CA': 'Canada',
        'DE': 'Germany', 'FR': 'France', 'IT': 'Italy', 'ES': 'Spain',
        'BR': 'Brazil', 'MX': 'Mexico', 'CN': 'China', 'JP': 'Japan',
    }
    
    def _apply_ipinfo_data(data):
        """Apply ipinfo.io response to result (fallback)."""
        result['city'] = data.get('city') or 'Unknown City'
        result['region'] = data.get('region') or ''
        cc = (data.get('country') or '').strip()
        result['country_code'] = cc
        result['country'] = _country_names.get(cc.upper(), cc) if cc else 'Unknown Country'
        if data.get('loc'):
            parts = data['loc'].split(',')
            if len(parts) == 2:
                try:
                    result['latitude'] = float(parts[0].strip())
                    result['longitude'] = float(parts[1].strip())
                except (ValueError, TypeError):
                    pass
        result['timezone'] = data.get('timezone') or ''
        result['isp'] = (data.get('org') or '').strip()
        result['success'] = True
    
    # Try ip-api.com first (free, good coverage)
    try:
        response = requests.get(
            f'http://ip-api.com/json/{ip_address}',
            timeout=8,
            params={
                'fields': 'status,message,country,countryCode,region,regionName,city,lat,lon,timezone,isp,org,query'
            }
        )
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                _apply_ipapi_data(data)
                logger.info(
                    f"Geolocation for IP {ip_address}: "
                    f"{result['city']}, {result['country']} ({result['isp'] or 'N/A'})"
                )
                return result
    except Exception as e:
        logger.debug(f"ip-api.com failed for {ip_address}: {e}")
    
    # Fallback: ipinfo.io (free 50k/month, often more accurate for mobile/carriers)
    try:
        response = requests.get(
            f'https://ipinfo.io/{ip_address}/json',
            timeout=8,
            headers={'Accept': 'application/json'}
        )
        if response.status_code == 200:
            data = response.json()
            if data and not data.get('error'):
                _apply_ipinfo_data(data)
                logger.info(
                    f"Geolocation (ipinfo fallback) for IP {ip_address}: "
                    f"{result['city']}, {result['country']}"
                )
                return result
    except Exception as e:
        logger.debug(f"ipinfo.io failed for {ip_address}: {e}")
    
    # Final fallback: ip-api batch endpoint (single-IP) - sometimes more reliable
    if not result['success']:
        try:
            response = requests.get(
                f'https://ip-api.com/json/{ip_address}?fields=status,city,regionName,country,countryCode,lat,lon,timezone,isp',
                timeout=8
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    _apply_ipapi_data(data)
                    return result
        except Exception:
            pass
    
    if not result['success']:
        result['city'] = 'Unknown'
        result['country'] = 'Unknown'
        logger.warning(f"All geolocation providers failed for IP {ip_address}")
    
    return result


def create_user_session(request, user, client_reported_ip=None, gps_location=None, sub_user=None,
                        client_device_type=None):
    """
    Create a new UserSession record for a login event.
    
    Args:
        request: Django HttpRequest object
        user: The User object who logged in
        client_reported_ip: Optional IP fetched by the client (e.g. from api.ipify.org).
            When provided and valid, this is preferred over server-derived IP to ensure
            the stored IP matches what the user sees when checking their IP on phone/device.
        gps_location: Optional dict with GPS location data from browser geolocation API:
            {
                'latitude': float,
                'longitude': float,
                'city': str,
                'region': str,
                'country': str,
                'accuracy': float (in meters)
            }
    
    IMPORTANT: Each login creates a UNIQUE session record, even if:
    - The same user logs in from multiple devices
    - Multiple people share the same account
    - The same device logs in at different times
    
    This allows tracking:
    - Each device's IP address separately
    - Each login's timestamp (login_time is auto-set)
    - Each logout's timestamp (logout_time is set on logout)
    
    Args:
        request: Django HttpRequest object
        user: The User object who logged in
        
    Returns:
        UserSession: The created session object
    """
    from .models import UserSession
    
    # Get client information - CRITICAL for tracking
    # Prefer client-reported IP when valid (matches what user sees on ipify/whatismyip, especially on mobile)
    ip_address = None
    if client_reported_ip and is_valid_ip(client_reported_ip) and not is_private_ip(client_reported_ip):
        ip_address = client_reported_ip.strip()
        logger.info(f"Using client-reported IP for session: {ip_address}")
    if not ip_address:
        ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    session_key = request.session.session_key
    
    # Ensure we have a session key without creating a NEW session (create() would
    # generate a new key and the browser might keep the old one, losing auth).
    if not session_key:
        request.session.save()
        session_key = request.session.session_key
    
    # Parse device information (server-side UA parsing)
    device_info = parse_user_agent(user_agent)
    # Prefer client-reported device type (accurate for iPad iOS 13+ which reports as Mac)
    if client_device_type and client_device_type.strip().lower() in ('mobile', 'tablet', 'desktop'):
        device_info['device_type'] = client_device_type.strip().title()
        logger.info(f"Using client-reported device type: {device_info['device_type']}")
    
    # Get location information - prefer GPS over IP geolocation
    if gps_location and gps_location.get('latitude') is not None and gps_location.get('longitude') is not None:
        lat = gps_location.get('latitude')
        lon = gps_location.get('longitude')
        city = gps_location.get('city') or ''
        region = gps_location.get('region') or ''
        country = gps_location.get('country') or ''

        # Server-side reverse geocode fallback if client didn't return address
        if not city or not country:
            server_addr = _reverse_geocode_coordinates(lat, lon)
            if server_addr:
                city = city or server_addr.get('city', '')
                region = region or server_addr.get('region', '')
                country = country or server_addr.get('country', '')

        accuracy = gps_location.get('accuracy') or 0
        try:
            accuracy = float(accuracy)
        except (TypeError, ValueError):
            accuracy = 0

        # Use GPS-based location (real-time, accurate)
        location_info = {
            'city': city or 'Unknown City',
            'region': region,
            'country': country or 'Unknown Country',
            'country_code': '',
            'latitude': lat,
            'longitude': lon,
            'timezone': '',
            'isp': f"GPS (±{accuracy:.0f}m)" if accuracy else "GPS (real-time)",
            'success': True,
            'ip_type': 'gps',
        }
        logger.info(
            f"Using GPS location for session: {location_info['city']}, {location_info['country']} "
            f"(Accuracy: ±{accuracy:.0f}m)"
        )
    else:
        # Fall back to IP-based geolocation
        location_info = get_ip_geolocation(ip_address)
        logger.info(f"Using IP-based location for session: {location_info['city']}, {location_info['country']}")
    
    # Log the session creation details for debugging
    logger.info(
        f"Creating session for user {user.email}: "
        f"IP={ip_address}, Device={device_info['device_type']} "
        f"({device_info['device_brand']} {device_info['device_model']}), "
        f"Browser={device_info['browser_name']}, OS={device_info['os_name']}, "
        f"Location={location_info['city']}, {location_info['country']}"
    )
    
    # Create the session record
    # login_time is automatically set by auto_now_add=True
    session = UserSession.objects.create(
        user=user,
        sub_user=sub_user,
        session_key=session_key,
        # Device info - for identifying the type of device
        device_type=device_info['device_type'],
        device_brand=device_info['device_brand'],
        device_model=device_info['device_model'],
        browser_name=device_info['browser_name'],
        browser_version=device_info['browser_version'],
        os_name=device_info['os_name'],
        os_version=device_info['os_version'],
        user_agent=user_agent,
        # Network info - THE ACTUAL IP ADDRESS OF THE DEVICE
        ip_address=ip_address,
        # Location info - derived from GPS (preferred) or IP address
        city=location_info['city'],
        region=location_info['region'],
        country=location_info['country'],
        country_code=location_info['country_code'],
        latitude=location_info['latitude'],
        longitude=location_info['longitude'],
        tz_name=location_info['timezone'],
        isp=location_info['isp'],
        # Status
        is_active=True,
    )
    
    logger.info(
        f"Session created: ID={session.id}, User={user.email}, "
        f"IP={ip_address}, Login Time={session.login_time}"
    )
    
    # Store session ID in the Django session for later reference (for logout tracking)
    request.session['security_session_id'] = str(session.id)
    
    # Check for suspicious activity
    check_suspicious_login(session, user)
    
    return session


def check_suspicious_login(session, user):
    """
    Check if a login appears suspicious based on various factors.
    
    Args:
        session: The UserSession object
        user: The User object
    """
    from .models import UserSession
    
    suspicious_reasons = []
    
    # Get recent sessions for this user
    recent_sessions = UserSession.objects.filter(
        user=user
    ).exclude(id=session.id).order_by('-login_time')[:10]
    
    if recent_sessions.exists():
        last_session = recent_sessions.first()
        
        # Check for different country
        if last_session.country and session.country:
            if last_session.country != session.country:
                # Check if login was within a short time (impossible travel)
                time_diff = (session.login_time - last_session.login_time).total_seconds()
                if time_diff < 3600:  # Within 1 hour
                    suspicious_reasons.append(
                        f"Login from different country ({session.country}) within 1 hour of previous login ({last_session.country})"
                    )
        
        # Check for new device
        known_devices = set(
            recent_sessions.values_list('device_type', 'browser_name', 'os_name')
        )
        current_device = (session.device_type, session.browser_name, session.os_name)
        if current_device not in known_devices and len(known_devices) >= 3:
            suspicious_reasons.append(
                f"New device type: {session.device_info} with {session.browser_name} on {session.os_name}"
            )
    
    if suspicious_reasons:
        session.is_suspicious = True
        session.suspicious_reason = '\n'.join(suspicious_reasons)
        session.save()


def end_user_session(request, user):
    """
    Mark a user session as ended (logged out).
    Always logs a LOGOUT activity so the event is never missing from the activity log.
    """
    from .models import UserSession, UserActivity
    
    session_id = request.session.get('security_session_id')
    current_ip = get_client_ip(request)
    account = get_account_for_activity(request=request, user=user)
    logout_logged = False
    
    if session_id:
        try:
            session = UserSession.objects.get(id=session_id)
            
            logger.info(
                f"Ending session: ID={session.id}, User={user.email}, "
                f"IP={session.ip_address}, Login Time={session.login_time}"
            )
            
            session.mark_logged_out()
            
            logger.info(
                f"Session ended: ID={session.id}, User={user.email}, "
                f"Logout Time={session.logout_time}, Duration={session.session_duration}"
            )
            
            who_logged = f"{session.sub_user.full_name} (team member)" if session.sub_user else (user.get_full_name() or user.email)
            UserActivity.log_activity(
                user=user,
                session=session,
                sub_user=session.sub_user,
                account=account,
                activity_type='LOGOUT',
                description=f"{who_logged} logged out from {session.device_info} ({session.location_info})",
                ip_address=current_ip or session.ip_address,
                user_agent=request.META.get('HTTP_USER_AGENT', session.user_agent),
            )
            logout_logged = True
        except UserSession.DoesNotExist:
            logger.warning(f"Session {session_id} not found for logout")
        except Exception as e:
            logger.exception(f"Error ending session {session_id}: {e}")
    
    if not logout_logged:
        # No security_session_id or session not found: try to close by session_key
        active_sessions = UserSession.objects.filter(
            user=user,
            is_active=True,
            session_key=request.session.session_key
        )
        for session in active_sessions:
            try:
                logger.info(f"Closing orphaned session: {session.id} for user {user.email}")
                session.mark_logged_out()
                who_logged = f"{session.sub_user.full_name} (team member)" if session.sub_user else (user.get_full_name() or user.email)
                UserActivity.log_activity(
                    user=user,
                    session=session,
                    sub_user=session.sub_user,
                    account=account,
                    activity_type='LOGOUT',
                    description=f"{who_logged} logged out from {session.device_info}",
                    ip_address=current_ip or session.ip_address,
                    user_agent=request.META.get('HTTP_USER_AGENT', session.user_agent),
                )
                logout_logged = True
            except Exception as e:
                logger.exception(f"Error closing session {session.id}: {e}")
    
    # Always log at least one LOGOUT so the event is never missing (e.g. missing session cookie)
    if not logout_logged:
        who_logged = user.get_full_name() or user.email
        sub_user_id = request.session.get('sub_user_id')
        sub_user = None
        if sub_user_id and user:
            try:
                from .models import SubUser
                sub_user = SubUser.objects.get(id=sub_user_id, linked_user=user)
                who_logged = f"{sub_user.full_name} (team member)"
            except (SubUser.DoesNotExist, ValueError, TypeError):
                pass
        UserActivity.log_activity(
            user=user,
            sub_user=sub_user,
            account=account,
            activity_type='LOGOUT',
            description=f"{who_logged} logged out",
            ip_address=current_ip,
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )


def get_active_sessions(user):
    """
    Get all active sessions for a user.
    
    Args:
        user: The User object
        
    Returns:
        QuerySet: Active UserSession objects
    """
    from .models import UserSession
    
    return UserSession.objects.filter(
        user=user,
        is_active=True
    ).order_by('-last_activity')


def terminate_session(session_id, user):
    """
    Terminate a specific session (remote logout).
    
    Args:
        session_id: The UUID of the session to terminate
        user: The User object (for verification)
        
    Returns:
        bool: True if successful, False otherwise
    """
    from .models import UserSession
    from django.contrib.sessions.models import Session
    
    try:
        session = UserSession.objects.get(id=session_id, user=user)
        
        # Delete the Django session if it exists
        if session.session_key:
            try:
                Session.objects.filter(session_key=session.session_key).delete()
            except Exception:
                pass
        
        session.mark_logged_out()
        return True
    except UserSession.DoesNotExist:
        return False


# Cache key and TTL for session keys force-logged out by admin (so login page can show message)
FORCE_LOGOUT_CACHE_KEY = 'security:force_logout_session_keys'
FORCE_LOGOUT_CACHE_TTL = 600  # 10 minutes


def get_account_and_session_user_ids(request):
    """
    Return (account, list of user ids) for the current request's account (company scope).
    Used for session listing and force-logout so the same set of users is always used.
    Includes: account owner + users with account=account + linked_user of each SubUser
    under this account (so team members are included even if their User.account is not set).
    """
    from django.contrib.auth import get_user_model
    from .models import SubUser

    User = get_user_model()
    user = request.user
    account = None
    if getattr(request, 'company', None) and getattr(request.company, 'account_id', None):
        account = getattr(request.company, 'account', None)
    if not account and getattr(user, 'account_id', None):
        account = user.account
    if not account:
        return None, []

    account_user_ids = set()
    if getattr(account, 'owner_id', None):
        account_user_ids.add(account.owner_id)
    account_user_ids.update(
        User.objects.filter(account=account).values_list('pk', flat=True)
    )
    account_user_ids.update(
        SubUser.objects.filter(
            account_owner__account=account,
        ).exclude(
            linked_user_id__isnull=True,
        ).values_list('linked_user_id', flat=True).distinct()
    )
    return account, list(account_user_ids)


def force_logout_all_account_sessions(request, exclude_current=True):
    """
    Force-logout ALL active sessions for the entire account (company).
    Deletes Django session rows so affected users are logged out immediately on next request.
    Multi-tenant safe: only sessions for users in request.user.account are terminated.

    Behavior when exclude_current=True (used by "Log out all users" button):
    - Only the current request's session (this browser/device) stays active.
    - All other sessions are terminated, including:
      - Every other user in the company (team members, etc.).
      - Any other session of the same user (company owner/admin) on other browsers or devices.
    So the company owner or admin who clicks the button remains logged in only on the device
    they are using; all other sessions—including their own on other devices—are logged out.

    Args:
        request: HttpRequest (must have authenticated user with account).
        exclude_current: If True, the current request's session is kept (admin stays logged in).

    Returns:
        int: Number of sessions terminated (Django sessions deleted + UserSession marked ended).
    """
    from django.contrib.sessions.models import Session
    from django.core.cache import cache
    from django.utils import timezone as django_timezone
    from .models import UserSession, UserActivity

    user = request.user
    account, account_user_ids = get_account_and_session_user_ids(request)
    if not account or not account_user_ids:
        return 0

    account_user_ids_set = set(account_user_ids)

    # Ensure we have a session key before excluding it, so we never accidentally delete
    # the current session's Django Session row (which would log out the admin who clicked).
    if exclude_current and not request.session.session_key:
        request.session.save()
    current_session_key = request.session.session_key if exclude_current else None

    # Find sessions to delete by reading Django's Session table directly (source of truth).
    # UserSession.session_key can be stale; decoding each Session guarantees we log out
    # every other user on this account.
    session_keys_to_delete = []
    now = django_timezone.now()
    for db_session in Session.objects.filter(expire_date__gte=now).iterator():
        if db_session.session_key == current_session_key:
            continue
        try:
            decoded = db_session.get_decoded()
            auth_user_id = decoded.get('_auth_user_id')
            if auth_user_id is None:
                continue
            uid = int(auth_user_id)
            if uid in account_user_ids_set:
                session_keys_to_delete.append(db_session.session_key)
        except (ValueError, TypeError, KeyError) as e:
            logger.debug("Skip session %s: %s", getattr(db_session, 'session_key', None), e)
            continue

    if not session_keys_to_delete:
        return 0

    # 1. Delete Django session rows so browsers are logged out immediately
    Session.objects.filter(session_key__in=session_keys_to_delete).delete()

    # 2. Mark UserSession records as ended (all account sessions we know about)
    user_sessions_to_end = UserSession.objects.filter(
        user_id__in=account_user_ids,
        is_active=True,
    ).exclude(session_key=current_session_key)
    for usess in user_sessions_to_end:
        try:
            usess.mark_logged_out()
        except Exception as e:
            logger.exception("Error marking UserSession %s as ended: %s", usess.id, e)

    # 3. Store deleted keys so login page can show "You were logged out by an administrator"
    try:
        existing = set(cache.get(FORCE_LOGOUT_CACHE_KEY) or [])
        existing.update(session_keys_to_delete)
        cache.set(FORCE_LOGOUT_CACHE_KEY, existing, timeout=FORCE_LOGOUT_CACHE_TTL)
    except Exception as e:
        logger.debug("Could not store force-logout keys in cache: %s", e)

    terminated_count = len(session_keys_to_delete)

    # 4. Log the action
    try:
        who = f"{user.get_full_name() or user.email} (company admin)"
        UserActivity.log_activity(
            user=user,
            account=account,
            activity_type='OTHER',
            description=f"Company admin force-logged out all users ({terminated_count} session(s) terminated)",
            app_name='accounts',
            model_name='UserSession',
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            extra_data={'terminated_count': terminated_count, 'session_keys_deleted': terminated_count},
        )
    except Exception as e:
        logger.exception("Error logging force-logout activity: %s", e)

    return terminated_count


def get_user_activity_summary(user, days=30, account=None):
    """
    Get a summary of user activities for the specified period.
    When account is provided, filters by account (tenant-safe); otherwise by user.
    
    Args:
        user: The User object
        days: Number of days to look back
        account: Optional Account to scope activities (recommended for multi-tenant)
        
    Returns:
        dict: Activity summary statistics
    """
    from .models import UserActivity
    from django.db.models import Count
    from datetime import timedelta
    
    start_date = timezone.now() - timedelta(days=days)
    
    activities = UserActivity.objects.filter(timestamp__gte=start_date)
    if account:
        activities = activities.filter(account=account)
    else:
        activities = activities.filter(user=user)
    
    # by_type: { activity_type: count } (accurate counts per type)
    by_type_qs = activities.values('activity_type').annotate(count=Count('id'))
    by_type = {r['activity_type']: r['count'] for r in by_type_qs}
    
    # by_app: { app_name: count }
    by_app_qs = activities.exclude(app_name='').values('app_name').annotate(count=Count('id'))
    by_app = {r['app_name']: r['count'] for r in by_app_qs}
    
    summary = {
        'total_activities': activities.count(),
        'by_type': by_type,
        'by_app': by_app,
        'suspicious_count': activities.filter(is_suspicious=True).count(),
    }
    
    return summary
