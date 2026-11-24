from django.db import models
from django.contrib.auth import get_user_model
from decimal import Decimal
from apps.core.models import CompanyProfile
from apps.core.sync_mixin import SyncMixin

User = get_user_model()


class Client(SyncMixin, models.Model):
    company = models.ForeignKey(CompanyProfile, on_delete=models.CASCADE, related_name='clients')
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    address = models.TextField(blank=True)
    contact_person = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # updated_at from SyncMixin (for conflict resolution)

    # Auto-discovered from other apps: primary source
    source_app = models.CharField(max_length=64, blank=True, help_text='App where this client was first found (e.g. invoices, receipts)')
    source_record_id = models.CharField(max_length=64, blank=True)
    source_record_url = models.CharField(max_length=512, blank=True, help_text='Link to the exact record in the source app')
    source_record_label = models.CharField(max_length=255, blank=True, help_text='Human label e.g. Invoice INV-001')
    source_record_created_at = models.DateTimeField(null=True, blank=True, help_text='When the primary source record was created')
    source_record_created_by = models.CharField(max_length=255, blank=True, help_text='Who created the primary source record')
    # Other apps where same client appears: list of {app, label, url, created_at, created_by}
    other_sources = models.JSONField(default=list, blank=True, help_text='List of {app, label, url, created_at, created_by} for additional records')

    def __str__(self):
        return self.name

    def get_primary_source_url(self):
        """Return the main link to the source record (for card click)."""
        if self.source_record_url:
            return self.source_record_url
        if self.other_sources:
            return self.other_sources[0].get('url') or ''
        return ''

    def get_display_sources(self):
        """List of (app_label, record_label, url, created_at, created_by) for display (primary + other_sources).
        Includes all apps that created or have this client, no duplicates. Clients created
        manually (no source_app) show as 'Clients' so the card always shows the app name(s)."""
        seen_apps = set()
        out = []

        # Primary source: include when source_app is set (even if label is empty)
        if self.source_app:
            app = self.source_app.strip()
            if app and app not in seen_apps:
                seen_apps.add(app)
                created_at = getattr(self, 'source_record_created_at', None)
                created_by = getattr(self, 'source_record_created_by', '') or ''
                out.append((app, self.source_record_label or '', self.source_record_url or '', created_at, created_by))

        for s in self.other_sources or []:
            app = (s.get('app') or '').strip()
            if app and app not in seen_apps:
                seen_apps.add(app)
                created_at = s.get('created_at')
                if hasattr(created_at, 'strftime'):
                    created_at = created_at
                elif isinstance(created_at, str):
                    try:
                        from django.utils.dateparse import parse_datetime
                        created_at = parse_datetime(created_at)
                    except Exception:
                        created_at = None
                else:
                    created_at = None
                created_by = (s.get('created_by') or s.get('created_by_name') or '').strip()
                out.append((app, s.get('label', '') or '', s.get('url', '') or '', created_at, created_by))

        # Manual clients (created from Clients app): show "Clients" so the card displays the app name
        if not out:
            out.append(('Clients', '', '', None, ''))

        return out

    def get_all_creator_display_names(self):
        """Return a list of unique, non-empty creator names (for company admin: who created this client or any source record)."""
        seen_lower = set()
        names = []
        if self.created_by:
            raw = (getattr(self.created_by, 'get_full_name', lambda: '')() or getattr(self.created_by, 'email', '') or '').strip()
            if raw and raw.lower() not in seen_lower:
                names.append(raw)
                seen_lower.add(raw.lower())
        primary = (getattr(self, 'source_record_created_by', '') or '').strip()
        if primary and primary.lower() not in seen_lower:
            names.append(primary)
            seen_lower.add(primary.lower())
        for s in self.other_sources or []:
            raw = (s.get('created_by') or s.get('created_by_name') or '').strip()
            if raw and raw.lower() not in seen_lower:
                names.append(raw)
                seen_lower.add(raw.lower())
        return names

    class Meta:
        permissions = [
            ('print_client', 'Can print client'),
            ('download_client', 'Can download or export client data'),
        ]
