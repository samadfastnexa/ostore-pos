"""Tests for cashier product-level discounts and minimum price enforcement."""
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLineDiscount(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.pos_config = cls.env['pos.config'].create({
            'name': 'Test POS Register',
            'company_id': cls.company.id,
            'pos_retail_line_discount_enabled': True,
            'pos_retail_line_discount_manager_below_min': True,
        })
        cls.manager = cls.env['hr.employee'].create({
            'name': 'Store Manager',
            'company_id': cls.company.id,
        })
        cls.cashier = cls.env['hr.employee'].create({
            'name': 'Cashier 1',
            'company_id': cls.company.id,
        })

        # Product A: Price 1,000, Min 850 (Max discount 15%)
        cls.prod_a = cls.env['product.product'].create({
            'name': 'Product A',
            'list_price': 1000.0,
            'minimum_selling_price': 850.0,
            'available_in_pos': True,
        })
        # Product B: Price 2,000, Min 1,900 (Max discount 5%)
        cls.prod_b = cls.env['product.product'].create({
            'name': 'Product B',
            'list_price': 2000.0,
            'minimum_selling_price': 1900.0,
            'available_in_pos': True,
        })
        # Product C: Price 500, No minimum price
        cls.prod_c = cls.env['product.product'].create({
            'name': 'Product C',
            'list_price': 500.0,
            'minimum_selling_price': 0.0,
            'available_in_pos': True,
        })

    def _create_order(self, lines_data):
        pos_order_lines = []
        for l in lines_data:
            vals = {
                'product_id': l['product'].id,
                'qty': l.get('qty', 1),
                'price_unit': l.get('price_unit', l['product'].list_price),
                'discount': l.get('discount', 0.0),
                'pos_retail_line_discount_manager_id': l.get('manager_id', False),
                'pos_retail_line_discount_input_type': l.get('input_type', 'percent'),
                'pos_retail_line_discount_reason': l.get('reason', ''),
                'pos_retail_min_price': l['product'].minimum_selling_price,
                'pos_retail_default_price': l['product'].list_price,
            }
            pos_order_lines.append((0, 0, vals))

        return self.env['pos.order'].create({
            'company_id': self.company.id,
            'config_id': self.pos_config.id,
            'employee_id': self.cashier.id,
            'cashier': self.cashier.name,
            'lines': pos_order_lines,
            'amount_tax': 0.0,
            'amount_total': sum(
                (l.get('price_unit', l['product'].list_price) * (1 - l.get('discount', 0) / 100.0)) * l.get('qty', 1)
                for l in lines_data
            ),
            'amount_paid': sum(
                (l.get('price_unit', l['product'].list_price) * (1 - l.get('discount', 0) / 100.0)) * l.get('qty', 1)
                for l in lines_data
            ),
            'amount_return': 0.0,
        })

    def test_01_discount_within_minimum_allowed(self):
        """10% discount on Product A: 1,000 -> 900 >= 850 (Allowed)."""
        order = self._create_order([{
            'product': self.prod_a,
            'discount': 10.0,
        }])
        line = order.lines[0]
        final_price = line.price_unit * (1 - line.discount / 100.0)
        self.assertEqual(final_price, 900.0)
        self.assertGreaterEqual(final_price, self.prod_a.minimum_selling_price)

    def test_02_discount_exactly_at_minimum_allowed(self):
        """15% discount on Product A: 1,000 -> 850 == 850 (Allowed)."""
        order = self._create_order([{
            'product': self.prod_a,
            'discount': 15.0,
        }])
        line = order.lines[0]
        final_price = line.price_unit * (1 - line.discount / 100.0)
        self.assertEqual(final_price, 850.0)
        self.assertGreaterEqual(final_price, self.prod_a.minimum_selling_price)

    def test_03_discount_below_minimum_blocked(self):
        """20% discount on Product A: 1,000 -> 800 < 850 (Blocked by backend constraint)."""
        with self.assertRaises(ValidationError):
            self._create_order([{
                'product': self.prod_a,
                'discount': 20.0,
            }])

    def test_04_discount_below_minimum_with_manager_override(self):
        """20% discount on Product A with manager approval: Allowed."""
        order = self._create_order([{
            'product': self.prod_a,
            'discount': 20.0,
            'manager_id': self.manager.id,
            'reason': 'Customer loyalty promo',
        }])
        line = order.lines[0]
        final_price = line.price_unit * (1 - line.discount / 100.0)
        self.assertEqual(final_price, 800.0)
        self.assertEqual(line.pos_retail_line_discount_manager_id.id, self.manager.id)

    def test_05_product_without_minimum_freely_discounted(self):
        """Product C has no minimum price; 50% discount is allowed."""
        order = self._create_order([{
            'product': self.prod_c,
            'discount': 50.0,
        }])
        line = order.lines[0]
        final_price = line.price_unit * (1 - line.discount / 100.0)
        self.assertEqual(final_price, 250.0)

    def test_06_line_discount_audit_log_created(self):
        """Audit log pos.retail.line.discount.log is populated when order is validated."""
        order = self._create_order([
            {
                'product': self.prod_a,
                'discount': 10.0,
                'input_type': 'percent',
                'reason': 'Special customer',
            },
            {
                'product': self.prod_c,
                'discount': 20.0,
                'input_type': 'fixed',
            },
        ])
        # Trigger line discount log creation
        self.env['pos.retail.line.discount.log'].sudo()._create_from_order(order)

        logs = self.env['pos.retail.line.discount.log'].search([('order_id', '=', order.id)])
        self.assertEqual(len(logs), 2)

        log_a = logs.filtered(lambda l: l.product_id.id == self.prod_a.id)
        self.assertTrue(log_a)
        self.assertEqual(log_a.original_price, 1000.0)
        self.assertEqual(log_a.discount_percentage, 10.0)
        self.assertEqual(log_a.discount_amount, 100.0)
        self.assertEqual(log_a.final_price, 900.0)
        self.assertEqual(log_a.minimum_selling_price, 850.0)
        self.assertFalse(log_a.below_minimum)
        self.assertEqual(log_a.reason, 'Special customer')
        self.assertEqual(log_a.cashier_id.id, self.cashier.id)
