from django.apps import AppConfig
from django.contrib import auth
from django.db.models.signals import post_migrate


def create_permissions(sender, **kwargs):
    """Create video call permissions after migration."""
    from django.contrib.contenttypes.models import ContentType
    from django.contrib.auth.models import Permission
    
    content_type, _ = ContentType.objects.get_or_create(
        app_label='videocalls',
        model='videocallroom'
    )
    
    permissions = [
        ('view_videocall', 'Can view video calls'),
        ('create_videocall', 'Can create video calls'),
        ('manage_videocall', 'Can manage video calls'),
        ('record_videocall', 'Can record video calls'),
    ]
    
    for codename, name in permissions:
        Permission.objects.get_or_create(
            codename=codename,
            name=name,
            content_type=content_type
        )


class VideocallsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.videocalls'
    verbose_name = 'Video Calls'
    
    def ready(self):
        post_migrate.connect(create_permissions, sender=self)
