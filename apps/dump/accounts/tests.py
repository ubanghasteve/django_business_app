"""
Phase 8: Automated tests for group-based permissions and cross-account isolation.

Tests prove:
- Permissions are inherited from groups
- Access is denied without permission (403)
- Access is granted immediately after permission assignment
- Cross-account access is impossible
"""
from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection, transaction

from apps.core.models import Account
from apps.accounts.models import AccountGroup, SubUser, UserActivity
from apps.accounts.services import (
    create_account_group,
    assign_user_to_account_group,
    get_or_create_default_onboarding_role,
)
from apps.accounts.default_role import DEFAULT_ONBOARDING_ROLE_NAME

User = get_user_model()


def _create_user(email, account, password='testpass123', **kwargs):
    return User.objects.create_user(
        email=email,
        password=password,
        account=account,
        first_name='Test',
        last_name='User',
        **kwargs
    )


def _link_user_as_subuser(owner, user):
    """
    Create a SubUser so that `user` appears as an account member on the role members page.
    Use when tests need the user to be selectable in role_members (owner + active SubUser linked_users).
    """
    from django.contrib.auth.hashers import make_password
    return SubUser.objects.create(
        account_owner=owner,
        linked_user=user,
        email=user.email,
        full_name=user.get_full_name() or user.email,
        password_hash=user.password if hasattr(user, 'password') and user.password else make_password('testpass123'),
        is_active=True,
    )


def _create_account_with_owner(email='owner@test.com', name='Test Account'):
    """
    Create one Account and one User (owner) that reference each other.
    Uses explicit IDs and FK off (SQLite) to satisfy the circular FK.
    Must run outside an atomic block (e.g. in TransactionTestCase or with autocommit).
    """
    from django.utils import timezone
    now = timezone.now()
    # Use a separate atomic so we don't conflict with TestCase's outer atomic
    with transaction.atomic():
        with connection.cursor() as cursor:
            if connection.vendor == 'sqlite':
                cursor.execute('PRAGMA foreign_keys=OFF')
            cursor.execute('SELECT COALESCE(MAX(id), 0) + 1 FROM core_account')
            aid = cursor.fetchone()[0]
            cursor.execute('SELECT COALESCE(MAX(id), 0) + 1 FROM accounts_user')
            uid = cursor.fetchone()[0]
            cursor.execute(
                'INSERT INTO core_account (id, name, is_active, created_at, updated_at, owner_id) VALUES (%s, %s, 1, %s, %s, %s)',
                [aid, name, now.isoformat(), now.isoformat(), uid]
            )
            cursor.execute(
                """INSERT INTO accounts_user (id, email, account_id, first_name, last_name, password, is_active, is_staff, is_superuser, date_joined, phone, last_login, bio, location, website)
                   VALUES (%s, %s, %s, 'Test', 'Owner', '', 1, 0, 0, %s, '', NULL, '', '', '')""",
                [uid, email, aid, now.isoformat()]
            )
            if connection.vendor == 'sqlite':
                cursor.execute('PRAGMA foreign_keys=ON')
    account = Account.objects.get(pk=aid)
    user = User.objects.get(pk=uid)
    user.set_password('testpass123')
    user.save(update_fields=['password'])
    account.owner = user
    account.save(update_fields=['owner_id'])
    return account, user


class GroupPermissionInheritanceTests(TransactionTestCase):
    """Prove that permissions are inherited from groups via AccountGroup."""

    def setUp(self):
        self.account, self.owner = _create_account_with_owner('owner@test.com', 'Test Account')
        self.user = _create_user('user@test.com', self.account)

    def test_user_inherits_permission_from_account_group(self):
        """User in a group with a permission has that permission via has_perm()."""
        perm = Permission.objects.filter(codename='view_subuser').first()
        self.assertIsNotNone(perm, 'view_subuser permission should exist')
        ag = create_account_group(
            self.account,
            role_name='Team Viewer',
            permission_codenames=['view_subuser'],
        )
        self.user.groups.add(ag.group)
        self.user.refresh_from_db()
        # Clear permission cache so we see fresh perms from group
        self.assertIn(ag.group, self.user.groups.all())
        self.assertTrue(
            self.user.has_perm('accounts.view_subuser'),
            'User in group with view_subuser should have that permission',
        )

    def test_user_without_group_does_not_have_permission(self):
        """User with no groups does not have the permission."""
        create_account_group(
            self.account,
            role_name='Team Viewer',
            permission_codenames=['view_subuser'],
        )
        self.user.refresh_from_db()
        self.assertFalse(
            self.user.has_perm('accounts.view_subuser'),
            'User not in any group should not have view_subuser',
        )

    def test_assign_user_to_account_group_grants_permission(self):
        """After assign_user_to_account_group, user has the group's permissions."""
        ag = create_account_group(
            self.account,
            role_name='Security Viewer',
            permission_codenames=['accounts.view_useractivity'],
        )
        assign_user_to_account_group(self.user, ag)
        self.user.refresh_from_db()
        self.assertTrue(
            self.user.has_perm('accounts.view_useractivity'),
            'After assignment user should have view_useractivity',
        )


class PermissionDeniedTests(TransactionTestCase):
    """Prove that access is denied (403) without the required permission."""

    def setUp(self):
        self.account, self.owner = _create_account_with_owner('owner@test.com', 'Test Account')
        self.user = _create_user('noperm@test.com', self.account)
        self.client = Client()
        # Ensure user has no extra permissions (no group with view_useractivity)
        self.user.groups.clear()
        self.user.user_permissions.clear()
        self.user.save()

    def test_security_dashboard_denied_without_permission(self):
        """Access to security dashboard returns 403 without accounts.view_useractivity."""
        self.client.force_login(self.user)
        url = reverse('accounts:security_dashboard')
        response = self.client.get(url)
        self.assertEqual(
            response.status_code,
            403,
            'Security dashboard must return 403 when user lacks view_useractivity',
        )

    def test_role_list_denied_without_permission(self):
        """Access to role list returns 403 without auth.view_group (or equivalent)."""
        self.client.force_login(self.user)
        url = reverse('accounts:role_list')
        response = self.client.get(url)
        self.assertEqual(
            response.status_code,
            403,
            'Role list must return 403 when user lacks required permission',
        )

class PermissionGrantedAfterAssignmentTests(TransactionTestCase):
    """Prove that access is granted immediately after permission assignment."""

    def setUp(self):
        self.account, self.owner = _create_account_with_owner('owner@test.com', 'Test Account')
        self.user = _create_user('member@test.com', self.account)
        self.user.groups.clear()
        self.user.user_permissions.clear()
        self.user.save()
        self.client = Client()

    def test_security_dashboard_granted_after_group_assignment(self):
        """After adding user to a group with view_useractivity, security dashboard returns 200."""
        self.client.force_login(self.user)
        url = reverse('accounts:security_dashboard')
        r_before = self.client.get(url)
        self.assertEqual(r_before.status_code, 403, 'Must be denied before permission')

        ag = create_account_group(
            self.account,
            role_name='Security Viewer',
            permission_codenames=['accounts.view_useractivity'],
        )
        assign_user_to_account_group(self.user, ag)
        self.user.refresh_from_db()

        r_after = self.client.get(url)
        self.assertEqual(
            r_after.status_code,
            200,
            'Security dashboard must return 200 after user has view_useractivity',
        )


