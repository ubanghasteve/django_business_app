"""
Phase 4 — Execution: API tests for offline-first sync endpoints.

Covers: authentication, no-tenant 403, RBAC, bulk create/update, last-write-wins,
multi-tenant isolation, changes endpoint.
"""
import uuid as uuid_lib
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType

from apps.core.models import Account, CompanyProfile
from apps.expense.models import Expense

User = get_user_model()


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S.%fZ') if dt else None


class SyncAPIExpenseAuthTest(TestCase):
    """Unauthenticated and no-tenant requests get 403."""

    def setUp(self):
        self.client = APIClient()
        self.bulk_url = reverse('sync_api:v1:expense-bulk-create-update')
        self.changes_url = reverse('sync_api:v1:expense-changes')

    def test_bulk_create_update_unauthenticated_returns_403(self):
        response = self.client.post(
            self.bulk_url,
            {'items': [{'uuid': str(uuid_lib.uuid4()), 'updated_at': _iso(timezone.now()), 'status': 'draft'}]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_changes_unauthenticated_returns_403(self):
        response = self.client.get(self.changes_url, {'since': '2020-01-01T00:00:00Z'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bulk_create_update_user_without_account_returns_403(self):
        user = User.objects.create_user(
            email='noaccount@test.com',
            password='pw',
            account=None,
        )
        User.objects.filter(pk=user.pk).update(account=None)
        user.refresh_from_db()
        ct = ContentType.objects.get_for_model(Expense)
        perm = Permission.objects.get(codename='view_expense', content_type=ct)
        user.user_permissions.add(perm)
        self.client.force_authenticate(user=user)
        response = self.client.post(
            self.bulk_url,
            {'items': [{'uuid': str(uuid_lib.uuid4()), 'updated_at': _iso(timezone.now()), 'status': 'draft'}]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('No tenant account', response.json().get('detail', ''))


class SyncAPIExpenseRBACTest(TestCase):
    """User without view_perm gets 403; without add_perm cannot create; without change_perm cannot update."""

    def setUp(self):
        self.client = APIClient()
        self.account = Account.objects.create(name='Test Account', owner=None)
        self.user = User.objects.create_user(
            email='rbac@test.com',
            password='pw',
            account=self.account,
        )
        self.company = CompanyProfile.objects.create(
            user=self.user,
            account=self.account,
            company_name='Test Co',
        )
        self.bulk_url = reverse('sync_api:v1:expense-bulk-create-update')
        self.changes_url = reverse('sync_api:v1:expense-changes')
        # Do NOT grant any expense permissions by default

    def test_changes_without_view_perm_returns_403(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.changes_url, {'since': '2020-01-01T00:00:00Z'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Permission denied', response.json().get('detail', ''))

    def test_bulk_without_view_perm_returns_403(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            self.bulk_url,
            {'items': [{'uuid': str(uuid_lib.uuid4()), 'updated_at': _iso(timezone.now()), 'status': 'draft'}]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_bulk_create_without_add_perm_fails_in_failed_list(self):
        ct = ContentType.objects.get_for_model(Expense)
        view_perm = Permission.objects.get(codename='view_expense', content_type=ct)
        self.user.user_permissions.add(view_perm)
        self.client.force_authenticate(user=self.user)
        item_uuid = str(uuid_lib.uuid4())
        response = self.client.post(
            self.bulk_url,
            {'items': [{'uuid': item_uuid, 'updated_at': _iso(timezone.now()), 'status': 'draft'}]},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data['success']), 0)
        self.assertEqual(len(data['failed']), 1)
        self.assertIn('No add permission', data['failed'][0].get('error', ''))


class SyncAPIExpenseBulkCreateUpdateTest(TestCase):
    """Bulk create and update by uuid; valid payload succeeds."""

    def setUp(self):
        self.client = APIClient()
        self.account = Account.objects.create(name='Test Account', owner=None)
        self.user = User.objects.create_user(
            email='sync@test.com',
            password='pw',
            account=self.account,
        )
        self.company = CompanyProfile.objects.create(
            user=self.user,
            account=self.account,
            company_name='Test Co',
        )
        ct = ContentType.objects.get_for_model(Expense)
        for codename in ('view_expense', 'add_expense', 'change_expense'):
            perm = Permission.objects.get(codename=codename, content_type=ct)
            self.user.user_permissions.add(perm)
        self.bulk_url = reverse('sync_api:v1:expense-bulk-create-update')
        self.changes_url = reverse('sync_api:v1:expense-changes')

    def test_bulk_create_success(self):
        self.client.force_authenticate(user=self.user)
        item_uuid = str(uuid_lib.uuid4())
        payload = {
            'items': [{
                'uuid': item_uuid,
                'updated_at': _iso(timezone.now()),
                'status': 'draft',
                'expense_date': '2025-01-15',
            }],
        }
        response = self.client.post(self.bulk_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data['failed']), 0)
        self.assertEqual(len(data['success']), 1)
        self.assertIn('uuid', data['success'][0])
        self.assertEqual(Expense.objects.filter(account=self.account).count(), 1)

    def test_bulk_update_success(self):
        self.client.force_authenticate(user=self.user)
        expense = Expense.objects.create(
            account=self.account,
            company=self.company,
            created_by=self.user,
            status='draft',
            expense_date=timezone.now().date(),
        )
        item_uuid = str(expense.uuid)
        newer = timezone.now() + timezone.timedelta(seconds=10)
        payload = {
            'items': [{
                'uuid': item_uuid,
                'updated_at': _iso(newer),
                'status': 'pending',
            }],
        }
        response = self.client.post(self.bulk_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data['failed']), 0)
        self.assertEqual(len(data['success']), 1)
        expense.refresh_from_db()
        self.assertEqual(expense.status, 'pending')

    def test_last_write_wins_older_skipped(self):
        self.client.force_authenticate(user=self.user)
        expense = Expense.objects.create(
            account=self.account,
            company=self.company,
            created_by=self.user,
            status='draft',
            expense_date=timezone.now().date(),
        )
        item_uuid = str(expense.uuid)
        # Incoming updated_at older than existing
        old_ts = expense.updated_at - timezone.timedelta(seconds=10)
        payload = {
            'items': [{
                'uuid': item_uuid,
                'updated_at': _iso(old_ts),
                'status': 'rejected',
            }],
        }
        response = self.client.post(self.bulk_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data['failed']), 0)
        self.assertEqual(len(data['success']), 1)
        expense.refresh_from_db()
        self.assertEqual(expense.status, 'draft')


class SyncAPIMultiTenantTest(TestCase):
    """User from account A cannot update a record belonging to account B."""

    def setUp(self):
        self.client = APIClient()
        self.account_a = Account.objects.create(name='Account A', owner=None)
        self.account_b = Account.objects.create(name='Account B', owner=None)
        self.user_a = User.objects.create_user(email='a@test.com', password='pw', account=self.account_a)
        self.user_b = User.objects.create_user(email='b@test.com', password='pw', account=self.account_b)
        self.company_a = CompanyProfile.objects.create(user=self.user_a, account=self.account_a, company_name='Co A')
        self.company_b = CompanyProfile.objects.create(user=self.user_b, account=self.account_b, company_name='Co B')
        for user in (self.user_a, self.user_b):
            ct = ContentType.objects.get_for_model(Expense)
            for codename in ('view_expense', 'add_expense', 'change_expense'):
                perm = Permission.objects.get(codename=codename, content_type=ct)
                user.user_permissions.add(perm)
        self.bulk_url = reverse('sync_api:v1:expense-bulk-create-update')

    def test_cross_tenant_update_rejected(self):
        expense = Expense.objects.create(
            account=self.account_a,
            company=self.company_a,
            created_by=self.user_a,
            status='draft',
            expense_date=timezone.now().date(),
        )
        item_uuid = str(expense.uuid)
        self.client.force_authenticate(user=self.user_b)
        payload = {
            'items': [{
                'uuid': item_uuid,
                'updated_at': _iso(timezone.now()),
                'status': 'rejected',
                'expense_date': '2025-01-01',
            }],
        }
        response = self.client.post(self.bulk_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data['success']), 0, 'User B must not update tenant A record')
        self.assertEqual(len(data['failed']), 1)
        self.assertIn('Cross-tenant', data['failed'][0].get('error', ''))
        expense.refresh_from_db()
        self.assertEqual(expense.status, 'draft', 'Tenant A record must be unchanged')


class SyncAPIChangesEndpointTest(TestCase):
    """Changes endpoint requires since (ISO8601); returns 400 when missing or invalid; 200 with list when valid."""

    def setUp(self):
        self.client = APIClient()
        self.account = Account.objects.create(name='Test Account', owner=None)
        self.user = User.objects.create_user(email='ch@test.com', password='pw', account=self.account)
        ct = ContentType.objects.get_for_model(Expense)
        perm = Permission.objects.get(codename='view_expense', content_type=ct)
        self.user.user_permissions.add(perm)
        self.changes_url = reverse('sync_api:v1:expense-changes')

    def test_changes_without_since_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.changes_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('since', response.json().get('detail', ''))

    def test_changes_invalid_since_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.changes_url, {'since': 'not-a-datetime'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_changes_valid_since_returns_200(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.changes_url, {'since': '2020-01-01T00:00:00Z'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.json(), list)
