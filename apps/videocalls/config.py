# Video Calls Configuration
# =========================

# ICE Server Configuration
# These are the STUN/TURN servers used for WebRTC connectivity
# For production, consider using services like Twilio, Xirsys, or Metered.ca

VIDEO_CALL_ICE_SERVERS = [
    # Free STUN servers (no authentication required)
    {'urls': 'stun:stun.l.google.com:19302'},
    {'urls': 'stun:stun1.l.google.com:19302'},
    {'urls': 'stun:stun2.l.google.com:19302'},
    {'urls': 'stun:stun.ekiga.net'},
    {'urls': 'stun:stun.ideasip.com'},
    
    # Free TURN servers from Metered.ca (500MB/month free)
    # For production, get your own credentials from https://www.metered.ca/tools/openrelay/
    {
        'urls': 'turn:a.relay.metered.ca:80',
        'username': 'free',
        'credential': 'free'
    },
    {
        'urls': 'turn:a.relay.metered.ca:443',
        'username': 'free',
        'credential': 'free'
    },
]

# Signaling Poll Interval (milliseconds)
# Lower = faster signaling but more server load
VIDEO_CALL_POLL_INTERVAL = 1000

# Maximum participants per room (default)
VIDEO_CALL_DEFAULT_MAX_PARTICIPANTS = 10

# Enable recording (requires server storage)
VIDEO_CALL_RECORDING_ENABLED = True

# Maximum recording file size in MB
VIDEO_CALL_MAX_RECORDING_SIZE_MB = 500

# Call duration limit in seconds (0 = no limit)
VIDEO_CALL_MAX_DURATION_SECONDS = 0

# Enable chat functionality
VIDEO_CALL_CHAT_ENABLED = True

# Auto-create participant for anonymous users
VIDEO_CALL_ANONYMOUS_ENABLED = True

# ============================================
# SFU (Selective Forwarding Unit) Settings
# For 30-40+ participants without lag
# NOTE: SFU requires a Node.js server. Set to False for cPanel/shared hosting.
# ============================================

# Enable SFU mode for large meetings (requires Node.js mediasoup server)
MEDIASOUP_ENABLED = False

# SFU Server URL (Node.js mediasoup server)
MEDIASOUP_SERVER_URL = 'http://localhost:3001'

# WebSocket URL (same as server URL for HTTP polling)
MEDIASOUP_WS_URL = 'http://localhost:3001'

# Automatically upgrade to SFU when room exceeds this threshold
# Set to 0 to always use P2P mode (cPanel compatible)
MEDIASOUP_LARGE_ROOM_THRESHOLD = 0

# Auto-upgrade large rooms to SFU mode
MEDIASOUP_AUTO_UPGRADE_LARGE_ROOMS = False

# ============================================
# OPTIONAL: Third-party API Keys
# ============================================

# Twilio TURN API (https://www.twilio.com/stun-turn)
# TWILIO_ACCOUNT_SID = your_account_sid
# TWILIO_AUTH_TOKEN = your_auth_token

# Xirsys TURN API (https://xirsys.com/)
# XIRSYS_API_KEY = your_api_key
# XIRSYS_API_SECRET = your_api_secret
# XIRSYS_DOMAIN = your_domain

# Metered.ca TURN API (https://www.metered.ca/)
# METERED_API_KEY = your_api_key
