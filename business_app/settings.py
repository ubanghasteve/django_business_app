"""
Django settings for business_app project.
"""

from pathlib import Path
import os
from decouple import config as _config_default, Config, RepositoryEnv

# PyMySQL setup - use PyMySQL as MySQLdb replacement
import pymysql
pymysql.install_as_MySQLdb()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env from project root so cPanel/live server finds it even when CWD is different
_env_file = BASE_DIR / '.env'
if _env_file.exists():
    config = Config(RepositoryEnv(str(_env_file)))
else:
    config = _config_default

# Security settings
SECRET_KEY = config('SECRET_KEY', default='django-insecure-your-secret-key-here')


def _safe_bool(key, default=True):
    """Read config as bool; if value is invalid (e.g. 'warn'), return default."""
    try:
        return config(key, default=default, cast=bool)
    except (ValueError, TypeError):
        return default


DEBUG = _safe_bool('DEBUG', False)
DEBUG_INVENTORY = _safe_bool('DEBUG_INVENTORY', True)

# Allowed Hosts – localhost default; on live set in .env (e.g. ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com)
# With that + SESSION_COOKIE_SECURE=True on live, notifications and login work on all devices.
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1,testserver').split(',')
if DEBUG:
    ALLOWED_HOSTS += ['*']

# Document smart extraction (Google Document AI / Azure): load from .env into os.environ
# so apps.extraction.smart_backends can use them. See DOCUMENT_SMART_APIS.md and .env.example.
for _key in (
    'USE_SMART_EXTRACTION', 'DOCUMENT_AI_PROJECT_ID', 'DOCUMENT_AI_LOCATION',
    'DOCUMENT_AI_PROCESSOR_ID', 'GOOGLE_APPLICATION_CREDENTIALS',
    'AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT', 'AZURE_DOCUMENT_INTELLIGENCE_KEY',
    # Advanced OCR engines
    'USE_ADVANCED_OCR', 'USE_ADVANCED_TABLE_EXTRACTION', 'USE_LAYOUT_ANALYSIS',
    'USE_PADDLEOCR', 'USE_EASYOCR', 'USE_RAPIDOCR', 'USE_DOCLAYOUT', 'USE_TABLE_EXTRACTION',
):
    try:
        _val = config(_key, default='')
        if _val and isinstance(_val, str):
            os.environ[_key] = _val.strip()
    except Exception:
        pass

# Application definition
# NOTE: With AJAX polling (no WebSockets), use standard WSGI runserver. Do NOT put
# 'daphne' first—that forces ASGI/Daphne. For WebSockets later, add 'daphne' first.
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
]

THIRD_PARTY_APPS = [
    'channels',
    'rest_framework',
    'corsheaders',
    'crispy_forms',
    'crispy_bootstrap5',
    'django_filters',
    'widget_tweaks',
]

LOCAL_APPS = [
    'apps.videocalls',
    'apps.accounts',
    'apps.core',
    'apps.invoices',
    'apps.receipts',
    'apps.requisitions',
    'apps.staff_offences',
    'apps.waybills',
    'apps.job_orders',
    'apps.quotations',
    'apps.inventory',
    'apps.store',
    'apps.expense',
    'apps.clients',
    'apps.accounting',
    'apps.messaging',
    'apps.mailing',
    'apps.hr_staff',
    'apps.notifications',
    'apps.sync_api',  # Offline-first sync API under /api/v1/
    'apps.smart_attendance',
    # AI Document Analyzer (tax analyzer)
    'apps.documents',
    'apps.extraction',
    'apps.ai_engine',
    'apps.finance_engine',
    'apps.tax_engine',
    'apps.reports',
    'apps.payroll',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    # Canonical host in DEBUG so session cookie works in Cursor + normal browser (localhost → 127.0.0.1)
    'apps.core.middleware.CanonicalHostMiddleware',
    # Performance middleware - GZip compression (must be first for maximum compression)
    'django.middleware.gzip.GZipMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.accounts.middleware.SessionInvalidationMiddleware',
    'apps.core.middleware.CompanyContextMiddleware',
    'apps.core.middleware.AccountApprovalMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Phase 7: Permission verification logging (log 403 and optionally access granted)
    'apps.core.middleware.PermissionVerificationMiddleware',
    # Custom performance middleware - Cache headers & preloading
    'apps.core.middleware.PerformanceMiddleware',
    'apps.core.middleware.JobOrderNoCacheMiddleware',  # Job orders: no cache so list/detail stay in sync
    'apps.core.middleware.RequisitionNoCacheMiddleware',  # Requisitions: no cache so list updates after edit/delete
    'apps.core.middleware.DynamicListNoCacheMiddleware',  # Inventory, waybills, invoices, receipts, quotations, expenses: same no-cache
    'apps.core.middleware.PreloadHeaderMiddleware',
    'apps.core.middleware.SecurityHeadersMiddleware',
    # Security tracking middleware - Track user activities
    'apps.accounts.middleware.ActivityTrackingMiddleware',
]

