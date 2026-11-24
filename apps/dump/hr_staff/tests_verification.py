# -*- coding: utf-8 -*-
"""
Deep verification: URLs, views, models, admin, templates, API routes, and real-time sync are in place.
Run with: python manage.py test apps.hr_staff.tests_verification
"""
import os
from django.test import TestCase, Client
from django.urls import reverse, NoReverseMatch
from django.contrib.auth import get_user_model
from django.template.loader import get_template

User = get_user_model()

# All hr_staff URL names that do not require pk
HR_STAFF_URL_NAMES_NO_PK = [
    'dashboard',
    'dashboard_stats_json',
    'employee_list',
    'employee_create',
    'employee_create_profiles_for_all',
    'employee_portal_dashboard',
    'department_list',
    'department_create',
    'leave_list',
    'leave_create',
]

# URL names that require pk (we use pk=1 for resolution test; view may return 404/302)
HR_STAFF_URL_NAMES_PK = [
    ('employee_detail', 1),
    ('employee_edit', 1),
    ('employee_delete', 1),
    ('employee_reset_password', 1),
    ('employee_toggle_active', 1),
    ('department_detail', 1),
    ('department_edit', 1),
    ('department_delete', 1),
    ('leave_detail', 1),
    ('leave_edit', 1),
    ('leave_delete', 1),
    ('leave_update_status', 1),
]

# Templates used by hr_staff views (must exist)
HR_STAFF_TEMPLATES = [
    'hr_staff/dashboard.html',
    'hr_staff/employee_list.html',
    'hr_staff/employee_detail.html',
    'hr_staff/employee_form.html',
    'hr_staff/employee_confirm_delete.html',
    'hr_staff/employee_credentials_display.html',
    'hr_staff/employee_portal_dashboard.html',
    'hr_staff/department_list.html',
    'hr_staff/department_detail.html',
    'hr_staff/department_form.html',
    'hr_staff/department_confirm_delete.html',
    'hr_staff/leave_list.html',
    'hr_staff/leave_detail.html',
    'hr_staff/leave_form.html',
    'hr_staff/leave_confirm_delete.html',
    'hr_staff/partials/hr_top_nav.html',
    'hr_staff/partials/metrics.html',
    'hr_staff/partials/recent_employees.html',
    'hr_staff/partials/leave_requests.html',
    'hr_staff/partials/department_overview.html',
]

# API paths used by frontend for real-time (no page refresh)
HR_STAFF_API_PATHS = [
    '/api/hr-staff/dashboard-stats/',
    '/api/hr-staff/dashboard-widgets/',
    '/api/hr-staff/notifications/',
    '/api/hr-staff/employees/',
    '/api/hr-staff/departments/',
    '/api/hr-staff/leave-requests/',
]