class CrossAccountIsolationTests(TransactionTestCase):
    """Prove that cross-account access is impossible."""

    def setUp(self):
        self.account1, self.owner1 = _create_account_with_owner('owner1@test.com', 'Account One')
        self.user1 = _create_user('user1@test.com', self.account1)
        self.account2, self.owner2 = _create_account_with_owner('owner2@test.com', 'Account Two')
        self.user2 = _create_user('user2@test.com', self.account2)
        self.client = Client()

    def test_user_cannot_assign_another_accounts_group(self):
        """assign_user_to_account_group raises when user and group are from different accounts."""
        ag2 = create_account_group(
            self.account2,
            role_name='Other Role',
            permission_codenames=[],
        )
        with self.assertRaises(ValueError) as ctx:
            assign_user_to_account_group(self.user1, ag2)
        self.assertIn('outside their account', str(ctx.exception))

    def test_quotation_list_only_shows_own_account_quotations(self):
        """Quotation list for user1 must not include quotations belonging to user2 (other account)."""
        from apps.quotations.models import Quotation
        from apps.clients.models import Client
        from apps.core.models import CompanyProfile

        # Create company profile for account1 so we can create clients
        cp1 = CompanyProfile.objects.create(
            account=self.account1,
            user=self.owner1,
            company_name='Co1',
            email='c1@test.com',
        )
        cp2 = CompanyProfile.objects.create(
            account=self.account2,
            user=self.owner2,
            company_name='Co2',
            email='c2@test.com',
        )
        client1 = Client.objects.create(company=cp1, name='Client1', email='', created_by=self.owner1)
        client2 = Client.objects.create(company=cp2, name='Client2', email='', created_by=self.owner2)

        # Quotation for user1 (account1)
        q1 = Quotation.objects.create(
            user=self.user1,
            quotation_number='Q1-001',
            grand_total=100,
            status='draft',
            client=client1,
        )
        # Quotation for user2 (account2)
        q2 = Quotation.objects.create(
            user=self.user2,
            quotation_number='Q2-001',
            grand_total=200,
            status='draft',
            client=client2,
        )

        self.client.force_login(self.user1)
        url = reverse('quotations:quotation_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # List view uses get_filtered_quotations(request) which filters by request.user
        page_obj = response.context.get('page_obj')
        self.assertIsNotNone(page_obj)
        ids = [q.pk for q in page_obj.object_list]
        self.assertIn(q1.pk, ids, 'User1 should see their own quotation')
        self.assertNotIn(q2.pk, ids, 'User1 must not see quotation from another account')

    def test_quotation_detail_returns_404_for_other_account(self):
        """Accessing another account's quotation by ID must return 404 (or 403)."""
        from apps.quotations.models import Quotation
        from apps.clients.models import Client
        from apps.core.models import CompanyProfile

        cp2 = CompanyProfile.objects.create(
            account=self.account2,
            user=self.owner2,
            company_name='Co2',
            email='c2@test.com',
        )
        client2 = Client.objects.create(company=cp2, name='Client2', email='', created_by=self.owner2)
        q2 = Quotation.objects.create(
            user=self.user2,
            quotation_number='Q2-001',
            grand_total=200,
            status='draft',
            client=client2,
        )

        self.client.force_login(self.user1)
        url = reverse('quotations:quotation_detail', kwargs={'pk': q2.pk})
        response = self.client.get(url)
        # Detail view must not expose another account's quotation: 404 or 403
        self.assertIn(
            response.status_code,
            (403, 404),
            'Quotation detail must return 403 or 404 when quotation belongs to another account',
        )


class PrivilegeEscalationTests(TransactionTestCase):
    """Prove that users cannot assign permissions or groups that grant more power than they have."""

    def setUp(self):
        self.account, self.owner = _create_account_with_owner('owner@test.com', 'Test Account')
        self.staff_user = _create_user('staff@test.com', self.account)
        self.member_user = _create_user('member@test.com', self.account)
        self.client = Client()

    def test_get_permissions_user_may_assign_excludes_auth_management_for_non_superuser(self):
        """Non-superuser may not assign auth.add_group, auth.change_permission, etc."""
        from apps.accounts.permission_boundaries import (
            get_permissions_user_may_assign,
            NON_DELEGATABLE_APP_LABEL,
            NON_DELEGATABLE_PERMISSION_CODENAMES,
        )
        # Give staff_user some permissions but not superuser
        ag = create_account_group(
            self.account,
            role_name='Staff',
            permission_codenames=['accounts.view_subuser', 'auth.add_group'],
        )
        self.staff_user.groups.add(ag.group)
        allowed = get_permissions_user_may_assign(self.staff_user)
        allowed_codenames = set(allowed.values_list('codename', flat=True))
        for codename in NON_DELEGATABLE_PERMISSION_CODENAMES:
            self.assertNotIn(
                codename,
                allowed_codenames,
                f'Non-superuser must not be able to assign auth.{codename}',
            )

    def test_get_permissions_user_may_assign_only_includes_permissions_user_has(self):
        """User may only assign permissions they already have."""
        from apps.accounts.permission_boundaries import get_permissions_user_may_assign
        create_account_group(
            self.account,
            role_name='Viewer',
            permission_codenames=['requisitions.view_requisition'],
        )
        ag = create_account_group(
            self.account,
            role_name='Staff',
            permission_codenames=['requisitions.view_requisition', 'requisitions.add_requisition'],
        )
        self.staff_user.groups.clear()
        self.staff_user.groups.add(ag.group)
        allowed = get_permissions_user_may_assign(self.staff_user)
        allowed_specs = {f"{p.content_type.app_label}.{p.codename}" for p in allowed}
        self.assertIn('requisitions.view_requisition', allowed_specs)
        self.assertIn('requisitions.add_requisition', allowed_specs)
        # User does not have delete_requisition
        self.assertNotIn('requisitions.delete_requisition', allowed_specs)

    def test_role_form_rejects_tampered_superuser_permission(self):
        """Submitting a permission the user may not assign raises ValidationError."""
        from apps.accounts.forms import AccountGroupForm
        from django.contrib.auth.models import Permission
        ag = create_account_group(
            self.account,
            role_name='Staff',
            permission_codenames=['requisitions.view_requisition'],
        )
        self.staff_user.groups.clear()
        self.staff_user.groups.add(ag.group)
        auth_add_group = Permission.objects.filter(
            content_type__app_label='auth',
            codename='add_group',
        ).first()
        self.assertIsNotNone(auth_add_group)
        form = AccountGroupForm(
            data={
                'role_name': 'Evil Role',
                'permissions': [auth_add_group.pk],
            },
            account=self.account,
            user=self.staff_user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('permissions', form.errors)

    def test_assign_user_to_role_with_more_power_than_assigner_returns_403(self):
        """Assigning users to a role that grants permissions the assigner lacks returns 403."""
        from apps.accounts.permission_boundaries import role_permissions_are_subset_of_user
        # Role has view + change requisition; staff_user only has view
        role_more = create_account_group(
            self.account,
            role_name='Editor',
            permission_codenames=['requisitions.view_requisition', 'requisitions.change_requisition'],
        )
        ag_staff = create_account_group(
            self.account,
            role_name='Viewer',
            permission_codenames=['requisitions.view_requisition'],
        )
        self.staff_user.groups.clear()
        self.staff_user.groups.add(ag_staff.group)
        self.assertFalse(
            role_permissions_are_subset_of_user(role_more, self.staff_user),
            'Editor role has change_requisition which staff_user does not have',
        )
        self.client.force_login(self.staff_user)
        url = reverse('accounts:role_members', kwargs={'role_id': role_more.pk})
        response = self.client.post(url, {'user_ids': [self.member_user.id]})
        self.assertEqual(response.status_code, 403)


class NoImplicitPermissionAdditionTests(TransactionTestCase):
    """
    Prove that role permission save does NOT add permissions the user did not select.

    BUG FIX: job_orders.Receipt and receipts.Receipt both have view_receipt.
    Passing codename-only caused _resolve_permissions to add ALL apps with that
    codename. AccountGroupForm now passes app_label.codename so only the
    explicitly selected permission is saved.
    """

    def setUp(self):
        self.account, self.owner = _create_account_with_owner('owner@test.com', 'Test Account')
        self.owner.is_superuser = True
        self.owner.save(update_fields=['is_superuser'])

    def test_selecting_receipts_view_receipt_does_not_add_job_orders_view_receipt(self):
        """Selecting receipts.view_receipt must NOT add job_orders.view_receipt."""
        from apps.accounts.forms import AccountGroupForm

        receipts_view = Permission.objects.filter(
            content_type__app_label='receipts',
            codename='view_receipt',
        ).first()
        job_orders_view = Permission.objects.filter(
            content_type__app_label='job_orders',
            codename='view_receipt',
        ).first()
        if not receipts_view or not job_orders_view:
            self.skipTest('receipts and job_orders apps with Receipt model required')

        form = AccountGroupForm(
            data={'role_name': 'Receipts Only', 'permissions': [receipts_view.pk]},
            account=self.account,
            user=self.owner,
        )
        self.assertTrue(form.is_valid(), form.errors)
        ag = form.save()

        role_specs = {
            f"{p.content_type.app_label}.{p.codename}"
            for p in ag.group.permissions.all()
        }
        self.assertIn('receipts.view_receipt', role_specs)
        self.assertNotIn(
            'job_orders.view_receipt',
            role_specs,
            'Selecting receipts.view_receipt must NOT implicitly add job_orders.view_receipt',
        )

    def test_unchecked_permission_removed_on_edit(self):
        """Unchecking a permission and saving must remove it permanently."""
        from apps.accounts.forms import AccountGroupForm

        perm1 = Permission.objects.filter(codename='view_subuser').first()
        perm2 = Permission.objects.filter(codename='view_useractivity').first()
        self.assertIsNotNone(perm1)
        self.assertIsNotNone(perm2)

        ag = create_account_group(
            self.account,
            role_name='Test Role',
            permission_codenames=['accounts.view_subuser', 'accounts.view_useractivity'],
        )
        initial_specs = {
            f"{p.content_type.app_label}.{p.codename}"
            for p in ag.group.permissions.all()
        }
        self.assertIn('accounts.view_subuser', initial_specs)
        self.assertIn('accounts.view_useractivity', initial_specs)

        # Edit: remove view_useractivity
        form = AccountGroupForm(
            data={'role_name': 'Test Role', 'permissions': [perm1.pk]},
            instance=ag,
            account=self.account,
            user=self.owner,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        ag.refresh_from_db()
        final_specs = {
            f"{p.content_type.app_label}.{p.codename}"
            for p in ag.group.permissions.all()
        }
        self.assertIn('accounts.view_subuser', final_specs)
        self.assertNotIn(
            'accounts.view_useractivity',
            final_specs,
            'Unchecked permission must be removed on save',
        )


class RolePermissionPersistenceVerificationTests(TransactionTestCase):
    """
    End-to-end verification: role save accuracy, role list consistency, runtime behavior.

    TEST 1: Create role with only receipts.view_receipt, save, re-open; job_orders NOT present.
    TEST 2: Role list shows only explicitly selected permissions.
    TEST 3: User with receipts-only role: Receipts visible, Job Orders not, job order URLs 403.
    """

    def setUp(self):
        self.account, self.owner = _create_account_with_owner('owner@test.com', 'Test Account')
        self.owner.is_superuser = True
        self.owner.save(update_fields=['is_superuser'])
        self.client = Client()

    def _get_receipts_view_perm(self):
        return Permission.objects.filter(
            content_type__app_label='receipts',
            codename='view_receipt',
        ).first()

    def test_1_role_save_accuracy(self):
        """Create role with ONLY receipts.view_receipt; save; re-open; job_orders perms NOT present."""
        from apps.accounts.forms import AccountGroupForm

        receipts_perm = self._get_receipts_view_perm()
        if not receipts_perm:
            self.skipTest('receipts.view_receipt permission required')

        # Create role
        form = AccountGroupForm(
            data={'role_name': 'Receipts Viewer', 'permissions': [receipts_perm.pk]},
            account=self.account,
            user=self.owner,
        )
        self.assertTrue(form.is_valid(), form.errors)
        ag = form.save()

        # Re-open: simulate loading edit form (form fetches initial from instance.group.permissions)
        edit_form = AccountGroupForm(instance=ag, account=self.account, user=self.owner)
        initial_pks = set(edit_form.fields['permissions'].initial or [])

        initial_specs = {
            f"{p.content_type.app_label}.{p.codename}"
            for p in Permission.objects.filter(pk__in=initial_pks)
        }

        self.assertIn('receipts.view_receipt', initial_specs)
        self.assertNotIn('job_orders.view_receipt', initial_specs)
        self.assertNotIn('job_orders.view_product', initial_specs)
        self.assertNotIn('job_orders.view_order', initial_specs)

    def test_2_role_list_consistency(self):
        """Role list page shows only explicitly selected permissions for the role."""
        receipts_perm = self._get_receipts_view_perm()
        if not receipts_perm:
            self.skipTest('receipts.view_receipt permission required')

        ag = create_account_group(
            self.account,
            role_name='Receipts Only Role',
            permission_codenames=['receipts.view_receipt'],
        )

        self.client.force_login(self.owner)
        response = self.client.get(reverse('auth:role_list'))
        self.assertEqual(response.status_code, 200)

        roles = response.context.get('roles') or []
        our_role = next((r for r in roles if r.pk == ag.pk), None)
        self.assertIsNotNone(our_role)

        displayed_specs = {
            f"{p.content_type.app_label}.{p.codename}"
            for p in our_role.group.permissions.all()
        }
        self.assertEqual(displayed_specs, {'receipts.view_receipt'})

    def test_3_runtime_behavior_receipts_visible_job_orders_403(self):
        """User with receipts-only role: Receipts visible, Job Orders NOT, job order URLs 403."""
        from apps.accounts.services import set_user_account_role

        receipts_perm = self._get_receipts_view_perm()
        if not receipts_perm:
            self.skipTest('receipts.view_receipt permission required')

        ag = create_account_group(
            self.account,
            role_name='Receipts Only',
            permission_codenames=['receipts.view_receipt'],
        )

        user = _create_user('receipts_only@test.com', self.account)
        set_user_account_role(user, ag)

        self.client.force_login(user)

        # Receipts list: should be accessible (200)
        receipts_url = reverse('receipts:list')
        r1 = self.client.get(receipts_url)
        self.assertEqual(r1.status_code, 200, f'Receipts list should be 200, got {r1.status_code}')

        # Job orders (products): should be 403
        job_orders_url = reverse('job_orders:products')
        r2 = self.client.get(job_orders_url)
        self.assertEqual(r2.status_code, 403, f'Job orders should be 403, got {r2.status_code}')

        # Navigation: user has receipts.view_receipt, not job_orders
        self.assertTrue(user.has_perm('receipts.view_receipt'))
        self.assertFalse(user.has_perm('job_orders.view_product'))
        self.assertFalse(user.has_perm('job_orders.view_order'))


class FullHrStaffRoleFormTests(TestCase):
    """Test that 'Full HR & Staff role' checkbox grants all HR permissions with any role name (HR2, My HR Role, etc.)."""

    def setUp(self):
        self.account = Account.objects.create(name='Test Account', is_approved=True)
        self.owner = User.objects.create_superuser(
            email='owner@test.com',
            password='testpass123',
            account=self.account,
            first_name='Test',
            last_name='Owner',
        )
        self.account.owner = self.owner
        self.account.save(update_fields=['owner_id'])

    def test_full_hr_staff_role_checkbox_grants_all_hr_permissions(self):
        """With only 'Full HR & Staff role' checked and any role name (e.g. HR2), role gets all HR permissions without selecting them in the list."""
        from apps.accounts.forms import AccountGroupForm

        hr_perms = list(
            Permission.objects.filter(content_type__app_label='hr_staff')
            .values_list('codename', flat=True)
            .distinct()
        )
        if not hr_perms:
            self.skipTest('hr_staff app has no permissions')

        form = AccountGroupForm(
            data={
                'role_name': 'HR2',
                'full_company_visibility': False,
                'full_hr_staff_role': True,
                'permissions': [],  # no permissions selected in the list
            },
            account=self.account,
            user=self.owner,
        )
        self.assertTrue(form.is_valid(), form.errors)
        ag = form.save()

        saved_specs = {
            f"{p.content_type.app_label}.{p.codename}"
            for p in ag.group.permissions.all()
        }
        for codename in hr_perms:
            self.assertIn(
                f'hr_staff.{codename}',
                saved_specs,
                f'Full HR & Staff role must grant hr_staff.{codename}',
            )
        self.assertEqual(ag.role_name, 'HR2')

    def test_custom_hr_role_names_and_edit_persist(self):
        """Create roles named HR3, My HR Role with Full HR & Staff only; edit persists to DB."""
        from apps.accounts.forms import AccountGroupForm

        for role_name in ('HR3', 'My HR Role'):
            form = AccountGroupForm(
                data={
                    'role_name': role_name,
                    'full_company_visibility': False,
                    'full_hr_staff_role': True,
                    'permissions': [],
                },
                account=self.account,
                user=self.owner,
            )
            self.assertTrue(form.is_valid(), form.errors)
            ag = form.save()
            self.assertEqual(ag.role_name, role_name)
            self.assertGreater(
                ag.group.permissions.filter(content_type__app_label='hr_staff').count(),
                0,
                f'Role {role_name} must have HR permissions',
            )


class DefaultOnboardingRoleTests(TransactionTestCase):
    """
    Default locked-down role for newly registered users.

    - New users are automatically assigned only to "Company Profile Viewer".
    - They cannot access restricted modules (invoices, expenses, etc.).
    - They gain access only after a superuser assigns an elevated role.
    - Privilege escalation (non-superuser adding to elevated role or removing from default) is blocked.
    """

    def setUp(self):
        self.account, self.owner = _create_account_with_owner('owner@test.com', 'Test Account')
        self.client = Client()

    def test_new_user_gets_company_profile_viewer_only(self):
        """A newly created user (with account) is automatically in Company Profile Viewer and has only minimal perms."""
        user = _create_user('newuser@test.com', self.account)
        user.refresh_from_db()
        groups = list(user.groups.all())
        self.assertEqual(len(groups), 1, 'New user should have exactly one group')
        ag = AccountGroup.objects.get(group=groups[0], account=self.account)
        self.assertEqual(ag.role_name, DEFAULT_ONBOARDING_ROLE_NAME)
        perm_codenames = set(
            ag.group.permissions.values_list('codename', flat=True)
        )
        self.assertEqual(perm_codenames, {'view_companyprofile'})
        self.assertTrue(user.has_perm('core.view_companyprofile'))
        self.assertFalse(user.has_perm('invoices.view_invoice'))
        self.assertFalse(user.has_perm('accounts.view_accountgroup'))

    def test_default_role_cannot_access_restricted_modules(self):
        """User in default role only receives 403 for requisitions, invoices, role list."""
        user = _create_user('locked@test.com', self.account)
        # Ensure only default role (no extra groups)
        user.groups.clear()
        default_ag = get_or_create_default_onboarding_role(self.account)
        assign_user_to_account_group(user, default_ag)
        user.refresh_from_db()
        self.client.force_login(user)
        self.assertEqual(
            self.client.get(reverse('requisitions:list')).status_code,
            403,
            'Requisitions list must return 403 for default role',
        )
        self.assertEqual(
            self.client.get(reverse('accounts:role_list')).status_code,
            403,
            'Role list must return 403 for default role',
        )
        self.assertEqual(
            self.client.get(reverse('invoices:list')).status_code,
            403,
            'Invoices list must return 403 for default role',
        )

    def test_default_role_can_view_company_profile_and_profile(self):
        """User in default role can access company profile (view) and own profile."""
        from apps.core.models import CompanyProfile
        user = _create_user('viewer@test.com', self.account)
        user.groups.clear()
        default_ag = get_or_create_default_onboarding_role(self.account)
        assign_user_to_account_group(user, default_ag)
        user.refresh_from_db()
        CompanyProfile.objects.create(
            account=self.account,
            user=self.owner,
            company_name='Test Co',
            email='test@test.com',
        )
        self.client.force_login(user)
        self.assertEqual(
            self.client.get(reverse('core:company_profile')).status_code,
            200,
            'Company profile view must be allowed for default role',
        )
        self.assertEqual(
            self.client.get(reverse('accounts:profile')).status_code,
            200,
            'Own profile must be allowed',
        )

    @override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
    def test_company_profile_onboarding_save_button_and_save_then_update_hidden(self):
        """Onboarding: newly registered (owner, view-only role) sees Save, can save; then Update hidden without change perm."""
        from apps.core.models import CompanyProfile
        # Owner with only default role (view_companyprofile), no company profile yet
        self.owner.groups.clear()
        default_ag = get_or_create_default_onboarding_role(self.account)
        assign_user_to_account_group(self.owner, default_ag)
        self.owner.refresh_from_db()
        CompanyProfile.objects.filter(account=self.account).delete()
        self.client.force_login(self.owner)
        # 1–2: GET company-profile → Save button visible
        resp = self.client.get(reverse('core:company_profile'))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context.get('show_save_button'), 'Save button must be visible for onboarding owner')
        self.assertIn(b'Create Profile', resp.content, 'Create Profile button must be in page')
        # 3: POST save company profile
        form_data = {
            'company_name': 'Onboarding Co',
            'email': 'onboard@test.com',
            'phone': '',
            'website': '',
            'address_line_1': '',
            'address_line_2': '',
            'city': '',
            'state': '',
            'postal_code': '',
            'country': '',
            'currency_code': 'USD',
            'currency_symbol': '$',
            'default_tax': '0',
            'primary_color': '#1976d2',
            'secondary_color': '#f8f9fa',
            'accent_color': '#e9ecef',
            'text_color': '#333333',
            'show_bank_details': 'on',
            'show_signature': 'on',
        }
        resp = self.client.post(reverse('core:company_profile'), form_data)
        self.assertEqual(resp.status_code, 302, 'POST must redirect after save')
        self.assertTrue(
            CompanyProfile.objects.filter(account=self.account).exists(),
            'Company profile must exist after onboarding save',
        )
        # 4: Re-GET company-profile → Update button hidden (no change_companyprofile)
        resp = self.client.get(reverse('core:company_profile'))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context.get('show_save_button'), 'Update button must be hidden without change permission')
        self.assertNotIn(b'Update Profile', resp.content, 'Update Profile button must not be rendered')
        # Other apps still 403
        self.assertEqual(self.client.get(reverse('requisitions:list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('invoices:list')).status_code, 403)
        # 5: Admin (user with change_companyprofile) sees Update button
        admin_ag = create_account_group(
            self.account,
            role_name='Company Editor',
            permission_codenames=['core.view_companyprofile', 'core.change_companyprofile'],
        )
        assign_user_to_account_group(self.owner, admin_ag)
        self.owner.groups.add(admin_ag.group)
        self.owner.refresh_from_db()
        resp = self.client.get(reverse('core:company_profile'))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context.get('show_save_button'), 'Admin/editor must see Update button')
        self.assertIn(b'Update Profile', resp.content)

    def test_access_after_superuser_assigns_elevated_role(self):
        """After a superuser assigns an elevated role, the user gains access to that module."""
        user = _create_user('member@test.com', self.account)
        _link_user_as_subuser(self.owner, user)
        user.groups.clear()
        default_ag = get_or_create_default_onboarding_role(self.account)
        assign_user_to_account_group(user, default_ag)
        elevated_ag = create_account_group(
            self.account,
            role_name='Requisition Viewer',
            permission_codenames=['requisitions.view_requisition'],
        )
        # Simulate superuser assigning elevated role
        self.owner.is_superuser = True
        self.owner.save()
        self.client.force_login(self.owner)
        url = reverse('accounts:role_members', kwargs={'role_id': elevated_ag.pk})
        self.client.post(url, {'user_ids': [user.id]})
        user.refresh_from_db()
        self.assertIn(elevated_ag.group, user.groups.all())
        self.client.force_login(user)
        self.assertEqual(
            self.client.get(reverse('requisitions:list')).status_code,
            200,
            'User must get access after superuser assigns elevated role',
        )

    def test_non_superuser_cannot_remove_from_default_role(self):
        """Only superuser may remove a user from Company Profile Viewer."""
        user = _create_user('member@test.com', self.account)
        _link_user_as_subuser(self.owner, user)
        user.groups.clear()
        default_ag = get_or_create_default_onboarding_role(self.account)
        assign_user_to_account_group(user, default_ag)
        # Admin has auth.change_group but is not superuser
        admin_ag = create_account_group(
            self.account,
            role_name='Company Admin',
            permission_codenames=[
                'core.view_companyprofile',
                'core.change_companyprofile',
                'auth.view_group',
                'auth.change_group',
            ],
        )
        admin_user = _create_user('admin@test.com', self.account)
        admin_user.groups.clear()
        assign_user_to_account_group(admin_user, admin_ag)
        self.assertFalse(admin_user.is_superuser)
        self.client.force_login(admin_user)
        url = reverse('accounts:role_members', kwargs={'role_id': default_ag.pk})
        # Try to remove user from default role (deselect user)
        response = self.client.post(url, {'user_ids': []})
        self.assertEqual(response.status_code, 403)
        user.refresh_from_db()
        self.assertIn(default_ag.group, user.groups.all(), 'Membership must be unchanged')

    def test_non_superuser_cannot_assign_elevated_role(self):
        """Only superuser may assign a user to a role other than Company Profile Viewer."""
        elevated_ag = create_account_group(
            self.account,
            role_name='Requisition Editor',
            permission_codenames=['requisitions.view_requisition', 'requisitions.change_requisition'],
        )
        # Admin has same perms as elevated role plus auth so they can open role_members and pass subset check
        admin_ag = create_account_group(
            self.account,
            role_name='Company Admin',
            permission_codenames=[
                'core.view_companyprofile',
                'requisitions.view_requisition',
                'requisitions.change_requisition',
                'auth.view_group',
                'auth.change_group',
            ],
        )
        admin_user = _create_user('admin@test.com', self.account)
        _link_user_as_subuser(self.owner, admin_user)
        admin_user.groups.clear()
        assign_user_to_account_group(admin_user, admin_ag)
        member_user = _create_user('member@test.com', self.account)
        _link_user_as_subuser(self.owner, member_user)
        member_user.groups.clear()
        default_ag = get_or_create_default_onboarding_role(self.account)
        assign_user_to_account_group(member_user, default_ag)
        self.assertFalse(admin_user.is_superuser)
        self.client.force_login(admin_user)
        url = reverse('accounts:role_members', kwargs={'role_id': elevated_ag.pk})
        response = self.client.post(url, {'user_ids': [member_user.id]})
        self.assertEqual(response.status_code, 403)
        member_user.refresh_from_db()
        self.assertNotIn(elevated_ag.group, member_user.groups.all())


class RoleMembershipAccuracyTests(TransactionTestCase):
    """
    Verify role membership accuracy: no ghost members, list always matches DB.

    TEST FLOW:
    1. Create role
    2. Add team member (with that role)
    3. Confirm they appear in authoritative membership data
    4. Remove team member
    5. Recompute role members (same logic as view)

    EXPECTED: No ghost members, membership list matches DB state, permissions unchanged.
    """

    def setUp(self):
        self.account, self.owner = _create_account_with_owner('owner@test.com', 'Test Account')
        self.owner.is_superuser = True
        self.owner.save()
        self.client = Client()

    def test_role_membership_accuracy_no_ghost_members_after_remove(self):
        """PASS only if: after remove team member, membership data has no ghost; list matches DB."""
        from apps.accounts.views import _get_account_member_user_ids

        # 1. Create role
        role_ag = create_account_group(
            self.account,
            role_name='Requisition Viewer',
            permission_codenames=['requisitions.view_requisition'],
        )
        permissions_before = set(
            role_ag.group.permissions.values_list('pk', flat=True)
        )

        # 2. Add team member (with this role)
        self.client.force_login(self.owner)
        add_url = reverse('accounts:subuser_create')
        self.client.post(add_url, data={
            'email': 'teammate@test.com',
            'full_name': 'Teammate One',
            'password': 'teampass123',
            'is_active': True,
            'role': role_ag.pk,
        })
        sub_user = SubUser.objects.get(email='teammate@test.com', account_owner=self.owner)
        linked_user = sub_user.linked_user
        linked_user_id = linked_user.id

        # 3. Confirm they appear in authoritative membership (same data the view uses)
        member_ids_1 = _get_account_member_user_ids(self.account)
        self.assertIn(linked_user_id, member_ids_1, 'Team member must appear in account members')
        all_users_1 = User.objects.filter(pk__in=member_ids_1).order_by('first_name', 'last_name', 'email')
        current_members_1 = all_users_1.filter(groups=role_ag.group)
        current_ids_1 = list(current_members_1.values_list('pk', flat=True))
        self.assertIn(linked_user_id, current_ids_1, 'Team member must appear as role member')

        # 4. Remove team member
        delete_url = reverse('accounts:subuser_delete', kwargs={'subuser_id': sub_user.pk})
        self.client.post(delete_url)
        self.assertFalse(SubUser.objects.filter(pk=sub_user.pk).exists(), 'SubUser must be deleted')

        # 5. Recompute role members (exactly what the view does on reload)
        member_ids_2 = _get_account_member_user_ids(self.account)
        all_users_2 = User.objects.filter(pk__in=member_ids_2).order_by('first_name', 'last_name', 'email')
        current_members_2 = all_users_2.filter(groups=role_ag.group)
        all_users_ids_2 = list(all_users_2.values_list('pk', flat=True))
        current_members_ids_2 = list(current_members_2.values_list('pk', flat=True))

        # No ghost members: removed user must not appear
        self.assertNotIn(
            linked_user_id, all_users_ids_2,
            'Removed team member must NOT appear in account users (no ghost members)',
        )
        self.assertNotIn(
            linked_user_id, current_members_ids_2,
            'Removed team member must NOT appear in role members (no ghost members)',
        )

        # Membership list matches DB: current_members == users in role.group that are valid account members
        in_group_in_db = list(
            User.objects.filter(pk__in=member_ids_2).filter(groups=role_ag.group).values_list('pk', flat=True)
        )
        self.assertEqual(
            sorted(current_members_ids_2),
            sorted(in_group_in_db),
            'Role members must match DB (account members in role.group)',
        )

        # Permissions unchanged
        role_ag.refresh_from_db()
        permissions_after = set(role_ag.group.permissions.values_list('pk', flat=True))
        self.assertEqual(
            permissions_before,
            permissions_after,
            'Role permissions must be unchanged after team member remove',
        )


class AddTeamMemberRoleAssignmentTests(TransactionTestCase):
    """
    Verify role assignment on Add Team Member flow:
    1. New role via Roles & Permissions appears in role selector
    2. Create team member with that role
    3. Log in as team member → allowed features work, forbidden return 403
    4. Assigning a role with higher permissions (than assigner) fails
    """

    def setUp(self):
        self.account, self.owner = _create_account_with_owner('owner@test.com', 'Test Account')
        self.owner.is_superuser = True
        self.owner.save()
        self.client = Client()

    def test_new_role_appears_in_add_team_member_form(self):
        """A role created via Roles & Permissions appears in the Add Team Member role selector."""
        role_ag = create_account_group(
            self.account,
            role_name='Requisition Viewer',
            permission_codenames=['requisitions.view_requisition'],
        )
        self.client.force_login(self.owner)
        url = reverse('accounts:subuser_create')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, 'Add Team Member page must load')
        form = response.context.get('form')
        self.assertIsNotNone(form, 'Form must be in context')
        role_queryset = form.fields['role'].queryset
        self.assertIn(role_ag, role_queryset, 'New role must appear in role selector')

    def test_deleted_role_does_not_appear_in_add_team_member_form(self):
        """After a role is deleted, it must not appear in Add Team Member role dropdown."""
        role_ag = create_account_group(
            self.account,
            role_name='Temporary Role',
            permission_codenames=['requisitions.view_requisition'],
        )
        self.client.force_login(self.owner)
        add_url = reverse('accounts:subuser_create')
        response = self.client.get(add_url)
        self.assertEqual(response.status_code, 200)
        form = response.context.get('form')
        self.assertIn(role_ag, form.fields['role'].queryset, 'Role must appear before delete')
        delete_url = reverse('accounts:role_delete', kwargs={'role_id': role_ag.pk})
        self.client.post(delete_url)
        response2 = self.client.get(add_url)
        self.assertEqual(response2.status_code, 200)
        form2 = response2.context.get('form')
        self.assertNotIn(
            role_ag,
            form2.fields['role'].queryset,
            'Deleted role must not appear in Add Team Member role selector',
        )
        role_pks = list(form2.fields['role'].queryset.values_list('pk', flat=True))
        self.assertNotIn(
            role_ag.pk,
            role_pks,
            'Deleted role pk must not be in dropdown queryset',
        )

    def test_role_dropdown_accuracy_verification(self):
        """
        VERIFICATION TEST: Role dropdown must match database state exactly.
        
        Steps:
        1. Create role → confirm appears in Add Team Member form queryset
        2. Delete role → confirm removed from form queryset
        3. Verify only valid roles shown (no orphaned/deleted)
        4. Verify permissions unchanged (assignability rules still enforced)
        """
        from .forms import SubUserForm
        from .models import AccountGroup
        
        # Step 1: Create role
        role_ag = create_account_group(
            self.account,
            role_name='Verification Role',
            permission_codenames=['requisitions.view_requisition'],
        )
        
        # Step 2: Confirm appears in Add Team Member form queryset
        form = SubUserForm(account_owner=self.owner, creating=True)
        role_queryset = form.fields['role'].queryset
        role_pks_before = set(role_queryset.values_list('pk', flat=True))
        self.assertIn(
            role_ag.pk,
            role_pks_before,
            'New role must appear in Add Team Member role dropdown',
        )
        
        # Step 3: Delete role
        from .services import remove_group_from_all_users_and_delete
        remove_group_from_all_users_and_delete(role_ag)
        
        # Verify AccountGroup and Group are both deleted
        self.assertFalse(
            AccountGroup.objects.filter(pk=role_ag.pk).exists(),
            'AccountGroup must be deleted',
        )
        from django.contrib.auth.models import Group
        self.assertFalse(
            Group.objects.filter(pk=role_ag.group_id).exists(),
            'Django Group must be deleted',
        )
        
        # Step 4: Reload Add Team Member form - deleted role must not appear
        form2 = SubUserForm(account_owner=self.owner, creating=True)
        role_queryset2 = form2.fields['role'].queryset
        role_pks_after = set(role_queryset2.values_list('pk', flat=True))
        
        self.assertNotIn(
            role_ag.pk,
            role_pks_after,
            'Deleted role must NOT appear in Add Team Member role dropdown',
        )
        
        # Step 5: Verify only valid roles shown (queryset matches DB state)
        db_role_pks = set(
            AccountGroup.objects.filter(account=self.account)
            .values_list('pk', flat=True)
        )
        # Form queryset should be subset of DB (filtered by assignability)
        self.assertTrue(
            role_pks_after.issubset(db_role_pks),
            'Form queryset must only contain roles that exist in database',
        )
        
        # Step 6: Verify permissions unchanged (assignability still enforced)
        # Form queryset should still respect permission boundaries
        from .permission_boundaries import get_account_groups_assigner_may_assign
        expected_queryset = get_account_groups_assigner_may_assign(self.account, self.owner)
        expected_pks = set(expected_queryset.values_list('pk', flat=True))
        self.assertEqual(
            role_pks_after,
            expected_pks,
            'Form queryset must match permission boundaries exactly',
        )
        
        # PASS: Dropdown matches database state exactly

    def test_create_team_member_with_role_then_login_has_correct_permissions(self):
        """Create team member with a role, log in as them; allowed features work, forbidden return 403."""
        role_ag = create_account_group(
            self.account,
            role_name='Requisition Viewer',
            permission_codenames=['requisitions.view_requisition'],
        )
        self.client.force_login(self.owner)
        add_url = reverse('accounts:subuser_create')
        response = self.client.post(add_url, data={
            'email': 'teammate@test.com',
            'full_name': 'Teammate One',
            'password': 'teampass123',
            'is_active': True,
            'role': role_ag.pk,
        })
        self.assertEqual(response.status_code, 302, 'Create should redirect')
        self.assertRedirects(response, reverse('accounts:subuser_list'))

        sub_user = SubUser.objects.get(email='teammate@test.com', account_owner=self.owner)
        self.assertIsNotNone(sub_user.linked_user_id, 'SubUser must have linked_user after create')
        linked_user = sub_user.linked_user
        linked_user.refresh_from_db()
        self.assertTrue(
            linked_user.has_perm('requisitions.view_requisition'),
            'Team member with Requisition Viewer role must have view_requisition',
        )
        self.assertFalse(
            linked_user.has_perm('requisitions.add_requisition'),
            'Team member without add_requisition in role must not have add_requisition',
        )

        self.client.force_login(linked_user)
        list_resp = self.client.get(reverse('requisitions:list'))
        self.assertEqual(list_resp.status_code, 200, 'Allowed feature (requisition list) must work')
        from apps.requisitions.models import Requisition
        from apps.core.models import CompanyProfile
        cp = CompanyProfile.objects.get_or_create(
            user=self.owner,
            defaults={'account': self.account, 'company_name': 'Test Co', 'email': 'test@test.com'},
        )[0]
        if not cp.account_id:
            cp.account = self.account
            cp.save()
        req = Requisition.objects.create(
            company=cp,
            account=self.account,
            created_by=self.owner,
            organization_name='Test Org',
        )
        edit_resp = self.client.get(reverse('requisitions:edit', kwargs={'pk': req.pk}))
        self.assertEqual(edit_resp.status_code, 403, 'Forbidden feature (requisition edit) must return 403')

    def test_change_role_permissions_relogin_permissions_update_immediately(self):
        """Change role permissions, re-login as team member; permissions update immediately."""
        from apps.accounts.services import update_account_group_permissions
        from apps.core.models import CompanyProfile

        CompanyProfile.objects.get_or_create(
            user=self.owner,
            defaults={'account': self.account, 'company_name': 'Sync Co', 'email': 'sync@test.com'},
        )
        view_only_ag = create_account_group(
            self.account,
            role_name='Requisition Viewer',
            permission_codenames=['requisitions.view_requisition'],
        )
        self.client.force_login(self.owner)
        self.client.post(reverse('accounts:subuser_create'), data={
            'email': 'sync_test@test.com',
            'full_name': 'Sync Test',
            'password': 'synctest123',
            'is_active': True,
            'role': view_only_ag.pk,
        })
        sub = SubUser.objects.get(email='sync_test@test.com', account_owner=self.owner)
        linked = sub.linked_user

        self.client.force_login(linked)
        self.assertTrue(linked.has_perm('requisitions.view_requisition'))
        self.assertFalse(linked.has_perm('requisitions.change_requisition'))
        r1 = self.client.get(reverse('requisitions:list'))
        self.assertEqual(r1.status_code, 200, 'View list must work')
        r2 = self.client.get(reverse('requisitions:create'))
        self.assertEqual(r2.status_code, 403, 'Create must be 403 with view-only role')

        update_account_group_permissions(view_only_ag, ['requisitions.view_requisition', 'requisitions.add_requisition'])
        linked.refresh_from_db()
        for attr in ('_perm_cache', '_group_perm_cache', '_obj_perm_cache'):
            if hasattr(linked, attr):
                delattr(linked, attr)
        self.assertTrue(linked.has_perm('requisitions.add_requisition'), 'After role update, must have add_requisition')

        self.client.logout()
        self.client.force_login(linked)
        r3 = self.client.get(reverse('requisitions:create'))
        self.assertEqual(r3.status_code, 200, 'After role update + re-login, create must be 200')

    def test_assign_higher_role_fails_for_limited_assigner(self):
        """A user who can only assign a low-permission role cannot assign a higher-permission role."""
        low_ag = create_account_group(
            self.account,
            role_name='Viewer',
            permission_codenames=['requisitions.view_requisition', 'accounts.add_subuser'],
        )
        high_ag = create_account_group(
            self.account,
            role_name='Editor',
            permission_codenames=['requisitions.view_requisition', 'requisitions.add_requisition', 'requisitions.change_requisition'],
        )
        assigner = _create_user('assigner@test.com', self.account)
        assigner.groups.clear()
        assign_user_to_account_group(assigner, low_ag)
        assigner.refresh_from_db()

        self.client.force_login(assigner)
        add_url = reverse('accounts:subuser_create')
        get_resp = self.client.get(add_url)
        self.assertEqual(get_resp.status_code, 200, 'Assigner with add_subuser must access Add Team Member')
        form = get_resp.context['form']
        assignable_ids = list(form.fields['role'].queryset.values_list('pk', flat=True))
        self.assertIn(low_ag.pk, assignable_ids, 'Assigner must see Viewer role')
        self.assertNotIn(high_ag.pk, assignable_ids, 'Assigner must NOT see Editor role (higher than their perms)')

        tampered_post = {
            'email': 'victim@test.com',
            'full_name': 'Victim',
            'password': 'victim123',
            'is_active': True,
            'role': high_ag.pk,
        }
        post_resp = self.client.post(add_url, data=tampered_post)
        self.assertEqual(post_resp.status_code, 403, 'Tampered POST with higher role must return 403')
        self.assertFalse(SubUser.objects.filter(email='victim@test.com').exists(), 'Team member must not be created')


# =============================================================================
# Activity logging accuracy and tenant safety verification (TEST 1–4)
# =============================================================================

class ActivityLoggingVerificationTests(TransactionTestCase):
    """Verify activity logging accuracy and tenant safety per specification."""

    def setUp(self):
        self.account, self.owner = _create_account_with_owner('owner@activity.test', 'Activity Test Account')
        self.client = Client()

    # ----- TEST 1 — Basic activity: login/logout as owner -----
    def test_1_login_logout_entries_with_correct_actor_and_timestamp(self):
        """Log in as account owner, log out; confirm LOGIN/LOGOUT entries with correct actor and timestamp."""
        login_url = reverse('accounts:login')
        logout_url = reverse('accounts:logout')
        # Login (POST) — do not follow redirects so we only assert login succeeded (302)
        r = self.client.post(login_url, {
            'username': self.owner.email,
            'password': 'testpass123',
        })
        self.assertEqual(r.status_code, 302, 'Login POST should redirect on success')
        self.assertTrue(
            self.client.session.get('_auth_user_id'),
            'Session must have authenticated user after login',
        )
        # Logout
        self.client.post(logout_url, {})
        from django.utils import timezone
        now = timezone.now()
        logins = UserActivity.objects.filter(user=self.owner, activity_type='LOGIN').order_by('-timestamp')
        logouts = UserActivity.objects.filter(user=self.owner, activity_type='LOGOUT').order_by('-timestamp')
        self.assertGreaterEqual(logins.count(), 1, 'At least one LOGIN entry must appear')
        self.assertGreaterEqual(logouts.count(), 1, 'At least one LOGOUT entry must appear')
        last_login = logins.first()
        last_logout = logouts.first()
        self.assertEqual(last_login.user_id, self.owner.id, 'LOGIN actor must be owner')
        self.assertEqual(last_logout.user_id, self.owner.id, 'LOGOUT actor must be owner')
        self.assertEqual(last_login.account_id, self.account.id, 'LOGIN must be tied to account')
        self.assertEqual(last_logout.account_id, self.account.id, 'LOGOUT must be tied to account')
        # Timestamps within last 2 minutes
        self.assertLess((now - last_login.timestamp).total_seconds(), 120, 'LOGIN timestamp should be recent')
        self.assertLess((now - last_logout.timestamp).total_seconds(), 120, 'LOGOUT timestamp should be recent')

    # ----- TEST 2 — Team member actions -----
    def test_2_team_member_actions_logged_with_correct_actor_and_account(self):
        """Log in as team member; perform action; confirm actions logged with team member as actor and correct account."""
        from django.contrib.auth.hashers import make_password
        # Create linked User for team member (so login sets session sub_user_id)
        team_user = User.objects.create_user(
            email='team@activity.test',
            password='teampass123',
            account=self.account,
            first_name='Team',
            last_name='Member',
        )
        sub = SubUser.objects.create(
            account_owner=self.owner,
            linked_user=team_user,
            email='team@activity.test',
            full_name='Team Member',
            password_hash=make_password('teampass123'),
            is_active=True,
            is_staff=False,
        )
        # Give team user permission to view security so GET returns 200 and middleware logs
        ag = create_account_group(
            self.account,
            role_name='Activity Viewer',
            permission_codenames=['accounts.view_activity_log'],
        )
        assign_user_to_account_group(team_user, ag)
        team_user.refresh_from_db()
        # Real login so login view sets session['sub_user_id'] for team member
        login_url = reverse('accounts:login')
        r = self.client.post(login_url, {
            'username': 'team@activity.test',
            'password': 'teampass123',
        })
        self.assertEqual(r.status_code, 302, 'Team member login should redirect')
        self.assertEqual(self.client.session.get('sub_user_id'), str(sub.id), 'Session must have sub_user_id after team login')
        # Request security dashboard (200) so middleware logs with sub_user
        r = self.client.get(reverse('accounts:security_dashboard'))
        self.assertEqual(r.status_code, 200, 'Team member must get 200 on security dashboard')
        # Check: at least one activity for this account with team member as actor
        activities = UserActivity.objects.filter(account=self.account).order_by('-timestamp')[:20]
        team_activities = [a for a in activities if a.sub_user_id == sub.id]
        self.assertGreaterEqual(
            len(team_activities),
            1,
            'At least one activity must be logged with team member as actor (e.g. page view)',
        )
        a = team_activities[0]
        self.assertEqual(a.account_id, self.account.id, 'Activity must belong to correct account')
        self.assertEqual(a.sub_user_id, sub.id, 'Actor must be the team member (sub_user)')

    # ----- TEST 3 — Security actions: role permission change, add team member -----
    def test_3_role_permission_change_and_add_team_member_logged(self):
        """Change a role's permissions; add a team member; confirm these actions are logged with target."""
        from apps.accounts.services import update_account_group_permissions
        ag = create_account_group(
            self.account,
            role_name='Test Role',
            permission_codenames=['accounts.view_subuser'],
        )
        before_perm = UserActivity.objects.filter(
            account=self.account,
            activity_type='PERMISSION_CHANGE',
        ).count()
        update_account_group_permissions(ag, ['accounts.view_subuser', 'accounts.add_subuser'])
        after_perm = UserActivity.objects.filter(
            account=self.account,
            activity_type='PERMISSION_CHANGE',
        ).count()
        self.assertGreater(after_perm, before_perm, 'Changing role permissions must log PERMISSION_CHANGE')

        before_sub = UserActivity.objects.filter(
            account=self.account,
            activity_type='CREATE',
            model_name='SubUser',
        ).count()
        from django.contrib.auth.hashers import make_password
        team_user = User.objects.create_user(
            email='newmember@activity.test',
            password='newpass123',
            account=self.account,
            first_name='New',
            last_name='Member',
        )
        SubUser.objects.create(
            account_owner=self.owner,
            linked_user=team_user,
            email='newmember@activity.test',
            full_name='New Member',
            password_hash=make_password('newpass123'),
            is_active=True,
            is_staff=False,
        )
        after_sub = UserActivity.objects.filter(
            account=self.account,
            activity_type='CREATE',
            model_name='SubUser',
        ).count()
        self.assertGreater(after_sub, before_sub, 'Adding team member must log CREATE SubUser')

    # ----- TEST 4 — Permission enforcement: no view_activity_log => 403 -----
    def test_4_security_dashboard_403_without_view_activity_log(self):
        """User without view_activity_log (and without view_useractivity) gets 403 on /auth/security/."""
        user = _create_user('noperm@activity.test', self.account)
        user.groups.clear()
        user.user_permissions.clear()
        user.save()
        self.client.force_login(user)
        url = reverse('accounts:security_dashboard')
        r = self.client.get(url)
        self.assertEqual(r.status_code, 403, '/auth/security/ must return 403 without view_activity_log or view_useractivity')

    def test_4b_security_dashboard_200_with_view_activity_log(self):
        """User with view_activity_log can access /auth/security/."""
        user = _create_user('hasperm@activity.test', self.account)
        user.groups.clear()
        user.user_permissions.clear()
        user.save()
        ag = create_account_group(
            self.account,
            role_name='Activity Viewer',
            permission_codenames=['accounts.view_activity_log'],
        )
        assign_user_to_account_group(user, ag)
        user.refresh_from_db()
        self.client.force_login(user)
        r = self.client.get(reverse('accounts:security_dashboard'))
        self.assertEqual(r.status_code, 200, 'Security dashboard must return 200 with view_activity_log')


class ForceLogoutAllUsersTests(TransactionTestCase):
    """Log out all users: admin triggers terminate-all and other users are logged out immediately."""

    def setUp(self):
        self.account, self.owner = _create_account_with_owner('admin@force-logout.test', 'Force Logout Account')
        self.user_a = _create_user('usera@force-logout.test', self.account, password='passa123')
        # Admin needs change_usersession and view_activity_log to use security dashboard and terminate-all
        from django.contrib.auth.models import Permission
        change_sess = Permission.objects.get(codename='change_usersession', content_type__app_label='accounts')
        view_log = Permission.objects.get(codename='view_activity_log', content_type__app_label='accounts')
        self.owner.user_permissions.add(change_sess, view_log)
        self.owner.save()

    def test_force_logout_all_invalidates_other_user_sessions(self):
        """When admin triggers 'Log out all users', User A's session is deleted and next request redirects to login."""
        from django.contrib.sessions.models import Session
        from apps.accounts.models import UserSession

        login_url = reverse('accounts:login')
        terminate_url = reverse('accounts:terminate_all_sessions')
        dashboard_url = reverse('accounts:security_dashboard')

        # User A logs in via login view so UserSession is created with session_key
        client_a = Client()
        r = client_a.post(login_url, {'username': self.user_a.email, 'password': 'passa123'}, follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.wsgi_request.user.is_authenticated, 'User A must be logged in')
        session_key_a = client_a.session.session_key
        self.assertIsNotNone(session_key_a)
        self.assertTrue(
            UserSession.objects.filter(user=self.user_a, session_key=session_key_a, is_active=True).exists(),
            'UserSession for User A must exist',
        )
        self.assertTrue(
            Session.objects.filter(session_key=session_key_a).exists(),
            'Django session for User A must exist',
        )

        # Admin logs in and triggers terminate all sessions
        self.client.force_login(self.owner)
        r = self.client.post(terminate_url, {}, follow=True)
        self.assertEqual(r.status_code, 200)
        messages = list(r.context.get('messages', []))
        self.assertTrue(
            any('terminated' in str(m) for m in messages),
            'Admin must see success message',
        )

        # User A's Django session must be deleted
        self.assertFalse(
            Session.objects.filter(session_key=session_key_a).exists(),
            'User A session must be deleted from django_session',
        )
        # User A's UserSession must be marked ended
        us = UserSession.objects.get(user=self.user_a, session_key=session_key_a)
        self.assertFalse(us.is_active, 'UserSession for User A must be marked ended')

        # User A's next request gets redirected to login (no cached access)
        r = client_a.get(dashboard_url, follow=False)
        self.assertEqual(r.status_code, 302, 'User A must be redirected')
        self.assertIn(login_url.split('?')[0], r.get('Location', ''), 'User A must be sent to login')

    def test_direct_url_after_force_logout_returns_302_or_403(self):
        """TEST 2 — No stale access: direct URL after logout yields 302 to login or 403."""
        from django.contrib.sessions.models import Session
        from apps.accounts.models import UserSession

        login_url = reverse('accounts:login')
        terminate_url = reverse('accounts:terminate_all_sessions')
        dashboard_url = reverse('accounts:security_dashboard')

        client_a = Client()
        client_a.post(login_url, {'username': self.user_a.email, 'password': 'passa123'}, follow=True)
        session_key_a = client_a.session.session_key

        self.client.force_login(self.owner)
        self.client.post(terminate_url, {})

        self.assertFalse(Session.objects.filter(session_key=session_key_a).exists(), 'Session must be deleted')

        # Direct URL access (no follow) must be 302 to login or 403
        r = client_a.get(dashboard_url, follow=False)
        self.assertIn(r.status_code, (302, 403), 'Must get 302 or 403 after force logout')
        if r.status_code == 302:
            self.assertIn(login_url.split('?')[0], r.get('Location', ''), 'Redirect must be to login')

    def test_other_company_session_remains_active(self):
        """TEST 3 — Tenant safety: user from another company is not logged out."""
        from django.contrib.sessions.models import Session
        from django.contrib.auth.models import Permission

        # Second account and user (different company)
        account_b, owner_b = _create_account_with_owner('owner-b@other.test', 'Other Company')
        user_b = _create_user('userb@other.test', account_b, password='passb123')
        view_log = Permission.objects.get(codename='view_activity_log', content_type__app_label='accounts')
        user_b.user_permissions.add(view_log)
        user_b.save()

        login_url = reverse('accounts:login')
        terminate_url = reverse('accounts:terminate_all_sessions')
        dashboard_url = reverse('accounts:security_dashboard')

        # User B (other company) logs in
        client_b = Client()
        r = client_b.post(login_url, {'username': user_b.email, 'password': 'passb123'}, follow=True)
        self.assertTrue(r.wsgi_request.user.is_authenticated, 'User B must be logged in')
        session_key_b = client_b.session.session_key
        self.assertIsNotNone(session_key_b)

        # Admin of Company A triggers "log out all users"
        self.client.force_login(self.owner)
        self.client.post(terminate_url, {})

        # User B's session must still exist
        self.assertTrue(
            Session.objects.filter(session_key=session_key_b).exists(),
            'Other company session must NOT be deleted',
        )
        # User B can still access dashboard (200 = still authenticated and authorized)
        r = client_b.get(dashboard_url, follow=False)
        self.assertEqual(r.status_code, 200, 'Other company user must still get 200 (session intact)')
        self.assertTrue(r.wsgi_request.user.is_authenticated, 'User B must remain authenticated')


@override_settings(STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage')
class PermissionVisibilityVerificationTests(TransactionTestCase):
    """
    Verify permission-based visibility: team list is company-wide; template/layout
    links are hidden when permission is missing. Return PASS only if visibility
    matches permissions exactly.
    """
    def setUp(self):
        self.account, self.owner = _create_account_with_owner('owner@permvis.test', 'PermVis Account')
        self.client = Client()
        # CompanyProfile so request.company is set for team members (get_company_profile_for_user)
        from apps.core.models import CompanyProfile
        CompanyProfile.objects.get_or_create(
            user=self.owner,
            defaults={'account': self.account, 'company_name': 'PermVis Co', 'email': 'owner@permvis.test'},
        )

    def test_1_team_admin_sees_all_company_team_members_and_can_add(self):
        """Admin user with team management perms sees ALL company SubUsers and can add new ones."""
        # Role with view + add subuser
        team_ag = create_account_group(
            self.account,
            role_name='Team Admin',
            permission_codenames=['accounts.view_subuser', 'accounts.add_subuser', 'auth.view_group'],
        )
        self.owner.groups.add(team_ag.group)
        self.owner.refresh_from_db()

        # Create two SubUsers (so company has 2 team members; owner is not a SubUser)
        self.client.force_login(self.owner)
        add_url = reverse('accounts:subuser_create')
        for i, (email, name) in enumerate([('teammate_a@permvis.test', 'Teammate A'), ('teammate_b@permvis.test', 'Teammate B')], 1):
            self.client.post(add_url, data={
                'email': email,
                'full_name': name,
                'password': 'teampass123',
                'is_active': True,
                'role': team_ag.pk,
            })

        sub_a = SubUser.objects.get(email='teammate_a@permvis.test', account_owner=self.owner)
        sub_b = SubUser.objects.get(email='teammate_b@permvis.test', account_owner=self.owner)
        self.assertEqual(SubUser.objects.filter(account_owner__account=self.account).count(), 2)

        # Log in as owner (has team admin role) and open team list
        self.client.force_login(self.owner)
        list_url = reverse('accounts:subuser_list')
        r = self.client.get(list_url)
        self.assertEqual(r.status_code, 200, 'Team list must return 200 for user with view_subuser')
        # All company team members must be visible (company-wide visibility)
        self.assertIn(sub_a.full_name, r.content.decode() or '', 'Teammate A must appear in team list')
        self.assertIn(sub_b.full_name, r.content.decode() or '', 'Teammate B must appear in team list')
        self.assertIn('Teammate A', r.content.decode() or '')
        self.assertIn('Teammate B', r.content.decode() or '')

        # Can add new team member
        r2 = self.client.post(add_url, data={
            'email': 'teammate_c@permvis.test',
            'full_name': 'Teammate C',
            'password': 'teampass123',
            'is_active': True,
            'role': team_ag.pk,
        })
        self.assertIn(r2.status_code, (200, 302), 'Add team member must succeed or redirect')
        if r2.status_code == 302:
            self.assertRedirects(r2, list_url)
        self.assertTrue(
            SubUser.objects.filter(email='teammate_c@permvis.test', account_owner__account=self.account).exists(),
            'New team member must exist under account',
        )
        r3 = self.client.get(list_url)
        self.assertIn('Teammate C', r3.content.decode() or '', 'New member must appear in team list')

    def test_2_team_member_with_team_admin_sees_all_company_team_members(self):
        """Team member (SubUser) with view_subuser sees ALL company SubUsers, not just themselves."""
        team_ag = create_account_group(
            self.account,
            role_name='Team Viewer',
            permission_codenames=['accounts.view_subuser', 'accounts.add_subuser', 'auth.view_group'],
        )
        self.owner.groups.add(team_ag.group)
        self.owner.refresh_from_db()
        self.client.force_login(self.owner)
        add_url = reverse('accounts:subuser_create')
        # Create SubUser A
        self.client.post(add_url, data={
            'email': 'teammate_a2@permvis.test',
            'full_name': 'Member A',
            'password': 'teampass123',
            'is_active': True,
            'role': team_ag.pk,
        })
        # Create SubUser B with view-only role (so B can view team list but not add)
        viewer_ag = create_account_group(
            self.account,
            role_name='Team Only Viewer',
            permission_codenames=['accounts.view_subuser'],
        )
        self.client.post(add_url, data={
            'email': 'teammate_b2@permvis.test',
            'full_name': 'Member B',
            'password': 'teampass123',
            'is_active': True,
            'role': viewer_ag.pk,
        })
        sub_a = SubUser.objects.get(email='teammate_a2@permvis.test', account_owner=self.owner)
        sub_b = SubUser.objects.get(email='teammate_b2@permvis.test', account_owner=self.owner)
        linked_b = sub_b.linked_user

        # Log in as Member B (SubUser) and open team list
        self.client.force_login(linked_b)
        list_url = reverse('accounts:subuser_list')
        r = self.client.get(list_url)
        self.assertEqual(r.status_code, 200, 'Team member with view_subuser must get team list 200')
        content = r.content.decode() or ''
        # Must see all company SubUsers (A and B), not empty list
        self.assertIn('Member A', content, 'Team member must see other member A')
        self.assertIn('Member B', content, 'Team member must see themselves (Member B)')
        self.assertGreaterEqual(
            content.count('permvis.test'),
            2,
            'At least two team members must appear (emails)',
        )

    def test_3_job_order_layouts_link_hidden_without_view_product(self):
        """User with view_order but NOT view_product must not see Job Order Layouts link in sidebar."""
        from apps.core.models import CompanyProfile
        CompanyProfile.objects.get_or_create(
            user=self.owner,
            defaults={'account': self.account, 'company_name': 'PermVis Co', 'email': 'owner@permvis.test'},
        )
        # Role: view_order only (no view_product)
        order_only_ag = create_account_group(
            self.account,
            role_name='Order Only',
            permission_codenames=['job_orders.view_order'],
        )
        user = _create_user('orderonly@permvis.test', self.account)
        user.groups.add(order_only_ag.group)
        user.save()
        self.client.force_login(user)
        # Page that renders sidebar (dashboard uses base.html with sidebar)
        r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 200)
        content = r.content.decode() or ''
        # Job Order Layouts link must be hidden (it requires view_product)
        self.assertNotIn('Job Order Layouts', content, 'Job Order Layouts link must be hidden without view_product')
        # Job Orders link may appear (view_order grants it)
        self.assertIn('Job Orders', content, 'Job Orders nav item may appear when user has view_order')

    def test_4_waybill_templates_link_hidden_without_view_waybilltemplate(self):
        """User with view_waybill but NOT view_waybilltemplate must not see Manage Templates on waybill list."""
        waybill_ag = create_account_group(
            self.account,
            role_name='Waybill Only',
            permission_codenames=['waybills.view_waybill'],
        )
        user = _create_user('waybillonly@permvis.test', self.account)
        user.groups.add(waybill_ag.group)
        user.save()
        from apps.core.models import CompanyProfile
        CompanyProfile.objects.get_or_create(
            user=self.owner,
            defaults={'account': self.account, 'company_name': 'PermVis Co', 'email': 'owner@permvis.test'},
        )
        self.client.force_login(user)
        r = self.client.get(reverse('waybills:list'))
        self.assertEqual(r.status_code, 200)
        content = r.content.decode() or ''
        self.assertNotIn('Manage Templates', content, 'Manage Templates must be hidden without view_waybilltemplate')

    def test_5_requisition_list_loads_with_view_requisition(self):
        """User with view_requisition can load requisition list."""
        req_ag = create_account_group(
            self.account,
            role_name='Requisition Only',
            permission_codenames=['requisitions.view_requisition'],
        )
        user = _create_user('reqonly@permvis.test', self.account)
        user.groups.add(req_ag.group)
        user.save()
        from apps.core.models import CompanyProfile
        CompanyProfile.objects.get_or_create(
            user=self.owner,
            defaults={'account': self.account, 'company_name': 'PermVis Co', 'email': 'owner@permvis.test'},
        )
        self.client.force_login(user)
        r = self.client.get(reverse('requisitions:list'))
        self.assertEqual(r.status_code, 200)
        content = r.content.decode() or ''
        self.assertIn('Requisition', content)

    def test_6_invoice_templates_sidebar_hidden_without_view_invoicetemplate(self):
        """User with view_invoice but NOT view_invoicetemplate must not see Invoice Templates in sidebar."""
        inv_ag = create_account_group(
            self.account,
            role_name='Invoice Only',
            permission_codenames=['invoices.view_invoice'],
        )
        user = _create_user('invoiceonly@permvis.test', self.account)
        user.groups.add(inv_ag.group)
        user.save()
        from apps.core.models import CompanyProfile
        CompanyProfile.objects.get_or_create(
            user=self.owner,
            defaults={'account': self.account, 'company_name': 'PermVis Co', 'email': 'owner@permvis.test'},
        )
        self.client.force_login(user)
        r = self.client.get(reverse('core:dashboard'))
        self.assertEqual(r.status_code, 200)
        content = r.content.decode() or ''
        self.assertNotIn('Invoice Templates', content, 'Invoice Templates sidebar link must be hidden')