ROOT_URLCONF = 'business_app.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.core.context_processors.company_context',
                'apps.core.context_processors.rbac_context',
                'apps.core.context_processors.debug_context',
                'apps.core.context_processors.currency_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'business_app.wsgi.application'
ASGI_APPLICATION = 'business_app.asgi.application'

# Channel layers for WebSocket messaging (InMemory for dev; use Redis in production for multi-worker)
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    },
}

# Database Configuration
# Uses SQLite for local development, MySQL for production
# Set USE_MYSQL=True in .env file for production
USE_MYSQL = config('USE_MYSQL', default=False, cast=bool)

if USE_MYSQL:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': config('DB_NAME', default=''),
            'USER': config('DB_USER', default=''),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': config('DB_HOST', default='localhost'),
            'PORT': config('DB_PORT', default='3306'),
            'OPTIONS': {
                'charset': 'utf8mb4',
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
            'OPTIONS': {
                'timeout': 60,  # Wait for SQLite lock (dev server + dashboard polls share one file)
            }
        }
    }

# =============================================================================
# CACHING - Critical for fast loading on slow connections
# =============================================================================
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
        'TIMEOUT': 600,  # 10 minutes for better performance
        'OPTIONS': {
            'MAX_ENTRIES': 2000,  # Increased cache entries
            'CULL_FREQUENCY': 2,  # Remove 50% when cache is full
        },
    },
    # Dedicated cache for views (page caching)
    'views': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'view-cache',
        'TIMEOUT': 300,
        'OPTIONS': {
            'MAX_ENTRIES': 500,
        },
    },
    # Dedicated cache for database queries
    'db': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'db-cache',
        'TIMEOUT': 120,  # 2 minutes for database queries
        'OPTIONS': {
            'MAX_ENTRIES': 1000,
        },
    },
}

# Custom User Model
AUTH_USER_MODEL = 'accounts.User'

# Authentication Backends
AUTHENTICATION_BACKENDS = [
    'apps.accounts.backends.EmailBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Password validation - Flexible validation that allows any password format
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'apps.accounts.validators.NoRestrictionPasswordValidator',
        'OPTIONS': {
            'min_length': 1,
        }
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]
STATIC_ROOT = BASE_DIR / 'staticfiles'

# =============================================================================
# PERFORMANCE OPTIMIZATIONS - Fast loading on slow connections
# =============================================================================

# WhiteNoise with compression for smaller file transfers (Brotli can make collectstatic slow).
# For faster collectstatic, use: 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# WhiteNoise settings for aggressive caching
WHITENOISE_MAX_AGE = 31536000  # 1 year cache for static files (with hash busting)
WHITENOISE_MIMETYPES = {
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.woff2': 'font/woff2',
    '.woff': 'font/woff',
}