class HrStaffSyncVerificationTest(TestCase):
    """Verify URLs, templates, models, admin, and API are in sync."""

    def setUp(self):
        from apps.core.models import Account, CompanyProfile
        from apps.accounts.services import get_or_create_company_admin_group, assign_user_to_account_group
        self.client = Client()
        self.account = Account.objects.create(name='Verify Account', owner=None)
        self.user = User.objects.create_user(
            email='verify@test.com', password='pass', first_name='V', last_name='User', account=self.account
        )
        self.account.owner_id = self.user.id
        self.account.save(update_fields=['owner_id'])
        CompanyProfile.objects.create(
            user=self.user, account=self.account, company_name='Verify Co', currency_symbol='$',
        )
        admin_ag = get_or_create_company_admin_group(self.account)
        assign_user_to_account_group(self.user, admin_ag)

    def test_all_hr_staff_url_names_resolve_without_pk(self):
        """Every hr_staff URL name (no pk) resolves without NoReverseMatch."""
        for name in HR_STAFF_URL_NAMES_NO_PK:
            with self.subTest(name=name):
                try:
                    url = reverse('hr_staff:' + name)
                    self.assertTrue(url.startswith('/hr-staff/') or url.startswith('/'), f'{name} should resolve')
                except NoReverseMatch as e:
                    self.fail(f'hr_staff:{name} failed to resolve: {e}')

    def test_all_hr_staff_url_names_with_pk_resolve(self):
        """Every hr_staff URL name (with pk) resolves."""
        for name, pk in HR_STAFF_URL_NAMES_PK:
            with self.subTest(name=name, pk=pk):
                try:
                    url = reverse('hr_staff:' + name, kwargs={'pk': pk})
                    self.assertIn(str(pk), url)
                except NoReverseMatch as e:
                    self.fail(f'hr_staff:{name} pk={pk} failed to resolve: {e}')

    def test_all_templates_exist(self):
        """Every template referenced by hr_staff views exists and is loadable."""
        for tpl in HR_STAFF_TEMPLATES:
            with self.subTest(template=tpl):
                try:
                    get_template(tpl)
                except Exception as e:
                    self.fail(f'Template {tpl} should exist and be loadable: {e}')

    def test_main_app_includes_hr_staff_routes(self):
        """Project urls include hr-staff and api/hr-staff."""
        from django.urls import get_resolver
        resolver = get_resolver()
        url_patterns = [p.pattern for p in resolver.url_patterns]
        self.assertTrue(any('hr-staff' in str(p) for p in url_patterns), 'hr-staff/ should be in root urlconf')

    def test_hr_staff_models_registered_in_admin(self):
        """Department, Employee, LeaveRequest are registered in admin."""
        from django.contrib import admin
        from apps.hr_staff.models import Department, Employee, LeaveRequest
        self.assertTrue(admin.site.is_registered(Department))
        self.assertTrue(admin.site.is_registered(Employee))
        self.assertTrue(admin.site.is_registered(LeaveRequest))

    def test_dashboard_returns_200_when_authorized(self):
        """Dashboard view returns 200 for user with access."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('hr_staff:dashboard'))
        self.assertEqual(response.status_code, 200, 'Dashboard should return 200 for company admin')

    def test_employee_list_returns_200_when_authorized(self):
        """Employee list returns 200 for user with access."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('hr_staff:employee_list'))
        self.assertEqual(response.status_code, 200)

    def test_leave_list_returns_200_when_authorized(self):
        """Leave list returns 200 for user with access."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('hr_staff:leave_list'))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_stats_json_returns_200_and_structure(self):
        """Dashboard stats JSON endpoint returns 200 and expected keys (real-time sync)."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('hr_staff:dashboard_stats_json'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('total_employees', data)
        self.assertIn('pending_leaves', data)

    def test_api_dashboard_widgets_returns_200_and_structure(self):
        """API dashboard-widgets returns 200 and stats/widgets (real-time without refresh)."""
        self.client.force_login(self.user)
        response = self.client.get('/api/hr-staff/dashboard-widgets/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('stats', data)
        self.assertIn('recent_employees', data)
        self.assertIn('leave_requests', data)

    def test_api_notifications_returns_200_and_structure(self):
        """API notifications returns 200 and notifications list (real-time without refresh)."""
        self.client.force_login(self.user)
        response = self.client.get('/api/hr-staff/notifications/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('notifications', data)

    def test_api_employees_list_returns_200_and_results(self):
        """API employees list returns 200 and results (used by employee list polling)."""
        self.client.force_login(self.user)
        response = self.client.get('/api/hr-staff/employees/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)

    def test_api_leave_requests_list_returns_200_and_results(self):
        """API leave-requests list returns 200 and results (used by leave list and portal polling)."""
        self.client.force_login(self.user)
        response = self.client.get('/api/hr-staff/leave-requests/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)

    def test_api_departments_list_returns_200_and_results(self):
        """API departments list returns 200 and results."""
        self.client.force_login(self.user)
        response = self.client.get('/api/hr-staff/departments/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)


class HrStaffDataIsolationAndPermissionSyncTest(TestCase):
    """
    Data isolation: HR app never exposes another account's data.
    Permission table & role table: new HR permissions are in Django admin permission table
    and Company Admin roles are automatically updated (post_migrate + account approval).
    """

    def setUp(self):
        from apps.core.models import Account, CompanyProfile
        self.client = Client()
        # Account A
        self.account_a = Account.objects.create(name='Account A', owner=None)
        self.user_a = User.objects.create_user(
            email='usera@test.com', password='pass', first_name='User', last_name='A', account=self.account_a
        )
        self.account_a.owner_id = self.user_a.id
        self.account_a.save(update_fields=['owner_id'])
        CompanyProfile.objects.create(
            user=self.user_a, account=self.account_a, company_name='Co A', currency_symbol='$',
        )
        # Account B
        self.account_b = Account.objects.create(name='Account B', owner=None)
        self.user_b = User.objects.create_user(
            email='userb@test.com', password='pass', first_name='User', last_name='B', account=self.account_b
        )
        self.account_b.owner_id = self.user_b.id
        self.account_b.save(update_fields=['owner_id'])
        CompanyProfile.objects.create(
            user=self.user_b, account=self.account_b, company_name='Co B', currency_symbol='$',
        )

    def test_data_isolation_employee_queryset(self):
        """User from account A must not see any employee from account B."""
        from apps.hr_staff.models import Employee
        from apps.hr_staff.querysets import get_employee_queryset_for_user
        emp_b = Employee.objects.create(
            account=self.account_b, first_name='Only', last_name='InB', status='active', created_by=self.user_b
        )
        qs_a = get_employee_queryset_for_user(self.user_a, None, account_lookup='account')
        self.assertNotIn(emp_b, qs_a, 'Account A user must not see account B employees')
        self.assertEqual(qs_a.filter(account=self.account_b).count(), 0)

    def test_data_isolation_api_employees(self):
        """API /api/hr-staff/employees/ must return only current user's account employees."""
        from apps.hr_staff.models import Employee
        from apps.accounts.services import get_or_create_company_admin_group, sync_hr_staff_permissions_to_company_admin, assign_user_to_account_group
        ag_a = get_or_create_company_admin_group(self.account_a)
        sync_hr_staff_permissions_to_company_admin()
        assign_user_to_account_group(self.user_a, ag_a)
        emp_a = Employee.objects.create(
            account=self.account_a, first_name='In', last_name='A', status='active', created_by=self.user_a
        )
        Employee.objects.create(
            account=self.account_b, first_name='Only', last_name='InB', status='active', created_by=self.user_b
        )
        self.client.force_login(self.user_a)
        response = self.client.get('/api/hr-staff/employees/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        results = data.get('results', [])
        ids = [r['id'] for r in results]
        self.assertIn(emp_a.id, ids, 'User A must see their account employee')
        self.assertEqual(len(ids), 1, 'User A must not see account B employees')

    def test_approved_account_owner_gets_company_admin_and_hr_access(self):
        """When super admin approves account (is_approved=True), owner is assigned Company Admin and sees HR."""
        self.account_a.is_approved = False
        self.account_a.save(update_fields=['is_approved'])
        self.client.force_login(self.user_a)
        self.account_a.is_approved = True
        self.account_a.save(update_fields=['is_approved'])  # signal promotes owner to Company Admin + syncs HR perms
        self.user_a.refresh_from_db()
        if hasattr(self.user_a, '_perm_cache'):
            delattr(self.user_a, '_perm_cache')
        r_after = self.client.get(reverse('hr_staff:dashboard'))
        self.assertEqual(r_after.status_code, 200, 'Approved owner with Company Admin must access HR dashboard')

    def test_sync_hr_staff_permissions_adds_new_permissions_to_company_admin(self):
        """sync_hr_staff_permissions_to_company_admin adds all HR permissions (including view_hr_dashboard) to Company Admin groups."""
        from apps.accounts.services import get_or_create_company_admin_group, sync_hr_staff_permissions_to_company_admin
        from apps.accounts.models import AccountGroup
        from django.contrib.auth.models import Permission
        ag = get_or_create_company_admin_group(self.account_a)
        self.assertIsNotNone(ag.group_id)
        sync_hr_staff_permissions_to_company_admin()
        ag.refresh_from_db()
        codenames = set(ag.group.permissions.values_list('codename', flat=True))
        self.assertIn('view_hr_dashboard', codenames)
        self.assertIn('view_own_hr_dashboard', codenames)
