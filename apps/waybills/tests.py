# Tests for waybills app: delivery quantity parsing, persistence, and computations

import json
from django.test import TestCase
from django.contrib.auth import get_user_model

from apps.core.models import Account
from apps.waybills.models import Waybill, WaybillTemplate
from apps.waybills.utils.quantity_parser import extract_numeric_value
from apps.waybills.views import get_waybill_context

User = get_user_model()


class QuantityParserTest(TestCase):
    """Verify quantity extraction and computation accuracy."""

    def test_extract_numeric_value_integers(self):
        self.assertEqual(extract_numeric_value('500'), 500.0)
        self.assertEqual(extract_numeric_value('0'), 0.0)
        self.assertEqual(extract_numeric_value('30'), 30.0)

    def test_extract_numeric_value_with_units(self):
        self.assertEqual(extract_numeric_value('500kg'), 500.0)
        self.assertEqual(extract_numeric_value('7.5 tons'), 7.5)
        self.assertEqual(extract_numeric_value('300 bags'), 300.0)
        self.assertEqual(extract_numeric_value('1000pcs'), 1000.0)

    def test_extract_numeric_value_decimals(self):
        self.assertEqual(extract_numeric_value('500.5'), 500.5)
        self.assertEqual(extract_numeric_value('0.25 kg'), 0.25)

    def test_extract_numeric_value_empty_or_invalid(self):
        self.assertEqual(extract_numeric_value(''), 0.0)
        self.assertEqual(extract_numeric_value(None), 0.0)
        self.assertEqual(extract_numeric_value('no number'), 0.0)
        self.assertEqual(extract_numeric_value('   '), 0.0)

    def test_remaining_computation_accuracy(self):
        # remaining = max(0, total - delivered)
        total = extract_numeric_value('500kg')
        delivered = extract_numeric_value('300kg')
        remaining = max(0.0, total - delivered)
        self.assertEqual(remaining, 200.0)

        total = extract_numeric_value('30 bags')
        delivered = extract_numeric_value('30 bags')
        self.assertEqual(max(0.0, total - delivered), 0.0)

        total = extract_numeric_value('100')
        delivered = extract_numeric_value('150')  # over-delivered
        self.assertEqual(max(0.0, total - delivered), 0.0)