# Session: use database backend for reliable login persistence (cached_db can lose session across workers)
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_CACHE_ALIAS = 'default'
# Save session on every request to ensure login state persists
SESSION_SAVE_EVERY_REQUEST = True
# Session cookie - works on both localhost (HTTP) and live (HTTPS) from one codebase
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
# On localhost leave unset or False; on live server (HTTPS) set SESSION_COOKIE_SECURE=True in .env
SESSION_COOKIE_SECURE = _safe_bool('SESSION_COOKIE_SECURE', False)
SESSION_COOKIE_PATH = '/'
SESSION_COOKIE_AGE = 1209600  # 2 weeks
# CSRF cookie: match session so AJAX (e.g. notifications) works on live HTTPS
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

# Database connection pooling (reduce connection overhead)
if USE_MYSQL:
    DATABASES['default']['CONN_MAX_AGE'] = 600  # Keep connections alive for 10 minutes

# When behind nginx/Apache/cPanel that terminates HTTPS, Django must trust X-Forwarded-Proto
# so request.is_secure() is True and cookies/redirects work. Enable when ALLOWED_HOSTS has a live domain.
_deploy_hosts_for_proxy = [h.strip() for h in config('ALLOWED_HOSTS', default='localhost,127.0.0.1,testserver').split(',') if h.strip() and h.strip() not in ('localhost', '127.0.0.1', 'testserver', '*')]
if _deploy_hosts_for_proxy:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Security headers that also improve performance
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# Compress responses for faster transfers
GZ_COMPRESSION_LEVEL = 6

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# MariaDB does not support unique constraints with conditions; we skip creating them
# via required_db_features and silence the W036 warning.
SILENCED_SYSTEM_CHECKS = ['models.W036']

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

# CORS settings
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]



# CSRF Trusted Origins – works on localhost and live from one codebase
# Dev origins always included; live origins auto-added from ALLOWED_HOSTS (no manual list needed)
_dev_origins = [
    'http://localhost', 'http://127.0.0.1',
    'http://localhost:8000', 'http://127.0.0.1:8000',
    'http://localhost:5000', 'http://127.0.0.1:5000',
    'http://localhost:3000', 'http://127.0.0.1:3000',
    'http://localhost:8080', 'http://127.0.0.1:8080',
    'http://localhost:9000', 'http://127.0.0.1:9000',
]
# Auto-add https/http for each deployment domain in ALLOWED_HOSTS (excluding localhost/testserver/wildcard)
_deploy_hosts = [h.strip() for h in ALLOWED_HOSTS if h.strip() and h.strip() not in ('localhost', '127.0.0.1', 'testserver', '*')]
_deploy_origins = []
for host in _deploy_hosts:
    _deploy_origins.extend([f'https://{host}', f'http://{host}'])
# Optional: only if you use a custom port or extra domain (e.g. LAN IP)
# ADDITIONAL_CSRF_ORIGINS=https://www.yourdomain.com:8443
_additional = config('ADDITIONAL_CSRF_ORIGINS', default='').split(',')
_additional = [o.strip() for o in _additional if o.strip()]
# Combine: dev + deploy domains + additional (dedupe)
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys(_dev_origins + _deploy_origins + _additional))

# Use cookie for CSRF so token is sent reliably (avoids "CSRF token from POST incorrect").
# If you use session (True), Django does not set csrftoken cookie; our base template meta tag + JS
# handle AJAX, but cookie is simpler for form POSTs. Set to True if you need session-only CSRF.
CSRF_USE_SESSIONS = False









# Crispy Forms
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

# Login/Logout URLs
LOGIN_URL = '/auth/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/dashboard/landing/'

# Currency Settings
DEFAULT_CURRENCY = 'NGN'
SUPPORTED_CURRENCIES = {
    'NGN': '₦',
    'USD': '$',
    'EUR': '€',
    'GBP': '£',
}

# File Upload Settings (HR profile photos 5MB; leave supporting docs up to 10MB)
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10MB

# Email settings
# ============================================================================
# IMPORTANT: Configure your email credentials below to enable password reset
# ============================================================================

