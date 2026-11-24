"""
Views for serving Service Worker from root to allow scope='/'.
Service Workers can only control paths under their own directory,
so sw.js must be served from / to register with scope='/'.
Also serves the PWA web app manifest with resolved static icon URLs.
"""
import json
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.templatetags.static import static


def service_worker(request):
    """Serve sw.js from project root to allow full app scope."""
    # Try STATIC_ROOT first (production after collectstatic), then static source
    for base in [settings.STATIC_ROOT, settings.BASE_DIR / "static"]:
        if base:
            path = Path(base) / "js" / "sw.js"
            if path.exists():
                return FileResponse(
                    path.open("rb"),
                    content_type="application/javascript",
                )
    raise Http404("Service Worker not found")


def service_worker_offline(request):
    """Serve service-worker.js (offline-first) from root so scope is '/'."""
    for base in [settings.STATIC_ROOT, settings.BASE_DIR / "static"]:
        if base:
            path = Path(base) / "js" / "service-worker.js"
            if path.exists():
                return FileResponse(
                    path.open("rb"),
                    content_type="application/javascript",
                )
    raise Http404("Service Worker not found")


def favicon_ico(request):
    """Serve /favicon.ico from the branded PNG/ICO so browsers stop using a cached default."""
    for base in [settings.STATIC_ROOT, settings.BASE_DIR / "static"]:
        if not base:
            continue
        for name in ("img/favicon.ico", "img/favicon.png"):
            path = Path(base) / name
            if path.exists():
                content_type = (
                    "image/x-icon" if path.suffix.lower() == ".ico" else "image/png"
                )
                response = FileResponse(path.open("rb"), content_type=content_type)
                response["Cache-Control"] = "public, max-age=86400"
                return response
    raise Http404("Favicon not found")


def _static_url(path, fallback):
    """Resolve a static URL; fall back if Manifest storage has no entry yet."""
    try:
        return static(path)
    except Exception:
        return fallback


def web_manifest(request):
    """Serve PWA manifest with hashed static icon URLs resolved at request time."""
    icon_192 = _static_url("img/icon-192.png", "/static/img/icon-192.png")
    icon_512 = _static_url("img/icon-512.png", "/static/img/icon-512.png")
    icon_maskable_192 = _static_url(
        "img/icon-maskable-192.png", "/static/img/icon-maskable-192.png"
    )
    icon_maskable_512 = _static_url(
        "img/icon-maskable-512.png", "/static/img/icon-maskable-512.png"
    )

    # Stable app id (same-origin). Used for install identity + getInstalledRelatedApps().
    app_id = "/dashboard/landing/"

    manifest = {
        "id": app_id,
        "name": "City Prints & Packaging",
        "short_name": "City Prints",
        "description": (
            "Business management app for City Prints & Packaging - "
            "invoices, inventory, HR, and more."
        ),
        "start_url": "/dashboard/landing/",
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#ffffff",
        "theme_color": "#ff6600",
        "lang": "en",
        "dir": "ltr",
        "categories": ["business", "productivity", "finance"],
        # Lets supporting browsers detect an existing install of this PWA.
        "prefer_related_applications": False,
        "related_applications": [
            {
                "platform": "webapp",
                "url": "/manifest.webmanifest",
                "id": app_id,
            }
        ],
        "icons": [
            {
                "src": icon_192,
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": icon_512,
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": icon_maskable_192,
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "maskable",
            },
            {
                "src": icon_maskable_512,
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
        "shortcuts": [
            {
                "name": "Dashboard",
                "short_name": "Dashboard",
                "url": "/dashboard/landing/",
                "icons": [{"src": icon_192, "sizes": "192x192"}],
            },
            {
                "name": "Invoices",
                "short_name": "Invoices",
                "url": "/invoices/",
                "icons": [{"src": icon_192, "sizes": "192x192"}],
            },
        ],
    }

    response = HttpResponse(
        json.dumps(manifest, indent=2),
        content_type="application/manifest+json",
    )
    response["Cache-Control"] = "public, max-age=3600"
    return response