class WaybillDeliveryQuantitiesPersistenceTest(TestCase):
    """Verify waybill creation saves delivery_quantities to DB and computations are correct."""

    def setUp(self):
        self.account = Account.objects.create(name='Waybill Test Account', owner=None)
        self.user = User.objects.create_user(
            email='waybill@test.com',
            password='testpass123',
            account=self.account,
        )
        self.template = WaybillTemplate.objects.create(
            user=self.user,
            name='Test Template',
            is_default=True,
        )

    def test_single_delivery_quantity_saved_and_main_fields_set(self):
        """Single row: custom_data.delivery_quantities and main model fields both set."""
        waybill = Waybill(
            user=self.user,
            template=self.template,
            total_quantity_input='500kg',
            delivered_quantity_input='300kg',
            custom_data={
                'delivery_quantities': [
                    {
                        'product': 'Rice',
                        'total_quantity_input': '500kg',
                        'delivered_quantity_input': '300kg',
                    }
                ],
                'user_preferences': {},
                'sender_info': {},
                'receiver_info': {},
                'shipment_info': {},
            },
        )
        waybill.save()

        self.assertEqual(waybill.total_quantity_value, 500.0)
        self.assertEqual(waybill.delivered_quantity_value, 300.0)
        self.assertEqual(waybill.remaining_quantity_value, 200.0)

        # Reload from DB
        waybill.refresh_from_db()
        dq = waybill.custom_data.get('delivery_quantities')
        self.assertIsNotNone(dq)
        self.assertEqual(len(dq), 1)
        self.assertEqual(dq[0]['product'], 'Rice')
        self.assertEqual(dq[0]['total_quantity_input'], '500kg')
        self.assertEqual(dq[0]['delivered_quantity_input'], '300kg')

    def test_multiple_delivery_quantities_saved_in_custom_data(self):
        """Multiple rows: stored only in custom_data; main fields empty."""
        waybill = Waybill(
            user=self.user,
            template=self.template,
            total_quantity_input='',  # multiple rows => empty main fields
            delivered_quantity_input='',
            custom_data={
                'delivery_quantities': [
                    {'product': 'Rice', 'total_quantity_input': '500kg', 'delivered_quantity_input': '300kg'},
                    {'product': 'Beans', 'total_quantity_input': '30 bags', 'delivered_quantity_input': '10 bags'},
                ],
                'user_preferences': {},
                'sender_info': {},
                'receiver_info': {},
                'shipment_info': {},
            },
        )
        waybill.save()

        waybill.refresh_from_db()
        dq = waybill.custom_data.get('delivery_quantities')
        self.assertEqual(len(dq), 2)
        self.assertEqual(dq[0]['product'], 'Rice')
        self.assertEqual(dq[0]['total_quantity_input'], '500kg')
        self.assertEqual(dq[1]['product'], 'Beans')
        self.assertEqual(dq[1]['total_quantity_input'], '30 bags')
        self.assertEqual(dq[1]['delivered_quantity_input'], '10 bags')

    def test_get_waybill_context_delivery_quantities_computations(self):
        """get_waybill_context returns correct remaining_display for each row."""
        waybill = Waybill(
            user=self.user,
            template=self.template,
            total_quantity_input='',
            delivered_quantity_input='',
            custom_data={
                'delivery_quantities': [
                    {'product': 'Rice', 'total_quantity_input': '500kg', 'delivered_quantity_input': '300kg'},
                    {'product': 'Beans', 'total_quantity_input': '30 bags', 'delivered_quantity_input': '10 bags'},
                ],
                'user_preferences': {},
                'sender_info': {},
                'receiver_info': {},
                'shipment_info': {},
            },
        )
        waybill.save()

        context = get_waybill_context(waybill, self.user, None)
        dq = context['delivery_quantities']
        self.assertEqual(len(dq), 2)

        # Rice: 500 - 300 = 200, unit "kg" (display includes space for readability)
        self.assertEqual(dq[0]['remaining_display'], '200 kg')
        self.assertEqual(dq[0]['product'], 'Rice')

        # Beans: 30 - 10 = 20, unit "bags"
        self.assertEqual(dq[1]['remaining_display'], '20 bags')
        self.assertEqual(dq[1]['product'], 'Beans')

    def test_over_delivery_computation_in_context(self):
        """Over-delivery: delivered > total shows correct over_display and status."""
        waybill = Waybill(
            user=self.user,
            template=self.template,
            total_quantity_input='100kg',
            delivered_quantity_input='120kg',
            custom_data={
                'delivery_quantities': [
                    {'product': 'Cement', 'total_quantity_input': '100kg', 'delivered_quantity_input': '120kg'},
                ],
                'user_preferences': {},
                'sender_info': {},
                'receiver_info': {},
                'shipment_info': {},
            },
        )
        waybill.save()

        context = get_waybill_context(waybill, self.user, None)
        dq = context['delivery_quantities']
        self.assertEqual(len(dq), 1)
        self.assertEqual(dq[0]['remaining_display'], '0 kg')
        self.assertEqual(dq[0]['over_delivery_val'], 20.0)
        self.assertEqual(dq[0]['over_display'], '20 kg')
        self.assertEqual(dq[0]['row_status'], 'over_delivered')
        self.assertEqual(dq[0]['row_status_label'], 'Over-delivered')

    def test_legacy_single_row_without_delivery_quantities_key(self):
        """Waybill with only main fields (no custom_data.delivery_quantities) still works."""
        waybill = Waybill(
            user=self.user,
            template=self.template,
            total_quantity_input='100 pcs',
            delivered_quantity_input='40 pcs',
            custom_data={
                'user_preferences': {},
                'sender_info': {},
                'receiver_info': {},
                'shipment_info': {},
            },
        )
        waybill.save()

        self.assertEqual(waybill.total_quantity_value, 100.0)
        self.assertEqual(waybill.delivered_quantity_value, 40.0)
        self.assertEqual(waybill.remaining_quantity_value, 60.0)

        context = get_waybill_context(waybill, self.user, None)
        dq = context['delivery_quantities']
        self.assertEqual(len(dq), 1)
        self.assertEqual(dq[0]['total_quantity_input'], '100 pcs')
        self.assertEqual(dq[0]['remaining_display'], '60 pcs')  # unit_str adds space before unit