# Email Backend Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# For Gmail:
# 1. Enable 2-Factor Authentication on your Gmail account
# 2. Create App Password: https://myaccount.google.com/apppasswords
# 3. Use the 16-character app password below (NOT your regular Gmail password)
# EMAIL_HOST = 'smtp.gmail.com'
# EMAIL_PORT = 465
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = 'info.abgpaulas@gmail.com'
# EMAIL_HOST_PASSWORD = 'your-app-password-here'

EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=465, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=False, cast=bool)
EMAIL_USE_SSL = config('EMAIL_USE_SSL', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')


# Alternative Email Providers (uncomment and configure if not using Gmail):
# ----------------------------------------------------------------------------
# For Outlook/Hotmail:
# EMAIL_HOST = 'smtp-mail.outlook.com'
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = 'your-email@outlook.com'
# EMAIL_HOST_PASSWORD = 'your-password'
#
# For SendGrid (recommended for production):
# EMAIL_HOST = 'smtp.sendgrid.net'
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = 'apikey'
# EMAIL_HOST_PASSWORD = 'your-sendgrid-api-key'
# ----------------------------------------------------------------------------

# Default from email (should match EMAIL_HOST_USER)
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER
SERVER_EMAIL = EMAIL_HOST_USER

# Optional: Twilio for bulk SMS (set in .env to enable SMS on Bulk Mailing page)
TWILIO_ACCOUNT_SID = config('TWILIO_ACCOUNT_SID', default='')
TWILIO_AUTH_TOKEN = config('TWILIO_AUTH_TOKEN', default='')
TWILIO_PHONE_NUMBER = config('TWILIO_PHONE_NUMBER', default='')  # e.g. +1234567890

# Video Calls Configuration
# =============================================================================
# STUN/TURN servers for WebRTC connectivity
# These servers enable peer-to-peer connections and NAT traversal

# Default ICE servers (STUN only - free, no credentials needed)
DEFAULT_ICE_SERVERS = [
    {'urls': 'stun:stun.l.google.com:19302'},
    {'urls': 'stun:stun1.l.google.com:19302'},
    {'urls': 'stun:stun2.l.google.com:19302'},
]

# Optional TURN server credentials (for better connectivity behind strict NATs/firewalls)
# Get free credentials from: https://www.metered.ca/tools/openrelay/
# Or use Twilio Network Traversal: https://www.twilio.com/stun-turn
TURN_SERVER_URL = config('TURN_SERVER_URL', default='')
TURN_SERVER_USERNAME = config('TURN_SERVER_USERNAME', default='')
TURN_SERVER_CREDENTIAL = config('TURN_SERVER_CREDENTIAL', default='')

# Build ICE servers list based on configuration
VIDEO_CALL_ICE_SERVERS = DEFAULT_ICE_SERVERS.copy()

if TURN_SERVER_URL:
    turn_config = {
        'urls': TURN_SERVER_URL,
        'credential': TURN_SERVER_CREDENTIAL,
    }
    if TURN_SERVER_USERNAME:
        turn_config['username'] = TURN_SERVER_USERNAME
    VIDEO_CALL_ICE_SERVERS.append(turn_config)

# Video Call Settings
VIDEO_CALL_POLL_INTERVAL = config('VIDEO_CALL_POLL_INTERVAL', default=1000, cast=int)
VIDEO_CALL_MAX_PARTICIPANTS = config('VIDEO_CALL_MAX_PARTICIPANTS', default=50, cast=int)
VIDEO_CALL_RECORDING_ENABLED = config('VIDEO_CALL_RECORDING_ENABLED', default=True, cast=bool)
VIDEO_CALL_MAX_DURATION_SECONDS = config('VIDEO_CALL_MAX_DURATION_SECONDS', default=0, cast=int)
VIDEO_CALL_CHAT_ENABLED = config('VIDEO_CALL_CHAT_ENABLED', default=True, cast=bool)

# P2P Video Mode Settings (cPanel Compatible - No Node.js Required)
# Set MEDIASOUP_ENABLED=False to always use P2P mode (up to 6-8 participants)
# For 30+ participants, you'd need a VPS with Node.js for mediasoup SFU
MEDIASOUP_ENABLED = config('MEDIASOUP_ENABLED', default=False, cast=bool)
MEDIASOUP_SERVER_URL = config('MEDIASOUP_SERVER_URL', default='http://localhost:3001')
MEDIASOUP_WS_URL = config('MEDIASOUP_WS_URL', default='ws://localhost:3001')
MEDIASOUP_AUTO_UPGRADE_LARGE_ROOMS = config('MEDIASOUP_AUTO_UPGRADE_LARGE_ROWS', default=False, cast=bool)
MEDIASOUP_LARGE_ROOM_THRESHOLD = config('MEDIASOUP_LARGE_ROOM_THRESHOLD', default=0, cast=int)

# Video Call Site URL - Set this to your domain for sharing meeting links
# Example: https://yourdomain.com or http://your-public-ip:8000
VIDEO_CALL_SITE_URL = config('VIDEO_CALL_SITE_URL', default='')
# =============================================================================

# Fallback to console backend for development/testing (uncomment if needed)
# Note: Console backend prints emails to terminal instead of sending them
# if not EMAIL_HOST_USER or EMAIL_HOST_USER == 'your-email@gmail.com':
#     EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
#     print("⚠️  WARNING: Using console email backend. Emails will be printed to console.")
#     print("   Configure EMAIL_HOST_USER and EMAIL_HOST_PASSWORD in settings.py to send real emails.")

# Debug and logging configuration
# NOTE: DEBUG and DEBUG_INVENTORY are defined near the top of this file using _safe_bool.
# This avoids accidentally overriding DEBUG to True in local/prod; set the DEBUG env var
# if you need to temporarily enable Django's debug mode.

# Phase 7: Set True during validation to log "Access granted" at sensitive paths (DEBUG).
# Set False after validation to stop those logs; 403 WARNING logs remain for audit.
PERMISSION_VERIFICATION_LOGGING = config('PERMISSION_VERIFICATION_LOGGING', default=False, cast=bool)

# Logging configuration for better debugging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': True,
        },
        'inventory': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG' if DEBUG_INVENTORY else 'INFO',
            'propagate': False,
        },
        'smart_attendance': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'smart_attendance.device': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'smart_attendance.sync': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'smart_attendance.repair': {
            'handlers': ['console', 'file'],
            'level': 'INFO',
            'propagate': False,
        },
        'security.permissions': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# Create logs directory if it doesn't exist
