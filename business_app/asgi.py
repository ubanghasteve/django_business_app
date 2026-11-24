"""
ASGI config for business_app project.
Supports HTTP and WebSocket (messaging). Use: daphne -b 0.0.0.0 -p 8000 business_app.asgi:application
Or: python manage.py runserver (Channels + daphne take over when installed).
"""
import os

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'business_app.settings')

# Initialize Django ASGI application early so that apps are loaded before importing routing
django_asgi_app = get_asgi_application()

from apps.messaging.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AllowedHostsOriginValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    ),
})
