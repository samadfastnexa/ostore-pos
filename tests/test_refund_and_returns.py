# -*- coding: utf-8 -*-
"""Comprehensive test suite for Customer Refunds and Vendor Returns."""
from odoo import fields
from odoo.exceptions import ValidationError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestRefundAndReturns(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id

        # Setup POS Config
        cls.pos_config = cls.env['pos.config'].create({
            'name': 'Returns Test Register',
            'company_id': cls.company.id,
            'pos_retail_allow_no_receipt_return': True,
            'pos_retail_no_receipt_price_policy': 'current_price',
            'pos_retail_no_receipt_period_days': 30,
            'pos_retail_no_receipt_approval_mode': 'amount',
            'pos_retail_no_receipt_approval_limit': 3000.0,
        })

        # Partners
        cls.customer = cls.env['res.partner'].create({
            'name': 'Test Retail Customer',
            'company_id': cls.company.id,
            'customer_rank': 1,
        })
        cls.vendor = cls.env['res.partner'].create({
            'name': 'Test Supplier Co',
            'company_id': cls.company.id,
            'supplier_rank': 1,
        })

        # Manager
        cls.manager = cls.env['hr.employee'].create({
            'name': 'Approving Manager',
            'company_id': cls.company.id,
        })

        # Return reasons
        cls.cust_reason_damaged = cls.env['pos.retail.return.reason'].create({
            'name': 'Defective / Damaged',
            'sequence': 10,
        })
        cls.cust_reason_mind = cls.env['pos.retail.return.reason'].create({
            'name': 'Customer Changed Mind',
            'sequence': 20,
        })
        cls.vend_reason_defective = cls.env['pos.retail.vendor.return.reason'].create({
            'name': 'Defective / Quality Issue',
            'sequence': 10,
        })

        # Products
        cls.product_drill = cls.env['product.product'].create({
            'name': 'Power Drill 500W',
            'list_price': 5000.0,
            'standard_price': 3500.0,
            'available_in_pos': True,
        })
        cls.product_fittings = cls.env['product.product'].create({
            'name': 'Brass Pipe Fitting',
            'list_price': 200.0,
            'standard_price': 120.0,
            'available_in_pos': True,
        })

    def test_01_cumulative_return_quantities(self):
        """Test cumulative partial returns enforce: Returnable Qty = Original Qty - Previously Returned Qty."""
        # Create an original POS order with 10 units
        pos_session = self.env['pos.session'].create({
            'config_id': self.pos_config.id,
            'user_id': self.env.user.id,
        })

        order = self.env['pos.order'].create({
            'session_id': pos_session.id,
            'partner_id': self.customer.id,
            'lines': [(0, 0, {
                'product_id': self.product_fittings.id,
                'qty': 10.0,
                'price_unit': 200.0,
                'price_subtotal': 2000.0,
                'price_subtotal_incl': 2000.0,
            })],
            'amount_total': 2000.0,
            'amount_paid': 2000.0,
            'amount_tax': 0.0,
            'amount_return': 0.0,
        })
        orig_line = order.lines[0]
        self.assertEqual(orig_line.pos_retail_returned_qty, 0.0)
        self.assertEqual(orig_line.pos_retail_returnable_qty, 10.0)

        # First partial refund: 4 units
        refund1 = self.env['pos.order'].create({
            'session_id': pos_session.id,
            'partner_id': self.customer.id,
            'is_refund': True,
            'lines': [(0, 0, {
                'product_id': self.product_fittings.id,
                'qty': -4.0,
                'price_unit': 200.0,
                'price_subtotal': -800.0,
                'price_subtotal_incl': -800.0,
                'refunded_orderline_id': orig_line.id,
            })],
            'amount_total': -800.0,
            'amount_paid': -800.0,
            'amount_tax': 0.0,
            'amount_return': 0.0,
        })

        orig_line._compute_pos_retail_return_quantities()
        self.assertEqual(orig_line.pos_retail_returned_qty, 4.0)
        self.assertEqual(orig_line.pos_retail_returnable_qty, 6.0)

        # Second refund: attempting 7 units must fail constraint (6 remaining)
        with self.assertRaises(ValidationError):
            self.env['pos.order'].create({
                'session_id': pos_session.id,
                'partner_id': self.customer.id,
                'is_refund': True,
                'lines': [(0, 0, {
                    'product_id': self.product_fittings.id,
                    'qty': -7.0,
                    'price_unit': 200.0,
                    'price_subtotal': -1400.0,
                    'price_subtotal_incl': -1400.0,
                    'refunded_orderline_id': orig_line.id,
                })],
                'amount_total': -1400.0,
                'amount_paid': -1400.0,
                'amount_tax': 0.0,
                'amount_return': 0.0,
            })

    def test_02_no_receipt_pricing_policies(self):
        """Test calculation of refund prices across all 4 pricing policies."""
        # Option 1: Current Price
        self.pos_config.pos_retail_no_receipt_price_policy = 'current_price'
        res = self.pos_config.get_no_receipt_product_price(self.product_drill.id)
        self.assertEqual(res['price'], 5000.0)

        # Option 3: Cost Price
        self.pos_config.pos_retail_no_receipt_price_policy = 'cost'
        res = self.pos_config.get_no_receipt_product_price(self.product_drill.id)
        self.assertEqual(res['price'], 3500.0)

        # Option 4: Manager determines price
        self.pos_config.pos_retail_no_receipt_price_policy = 'manager_price'
        res = self.pos_config.get_no_receipt_product_price(self.product_drill.id)
        self.assertTrue(res['requires_manager'])

    def test_03_customer_refund_approval_threshold(self):
        """Test Customer Refund requires manager approval above threshold."""
        # Refund amount 5,000 > threshold 3,000 -> requires manager
        refund = self.env['pos.retail.customer.refund'].create({
            'partner_id': self.customer.id,
            'company_id': self.company.id,
            'refund_method': 'cash',
            'line_ids': [(0, 0, {
                'product_id': self.product_drill.id,
                'quantity': 1.0,
                'price_unit': 5000.0,
                'return_reason_id': self.cust_reason_damaged.id,
                'product_condition': 'damaged',
            })],
        })
        self.assertTrue(refund.requires_manager_approval)

        # Confirming without manager must raise ValidationError
        with self.assertRaises(ValidationError):
            refund.action_confirm()

        # Add manager and confirm
        refund.manager_id = self.manager.id
        refund.action_confirm()
        self.assertEqual(refund.state, 'confirmed')

    def test_04_customer_refund_credit_ledger_processing(self):
        """Test processing Customer Refund with credit ledger settlement updates running balance."""
        refund = self.env['pos.retail.customer.refund'].create({
            'partner_id': self.customer.id,
            'company_id': self.company.id,
            'refund_method': 'credit_ledger',
            'line_ids': [(0, 0, {
                'product_id': self.product_fittings.id,
                'quantity': 2.0,
                'price_unit': 200.0,
                'return_reason_id': self.cust_reason_mind.id,
                'product_condition': 'resalable',
            })],
        })
        refund.action_confirm()
        refund.action_process()

        self.assertEqual(refund.state, 'done')
        self.assertTrue(refund.credit_note_id)
        self.assertEqual(refund.credit_note_id.move_type, 'out_refund')
        self.assertEqual(refund.credit_note_id.state, 'posted')
        self.assertTrue(refund.access_token)

    def test_05_vendor_return_processing(self):
        """Test processing Vendor Return with adjust payable debt."""
        v_return = self.env['pos.retail.vendor.return'].create({
            'partner_id': self.vendor.id,
            'company_id': self.company.id,
            'settlement_method': 'adjust_payable',
            'line_ids': [(0, 0, {
                'product_id': self.product_drill.id,
                'quantity': 1.0,
                'price_unit': 3500.0,
                'return_reason_id': self.vend_reason_defective.id,
                'product_condition': 'defective',
            })],
        })
        v_return.action_confirm()
        v_return.action_process()

        self.assertEqual(v_return.state, 'done')
        self.assertTrue(v_return.credit_note_id)
        self.assertEqual(v_return.credit_note_id.move_type, 'in_refund')
        self.assertEqual(v_return.credit_note_id.state, 'posted')
        self.assertTrue(v_return.access_token)
