# -*- coding: utf-8 -*-
"""Tests for HR Staff app: views, access control, and safety (HR vs Employee, explicit permission)."""
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
User = get_user_model()


class HrStaffAPITest(TestCase):
    """Test HR Staff API endpoints return 200 and expected structure when authenticated."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='hrtest@test.com',
            password='testpass123',
            first_name='HR',
            last_name='Tester',
        )
        # Create account and set user as owner so they are company admin
        from apps.core.models import Account, CompanyProfile
        self.account = Account.objects.create(name='Test Account', owner=self.user)
        self.user.account_id = self.account.id
        self.user.save(update_fields=['account_id'])
        self.company = CompanyProfile.objects.create(
            user=self.user,
            account=self.account,
            company_name='Test Co',
            currency_symbol='$',
        )

    def test_dashboard_widgets_api_returns_200_and_structure(self):
        self.client.force_login(self.user)
        url = '/api/hr-staff/dashboard-widgets/'
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, msg=response.content.decode())
        data = response.json()
        self.assertIn('stats', data)
        self.assertIn('recent_employees', data)
        self.assertIn('leave_requests', data)
        self.assertIn('departments_overview', data)
        self.assertIn('total_employees', data['stats'])
        self.assertIn('pending_leaves', data['stats'])

    def test_notifications_api_returns_200(self):
        self.client.force_login(self.user)
        response = self.client.get('/api/hr-staff/notifications/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, msg=response.content.decode())
        data = response.json()
        self.assertIn('notifications', data)

    def test_employees_list_api_returns_200(self):
        self.client.force_login(self.user)
        response = self.client.get('/api/hr-staff/employees/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, msg=response.content.decode())
        data = response.json()
        self.assertIn('results', data)

    def test_departments_list_api_returns_200(self):
        self.client.force_login(self.user)
        response = self.client.get('/api/hr-staff/departments/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, msg=response.content.decode())
        data = response.json()
        self.assertIn('results', data)

    def test_leave_requests_list_api_returns_200(self):
        self.client.force_login(self.user)
        response = self.client.get('/api/hr-staff/leave-requests/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, msg=response.content.decode())
        data = response.json()
        self.assertIn('results', data)

    def test_dashboard_stats_api_returns_200(self):
        self.client.force_login(self.user)
        response = self.client.get('/api/hr-staff/dashboard-stats/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200, msg=response.content.decode())
        data = response.json()
        self.assertIn('total_employees', data)
        self.assertIn('pending_leaves', data)

    def test_hr_dashboard_page_returns_200(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('hr_staff:dashboard'))
        self.assertEqual(response.status_code, 200, msg='HR dashboard should load for authenticated user')

    def test_create_employee_appears_in_dashboard_widgets(self):
        """Create an employee and verify it appears in dashboard-widgets API (real-time sync)."""
        from apps.hr_staff.models import Employee
        self.client.force_login(self.user)
        Employee.objects.create(
            account=self.account,
            company=self.company,
            first_name='New',
            last_name='Employee',
            status='active',
            created_by=self.user,
        )
        response = self.client.get('/api/hr-staff/dashboard-widgets/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreaterEqual(len(data['recent_employees']), 1)
        names = [e['full_name'] for e in data['recent_employees']]
        self.assertIn('New Employee', names)
        self.assertEqual(data['stats']['total_employees'], 1)

    def test_leave_duration_days_calculation(self):
        """Duration is (end_date - start_date).days + 1 (inclusive); API and model in sync."""
        from apps.hr_staff.models import Employee, LeaveRequest
        from datetime import date
        self.client.force_login(self.user)
        emp = Employee.objects.create(
            account=self.account,
            company=self.company,
            first_name='Leave',
            last_name='User',
            status='active',
            created_by=self.user,
        )
        # Same day -> 1 day
        leave1 = LeaveRequest.objects.create(
            account=self.account,
            employee=emp,
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 10),
            leave_type='sick',
            status='pending',
            created_by=self.user,
        )
        self.assertEqual(leave1.duration_days, 1)
        # Two days -> 2 days
        leave2 = LeaveRequest.objects.create(
            account=self.account,
            employee=emp,
            start_date=date(2025, 3, 10),
            end_date=date(2025, 3, 11),
            leave_type='vacation',
            status='approved',
            created_by=self.user,
        )
        self.assertEqual(leave2.duration_days, 2)
        # API returns duration_days
        response = self.client.get('/api/hr-staff/leave-requests/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        results = data.get('results', [])
        self.assertGreaterEqual(len(results), 2)
        by_id = {r['id']: r for r in results}
        self.assertEqual(by_id[leave1.id]['duration_days'], 1)
        self.assertEqual(by_id[leave2.id]['duration_days'], 2)


class HrStaffAccessAndSafetyTest(TestCase):
    """Confirm: old staff get employee profiles; HR sees all; employees see only themselves; HR cannot break other apps; HR app requires explicit permission."""

    def setUp(self):
        from apps.core.models import Account, CompanyProfile
        from apps.accounts.services import create_account_group, assign_user_to_account_group
        self.client = Client()
        self.account = Account.objects.create(name='Safe HR Account', owner=None)
        self.owner = User.objects.create_user(
            email='owner@test.com', password='pass', first_name='Owner', last_name='User', account=self.account
        )
        self.account.owner_id = self.owner.id
        self.account.save(update_fields=['owner_id'])
        CompanyProfile.objects.create(
            user=self.owner, account=self.account, company_name='Test Co', currency_symbol='$',
        )
        self.hr_user = User.objects.create_user(
            email='hr@test.com', password='pass', first_name='HR', last_name='User', account=self.account
        )
        self.employee_user = User.objects.create_user(
            email='emp@test.com', password='pass', first_name='Emp', last_name='User', account=self.account
        )
        hr_ag = create_account_group(
            self.account, 'HR Role',
            permission_codenames=[
                'hr_staff.view_hr_dashboard', 'hr_staff.view_employee', 'hr_staff.add_employee',
                'hr_staff.view_department', 'hr_staff.view_leaverequest', 'hr_staff.change_leaverequest',
            ],
        )
        emp_ag = create_account_group(
            self.account, 'Employee Role',
            permission_codenames=['hr_staff.view_own_hr_dashboard', 'hr_staff.view_employee', 'hr_staff.change_employee', 'hr_staff.view_leaverequest', 'hr_staff.add_leaverequest'],
        )
        assign_user_to_account_group(self.hr_user, hr_ag)
        assign_user_to_account_group(self.employee_user, emp_ag)

    def test_hr_app_requires_explicit_permission(self):
        """Without view_hr_dashboard and without view_own_hr_dashboard, user gets 403 on HR dashboard."""
        from apps.accounts.services import create_account_group, assign_user_to_account_group
        no_hr_user = User.objects.create_user(
            email='nohr@test.com', password='pass', first_name='No', last_name='HR', account=self.account
        )
        other_ag = create_account_group(self.account, 'Other', permission_codenames=['invoices.view_invoice'])
        assign_user_to_account_group(no_hr_user, other_ag)
        self.client.force_login(no_hr_user)
        self.assertFalse(no_hr_user.has_perm('hr_staff.view_hr_dashboard'))
        self.assertFalse(no_hr_user.has_perm('hr_staff.view_own_hr_dashboard'))
        response = self.client.get(reverse('hr_staff:dashboard'))
        self.assertEqual(response.status_code, 403, 'HR app must require explicit permission')

    def test_hr_sees_all_employees(self):
        """User with view_hr_dashboard sees all employees in the account (no created_by filtering)."""
        from apps.hr_staff.models import Employee
        from apps.hr_staff.querysets import get_employee_queryset_for_user
        Employee.objects.create(account=self.account, first_name='A', last_name='One', status='active', created_by=self.employee_user)
        Employee.objects.create(account=self.account, first_name='B', last_name='Two', status='active', created_by=self.owner)
        self.client.force_login(self.hr_user)
        qs = get_employee_queryset_for_user(self.hr_user, None, account_lookup='account')
        self.assertGreaterEqual(qs.count(), 2, 'HR must see all employees')

    def test_employees_see_only_themselves(self):
        """User with view_own_hr_dashboard and linked_employee sees only their own employee record."""
        from apps.hr_staff.models import Employee
        from apps.hr_staff.querysets import get_employee_queryset_for_user, get_linked_employee_for_user
        emp1 = Employee.objects.create(account=self.account, first_name='A', last_name='One', status='active', created_by=self.owner, linked_user=self.employee_user, is_portal_user=True)
        Employee.objects.create(account=self.account, first_name='B', last_name='Two', status='active', created_by=self.owner)
        qs = get_employee_queryset_for_user(self.employee_user, None, account_lookup='account')
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().pk, emp1.pk)
        linked = get_linked_employee_for_user(self.employee_user)
        self.assertIsNotNone(linked)
        self.assertEqual(linked.pk, emp1.pk)

    def test_old_staff_get_employee_profiles(self):
        """Create profiles for all users: every account user without a profile gets an Employee linked to them."""
        from apps.hr_staff.models import Employee
        from apps.hr_staff.forms import get_account_users_without_employee
        from apps.accounts.services import get_or_create_company_admin_group, assign_user_to_account_group
        users_without = list(get_account_users_without_employee(self.account))
        self.assertGreaterEqual(len(users_without), 2)  # at least hr_user, employee_user
        # Company Admin can run create-profiles-for-all
        admin_ag = get_or_create_company_admin_group(self.account)
        assign_user_to_account_group(self.owner, admin_ag)
        self.client.force_login(self.owner)
        response = self.client.post(reverse('hr_staff:employee_create_profiles_for_all'), {}, follow=True)
        self.assertEqual(response.status_code, 200, response.content.decode() if hasattr(response, 'content') else str(response))
        for u in (self.hr_user, self.employee_user):
            self.assertTrue(Employee.objects.filter(account=self.account, linked_user=u).exists(), f'Employee profile must exist for {u.email}')
        self.assertEqual(Employee.objects.filter(account=self.account).count(), len(users_without))

    def test_hr_cannot_break_other_apps(self):
        """HR role has only HR permissions; cannot access e.g. team/subuser management without that permission."""
        self.client.force_login(self.hr_user)
        # HR user has no accounts.view_subuser by default
        self.assertFalse(self.hr_user.has_perm('accounts.view_subuser'))
        response = self.client.get(reverse('accounts:subuser_list'))
        self.assertIn(response.status_code, (302, 403), 'HR without view_subuser must not access team management')