import os
logs_dir = BASE_DIR / 'logs'
logs_dir.mkdir(exist_ok=True)

# Celery / Redis configuration for background processing (attendance, biometric sync)
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default=CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_DEFAULT_QUEUE = 'default'

# Periodic tasks – device discovery for biometric devices (every 5 minutes).
# NOTE: On shared hosting (cPanel) Celery may not be installed or allowed.
# In that case this block is effectively unused; a cron-based management
# command (smart_attendance_cron) or zk_pull_sync can be used instead.
# We guard the import so missing Celery does not break Django startup.
try:
    from celery.schedules import crontab  # type: ignore  # noqa: E402
except (ImportError, ModuleNotFoundError):
    crontab = None

# Biometric push URL – when app runs on localhost, device cannot reach 127.0.0.1.
# Set to your server's reachable URL, e.g. "http://192.168.1.100:8000"
BIOMETRIC_PUSH_BASE_URL = config('BIOMETRIC_PUSH_BASE_URL', default='')

CELERY_BEAT_SCHEDULE = {}
if crontab is not None:
    CELERY_BEAT_SCHEDULE = {
        'smart_attendance_device_discovery': {
            'task': 'apps.smart_attendance.tasks.run_device_discovery',
            'schedule': 300.0,  # every 5 minutes
        },
    }
