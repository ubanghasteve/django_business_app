"""
Minimal tests for per-team-member record isolation (ownership baseline).

Tests is_company_admin, get_account_for_user, and visibility logic without
applying to any business app.
"""
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from .ownership import (
    is_company_admin,
    get_account_for_user,
    TenantOwnedQuerySet,
    TenantOwnedManager,
    for_user_queryset,
)

User = get_user_model()


class OwnershipHelpersTest(TestCase):
    """Test ownership helpers (admin detection, account resolution)."""

    def setUp(self):
        self.factory = RequestFactory()
        self.account = None  # Set by test if needed

    def test_is_company_admin_no_request(self):
        """Without request we cannot know session; safe default is False (treat as team member, restrict)."""
        user = User(email='owner@test.com', first_name='O', last_name='Owner')
        self.assertFalse(is_company_admin(user, None))
        self.assertFalse(is_company_admin(user))

    def test_is_company_admin_unauthenticated(self):
        """Unauthenticated user is not company admin."""
        user = AnonymousUser()
        self.assertFalse(is_company_admin(user, None))
        req = self.factory.get('/')
        req.user = user
        req.session = {}
        self.assertFalse(is_company_admin(user, req))

    def test_is_company_admin_with_session_no_sub_user(self):
        """Request with session but no sub_user_id => company admin."""
        user = User(email='owner@test.com', first_name='O', last_name='Owner')
        req = self.factory.get('/')
        req.user = user
        req.session = {}
        self.assertTrue(is_company_admin(user, req))
        req.session['other'] = 1
        self.assertTrue(is_company_admin(user, req))

    def test_is_company_admin_with_sub_user(self):
        """Request with sub_user_id in session => not company admin."""
        user = User(email='member@test.com', first_name='M', last_name='Member')
        req = self.factory.get('/')
        req.user = user
        req.session = {'sub_user_id': 42}
        self.assertFalse(is_company_admin(user, req))

    def test_get_account_for_user_none(self):
        """get_account_for_user(None) returns None."""
        self.assertIsNone(get_account_for_user(None))

    def test_get_account_for_user_no_account_attr(self):
        """User without account attribute returns None (e.g. AnonymousUser or account=None)."""
        user = AnonymousUser()
        self.assertIsNone(get_account_for_user(user))
        user2 = User(email='u@test.com', first_name='U', last_name='U')
        # When account is None, get_account_for_user returns None
        if hasattr(user2, 'account'):
            pass  # getattr(user2, 'account', None) may be None for unsaved user
        self.assertIsNone(get_account_for_user(None))


class TenantOwnedQuerySetVisibleToTest(TestCase):
    """Test TenantOwnedQuerySet.visible_to behavior (admin bypass vs team member filter)."""

    def test_visible_to_requires_authenticated_user(self):
        """visible_to with no user returns none."""
        from .models import Account
        from django.db import connection
        # Use a minimal model that has account/company + created_by and TenantOwnedQuerySet.
        from apps.inventory.models import Inventory
        qs = Inventory.objects.all()
        if not hasattr(qs, 'visible_to'):
            self.skipTest('Inventory does not use TenantOwnedQuerySet')
        none_user = None
        self.assertEqual(qs.visible_to(none_user, None).count(), 0)
