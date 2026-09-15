# -*- coding: utf-8 -*-
"""
Automated Test Suite for Thermal Barcode Label Printing
Covers:
- Vector SVG barcode generator (Code 128, EAN-13, EAN-8, UPC-A, Code 39)
- Physical roll & label geometry validation and constraints
- Default preset toggling & duplication
- Multi-column row pagination & odd slot handling
- Wizard line expansion & interactive preview computation
"""

from odoo.exceptions import ValidationError, UserError
from odoo.tests import TransactionCase, tagged

from ..models.thermal_barcode_generator import (
    generate_barcode_svg,
    encode_code128,
    encode_ean13,
    encode_ean8,
    encode_upca,
    encode_code39,
)


@tagged('post_install', '-at_install')
class TestThermalLabelPrinting(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # Create test products
        cls.prod_single = cls.env['product.product'].create({
            'name': 'Thermal Single Product',
            'default_code': 'TH-SINGLE-01',
            'barcode': '1234567890128',
            'lst_price': 150.0,
            'available_in_pos': True,
        })

        cls.prod_bulk = cls.env['product.product'].create({
            'name': 'Thermal Bulk Product',
            'default_code': 'TH-BULK-02',
            'barcode': '987654321098',
            'lst_price': 45.0,
            'available_in_pos': True,
        })

        # Create test presets
        cls.preset_50x30 = cls.env['pos.retail.thermal.label.preset'].create({
            'name': 'Test 50x30 1-Col',
            'preset_code': '50x30_1col',
            'roll_width': 54.0,
            'label_width': 50.0,
            'label_height': 30.0,
            'columns': 1,
            'gap_horizontal': 0.0,
            'gap_vertical': 3.0,
            'margin_left': 2.0,
            'margin_right': 2.0,
            'margin_top': 1.0,
            'margin_bottom': 1.0,
            'barcode_type': 'code128',
            'is_default': True,
        })

        cls.preset_100x30_2col = cls.env['pos.retail.thermal.label.preset'].create({
            'name': 'Test 100x30 2-Col',
            'preset_code': '100x30_2col',
            'roll_width': 104.0,
            'label_width': 48.0,
            'label_height': 30.0,
            'columns': 2,
            'gap_horizontal': 4.0,
            'gap_vertical': 3.0,
            'margin_left': 2.0,
            'margin_right': 2.0,
            'barcode_type': 'code128',
            'is_default': False,
        })

    def test_01_svg_barcode_generation(self):
        """Test pure vector SVG barcode engine for all supported formats without Cairo/renderPM."""
        # Code 128
        svg_c128 = generate_barcode_svg('ABC-12345', barcode_type='code128', height_mm=12)
        self.assertIn('<svg', svg_c128)
        self.assertIn('viewBox=', svg_c128)
        self.assertIn('<rect', svg_c128)
        self.assertIn('ABC-12345', svg_c128)

        # EAN-13 with 12 or 13 digits
        svg_ean13 = generate_barcode_svg('1234567890128', barcode_type='ean13', height_mm=10)
        self.assertIn('<svg', svg_ean13)
        self.assertIn('<rect', svg_ean13)

        # EAN-8
        svg_ean8 = generate_barcode_svg('12345670', barcode_type='ean8', height_mm=10)
        self.assertIn('<svg', svg_ean8)

        # UPC-A
        svg_upca = generate_barcode_svg('012345678905', barcode_type='upca', height_mm=10)
        self.assertIn('<svg', svg_upca)

        # Code 39
        svg_c39 = generate_barcode_svg('CODE39TEST', barcode_type='code39', height_mm=10)
        self.assertIn('<svg', svg_c39)

    def test_02_dimension_validation_exceeds_roll_width(self):
        """Validation error must be raised when label width + margins exceed physical roll width."""
        with self.assertRaises(ValidationError):
            self.env['pos.retail.thermal.label.preset'].create({
                'name': 'Impossible Fit',
                'preset_code': 'custom',
                'roll_width': 50.0,
                'label_width': 48.0,
                'label_height': 30.0,
                'columns': 1,
                'margin_left': 2.0,
                'margin_right': 2.0,  # 48 + 2 + 2 = 52mm > 50mm
            })

    def test_03_dimension_validation_multi_column_exceeds(self):
        """Multi-column layout must fit inside roll width including horizontal gap."""
        with self.assertRaises(ValidationError):
            self.env['pos.retail.thermal.label.preset'].create({
                'name': 'Impossible 2-Col Fit',
                'preset_code': 'custom',
                'roll_width': 100.0,
                'label_width': 50.0,
                'label_height': 30.0,
                'columns': 2,
                'gap_horizontal': 3.0,  # (50 * 2) + 3 = 103mm > 100mm
                'margin_left': 1.0,
                'margin_right': 1.0,
            })

    def test_04_dimension_validation_negative_or_zero(self):
        """Zero or negative roll/label dimensions must be blocked."""
        with self.assertRaises(ValidationError):
            self.env['pos.retail.thermal.label.preset'].create({
                'name': 'Zero Width',
                'preset_code': 'custom',
                'roll_width': 0.0,
                'label_width': 50.0,
                'label_height': 30.0,
            })

        with self.assertRaises(ValidationError):
            self.env['pos.retail.thermal.label.preset'].create({
                'name': 'Zero Columns',
                'preset_code': 'custom',
                'roll_width': 50.0,
                'label_width': 40.0,
                'label_height': 30.0,
                'columns': 0,
            })

    def test_05_default_preset_toggle(self):
        """Action set default must unset previous default and activate the selected one."""
        self.assertTrue(self.preset_50x30.is_default)
        self.assertFalse(self.preset_100x30_2col.is_default)

        # Set 100x30 as default
        self.preset_100x30_2col.action_set_default()
        self.preset_50x30.invalidate_recordset(['is_default'])
        self.preset_100x30_2col.invalidate_recordset(['is_default'])

        self.assertTrue(self.preset_100x30_2col.is_default)
        self.assertFalse(self.preset_50x30.is_default)

    def test_06_duplicate_preset(self):
        """Duplicating preset creates a custom format preset."""
        action = self.preset_50x30.action_duplicate_preset()
        new_preset = self.env['pos.retail.thermal.label.preset'].browse(action['res_id'])
        self.assertEqual(new_preset.preset_code, 'custom')
        self.assertIn("Custom Copy", new_preset.name)
        self.assertFalse(new_preset.is_default)
        self.assertEqual(new_preset.label_width, self.preset_50x30.label_width)

    def test_07_wizard_default_get_from_products(self):
        """Wizard loaded from active product IDs must populate wizard lines."""
        context = {
            'active_model': 'product.product',
            'active_ids': [self.prod_single.id, self.prod_bulk.id],
        }
        wizard_vals = self.env['pos.retail.thermal.label.wizard'].with_context(context).default_get(['preset_id', 'line_ids'])
        self.assertEqual(len(wizard_vals.get('line_ids', [])), 2)

    def test_08_wizard_pagination_and_preview_single_column(self):
        """Verify row calculation and preview generation for 1-column roll."""
        wizard = self.env['pos.retail.thermal.label.wizard'].create({
            'preset_id': self.preset_50x30.id,
            'line_ids': [
                (0, 0, {'product_id': self.prod_single.id, 'quantity': 3, 'price': 150.0, 'barcode': '123456'}),
            ],
        })
        wizard._compute_totals()
        self.assertEqual(wizard.total_labels, 3)
        self.assertEqual(wizard.total_rows, 3)

        wizard._compute_preview_html()
        self.assertIn('Physical Roll Preview', wizard.preview_html)
        self.assertIn('width:54.0mm', wizard.preview_html)
        self.assertIn('height:30.0mm', wizard.preview_html)

    def test_09_wizard_pagination_and_odd_quantity_multi_column(self):
        """Verify 2-column roll handles odd total quantities with empty slot on the final row."""
        wizard = self.env['pos.retail.thermal.label.wizard'].create({
            'preset_id': self.preset_100x30_2col.id,
            'line_ids': [
                (0, 0, {'product_id': self.prod_single.id, 'quantity': 5, 'price': 150.0, 'barcode': '123456'}),
            ],
        })
        wizard._compute_totals()
        self.assertEqual(wizard.total_labels, 5)
        # 5 labels on 2 columns = 3 physical rows
        self.assertEqual(wizard.total_rows, 3)

        wizard._compute_preview_html()
        # Preview must render an empty slot placeholder for the 6th position
        self.assertIn('[Empty Slot]', wizard.preview_html)

    def test_10_wizard_action_print_validation(self):
        """Printing with zero total quantity must raise UserError."""
        wizard = self.env['pos.retail.thermal.label.wizard'].create({
            'preset_id': self.preset_50x30.id,
            'line_ids': [
                (0, 0, {'product_id': self.prod_single.id, 'quantity': 0}),
            ],
        })
        with self.assertRaises(UserError):
            wizard.action_print()

    def test_11_wizard_action_set_qty_all(self):
        """Quick quantity helper should update all line items."""
        wizard = self.env['pos.retail.thermal.label.wizard'].create({
            'preset_id': self.preset_50x30.id,
            'line_ids': [
                (0, 0, {'product_id': self.prod_single.id, 'quantity': 1}),
                (0, 0, {'product_id': self.prod_bulk.id, 'quantity': 1}),
            ],
        })
        wizard.action_set_qty_all(qty=10)
        self.assertEqual(wizard.line_ids[0].quantity, 10)
        self.assertEqual(wizard.line_ids[1].quantity, 10)
        wizard._compute_totals()
        self.assertEqual(wizard.total_labels, 20)
