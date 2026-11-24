from django.contrib.auth.backends import BaseBackend
from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class EmailBackend(BaseBackend):
    """
    Custom authentication backend. Allows login with:
    1. Main User (email + password)
    2. SubUser / Team Member (their email + password) - returns linked_user so permissions apply
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        from .models import SubUser
        
        if not username or not password:
            return None
        
        # 1. Try main User first (case-insensitive email)
        try:
            user = User.objects.get(email__iexact=username)
            if user.check_password(password) and user.is_active:
                return user
        except User.DoesNotExist:
            pass
        
        # 2. Try SubUser (team member, case-insensitive email)
        try:
            sub_user = SubUser.objects.select_related('account_owner', 'account_owner__account').get(
                email__iexact=username, is_active=True
            )
            if sub_user.check_password(password):
                from .services import ensure_subuser_linked_user
                linked_user = ensure_subuser_linked_user(sub_user)
                return linked_user
        except SubUser.DoesNotExist:
            pass
        
        return None
    
    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
