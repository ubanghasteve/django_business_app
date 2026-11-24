"""
Verification tests for company context and action-level permission enforcement.

TEST 1 — TEAM MEMBER CONTEXT:
- No "create company" prompt when company exists
- Company name & logo visible
- Company profile loads read-only for team members

TEST 2 — ACTION PERMISSIONS (invoice, receipt, job order, quotation):
- User with ONLY view_X: list visible, print/download buttons hidden, direct URLs return 403
"""
from django.test import TransactionTestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from apps.core.models import Account, CompanyProfile
from apps.accounts.models import SubUser
from apps.accounts.services import (
    create_account_group,
    assign_user_to_account_group,
)
from apps.accounts.tests import _create_account_with_owner
from apps.invoices.models import Invoice
from apps.receipts.models import Receipt
from apps.quotations.models import Quotation
from apps.job_orders.models import Product

User = get_user_model()


class TeamMemberContextTests(TransactionTestCase):
    """TEST 1 — Team member sees company, no create prompt, profile read-only."""

    def setUp(self):
        self.account, self.owner = _create_account_with_owner()
        cp, _ = CompanyProfile.objects.get_or_create(
            user=self.owner,
            defaults={'account': self.account, 'company_name': 'Test Company', 'email': 'company@test.com'},
        )
        if not cp.account_id:
            cp.account = self.account
            cp.save()
        add_ag = create_account_group(
            self.account,
            role_name='Admin',
            permission_codenames=['accounts.add_subuser', 'core.view_companyprofile'],
        )
        assign_user_to_account_group(self.owner, add_ag)
        self.client = Client()

    def test_team_member_sees_company_no_create_prompt(self):
        """Team member: company name & logo visible, no 'Setup Required'."""
        ag = create_account_group(
            self.account,
            role_name='Viewer',
            permission_codenames=['core.view_companyprofile'],
        )
        self.client.force_login(self.owner)
        add_url = reverse('auth:subuser_create')
        self.client.post(add_url, data={
            'email': 'teammate@test.com',
            'full_name': 'Teammate One',
            'password': 'teampass123',
            'is_active': True,
            'role': ag.pk,
        })

        sub = SubUser.objects.get(email='teammate@test.com', account_owner=self.owner)
        linked = sub.linked_user
        self.client.force_login(linked)
        session = self.client.session
        session['sub_user_id'] = str(sub.id)
        session.save()

        resp = self.client.get(reverse('core:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('Setup Required', resp.content.decode(errors='replace'))
        self.assertIn(b'Test Company', resp.content)

    def test_team_member_company_profile_read_only(self):
        """Team member: company profile loads, shows company data (not create flow)."""
        ag = create_account_group(
            self.account,
            role_name='Viewer',
            permission_codenames=['core.view_companyprofile'],
        )
        self.client.force_login(self.owner)
        add_url = reverse('auth:subuser_create')
        self.client.post(add_url, data={
            'email': 'teammate2@test.com',
            'full_name': 'Teammate Two',
            'password': 'teampass123',
            'is_active': True,
            'role': ag.pk,
        })

        sub = SubUser.objects.get(email='teammate2@test.com', account_owner=self.owner)
        linked = sub.linked_user
        self.client.force_login(linked)
        session = self.client.session
        session['sub_user_id'] = str(sub.id)
        session.save()

        resp = self.client.get(reverse('core:company_profile'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Test Company', resp.content)


class ActionPermissionTests(TransactionTestCase):
    """TEST 2 & 3 — View-only user: list visible, print/download hidden, URLs return 403."""

    def setUp(self):
        self.account, self.owner = _create_account_with_owner()
        CompanyProfile.objects.get_or_create(
            user=self.owner,
            defaults={'account': self.account, 'company_name': 'Test Co', 'email': 'co@test.com'},
        )
        self.client = Client()

    def _create_view_only_user(self, perm_codename):
        """Create user with ONLY the given permission (e.g. invoices.view_invoice)."""
        app_label, codename = perm_codename.split('.')
        perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
        u = User.objects.create_user(
            email=f'viewonly_{codename}@test.com',
            password='viewpass123',
            account=self.account,
            first_name='View',
            last_name='Only',
        )
        u.user_permissions.add(perm)
        u.groups.clear()
        return u

    def test_invoice_view_only_print_download_403(self):
        """User with ONLY view_invoice: list OK, print/pdf URLs return 403."""
        u = self._create_view_only_user('invoices.view_invoice')
        inv = Invoice.objects.create(
            user=self.owner,
            client_name='Client',
            invoice_number='INV-001',
            grand_total=100,
        )
        self.client.force_login(u)

        list_resp = self.client.get(reverse('invoices:list'))
        self.assertEqual(list_resp.status_code, 200, 'Invoice list must be visible')

        detail_resp = self.client.get(reverse('invoices:detail', kwargs={'pk': inv.pk}))
        self.assertEqual(detail_resp.status_code, 200, 'Invoice detail must be visible')

        # Print and Download buttons must be hidden (URLs not in response)
        detail_html = detail_resp.content.decode(errors='replace')
        print_url = f'/invoices/{inv.pk}/print/'
        pdf_url = f'/invoices/{inv.pk}/pdf/'
        self.assertNotIn(print_url, detail_html, 'Print URL must not appear for view-only user')
        self.assertNotIn(pdf_url, detail_html, 'PDF URL must not appear for view-only user')

        # Direct access returns 403
        print_resp = self.client.get(reverse('invoices:print', kwargs={'pk': inv.pk}))
        self.assertEqual(print_resp.status_code, 403, 'Print must return 403')

        pdf_resp = self.client.get(reverse('invoices:pdf', kwargs={'pk': inv.pk}))
        self.assertEqual(pdf_resp.status_code, 403, 'PDF must return 403')

    def test_receipt_view_only_print_download_403(self):
        """User with ONLY view_receipt: list OK, print/pdf return 403."""
        inv = Invoice.objects.create(
            user=self.owner,
            client_name='Client',
            invoice_number='INV-REC',
            grand_total=100,
        )
        u = self._create_view_only_user('receipts.view_receipt')
        rec = Receipt.objects.create(
            created_by=self.owner,
            receipt_no='REC-001',
            invoice=inv,
            client_name='Client',
            amount_received=50,
            amount_in_words='Fifty',
            payment_method='cash',
            received_by='Test',
            balance_after_payment=50,
        )
        self.client.force_login(u)

        list_resp = self.client.get(reverse('receipts:list'))
        self.assertEqual(list_resp.status_code, 200)

        print_resp = self.client.get(reverse('receipts:print', kwargs={'receipt_id': rec.pk}))
        self.assertEqual(print_resp.status_code, 403)

        pdf_resp = self.client.get(reverse('receipts:pdf', kwargs={'receipt_id': rec.pk}))
        self.assertEqual(pdf_resp.status_code, 403)

    def test_job_order_view_only_print_download_403(self):
        """User with ONLY view_product: list OK, print/export return 403."""
        u = self._create_view_only_user('job_orders.view_product')
        prod = Product.objects.create(
            created_by=self.owner,
            job_order='JO-001',
            organization_name='Org',
            price=10,
            order_quantity=1,
        )
        prod.calculate_total()
        prod.save()
        self.client.force_login(u)

        list_resp = self.client.get(reverse('job_orders:products'))
        self.assertEqual(list_resp.status_code, 200)

        print_resp = self.client.get(reverse('job_orders:product_print', kwargs={'pk': prod.pk}))
        self.assertEqual(print_resp.status_code, 403)

        export_resp = self.client.get(reverse('job_orders:export_products_pdf'))
        self.assertEqual(export_resp.status_code, 403)

    def test_quotation_view_only_print_download_403(self):
        """User with ONLY view_quotation: list OK, print/export return 403."""
        u = self._create_view_only_user('quotations.view_quotation')
        quo = Quotation.objects.create(
            user=self.owner,
            quotation_number='QUO-001',
            grand_total=75,
        )
        self.client.force_login(u)

        list_resp = self.client.get(reverse('quotations:quotation_list'))
        self.assertEqual(list_resp.status_code, 200)

        print_resp = self.client.get(reverse('quotations:quotation_print', kwargs={'pk': quo.pk}))
        self.assertEqual(print_resp.status_code, 403)

        pdf_resp = self.client.get(reverse('quotations:quotation_pdf', kwargs={'pk': quo.pk}))
        self.assertEqual(pdf_resp.status_code, 403)
