# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

PRESET_DEFAULTS = {
    '40x20_1col': {
        'name': 'Small — 40 × 20 mm',
        'roll_width': 44.0,
        'label_width': 40.0,
        'label_height': 20.0,
        'columns': 1,
        'gap_horizontal': 0.0,
        'gap_vertical': 2.0,
        'margin_left': 2.0,
        'margin_right': 2.0,
        'margin_top': 1.0,
        'margin_bottom': 1.0,
        'barcode_height': 7.0,
        'font_size': 'small',
    },
    '50x25_1col': {
        'name': 'Small — 50 × 25 mm',
        'roll_width': 54.0,
        'label_width': 50.0,
        'label_height': 25.0,
        'columns': 1,
        'gap_horizontal': 0.0,
        'gap_vertical': 2.0,
        'margin_left': 2.0,
        'margin_right': 2.0,
        'margin_top': 1.5,
        'margin_bottom': 1.5,
        'barcode_height': 9.0,
        'font_size': 'small',
    },
    '50x30_1col': {
        'name': 'Standard — 50 × 30 mm',
        'roll_width': 54.0,
        'label_width': 50.0,
        'label_height': 30.0,
        'columns': 1,
        'gap_horizontal': 0.0,
        'gap_vertical': 2.0,
        'margin_left': 2.0,
        'margin_right': 2.0,
        'margin_top': 1.5,
        'margin_bottom': 1.5,
        'barcode_height': 11.0,
        'font_size': 'normal',
    },
    '50x40_1col': {
        'name': 'Standard — 50 × 40 mm',
        'roll_width': 54.0,
        'label_width': 50.0,
        'label_height': 40.0,
        'columns': 1,
        'gap_horizontal': 0.0,
        'gap_vertical': 2.0,
        'margin_left': 2.0,
        'margin_right': 2.0,
        'margin_top': 2.0,
        'margin_bottom': 2.0,
        'barcode_height': 14.0,
        'font_size': 'normal',
    },
    '60x30_1col': {
        'name': 'Medium — 60 × 30 mm',
        'roll_width': 64.0,
        'label_width': 60.0,
        'label_height': 30.0,
        'columns': 1,
        'gap_horizontal': 0.0,
        'gap_vertical': 2.0,
        'margin_left': 2.0,
        'margin_right': 2.0,
        'margin_top': 1.5,
        'margin_bottom': 1.5,
        'barcode_height': 11.0,
        'font_size': 'normal',
    },
    '60x40_1col': {
        'name': 'Medium — 60 × 40 mm',
        'roll_width': 64.0,
        'label_width': 60.0,
        'label_height': 40.0,
        'columns': 1,
        'gap_horizontal': 0.0,
        'gap_vertical': 2.0,
        'margin_left': 2.0,
        'margin_right': 2.0,
        'margin_top': 2.0,
        'margin_bottom': 2.0,
        'barcode_height': 14.0,
        'font_size': 'normal',
    },
    '70x40_1col': {
        'name': 'Large — 70 × 40 mm',
        'roll_width': 74.0,
        'label_width': 70.0,
        'label_height': 40.0,
        'columns': 1,
        'gap_horizontal': 0.0,
        'gap_vertical': 3.0,
        'margin_left': 2.0,
        'margin_right': 2.0,
        'margin_top': 2.0,
        'margin_bottom': 2.0,
        'barcode_height': 14.0,
        'font_size': 'large',
    },
    '80x50_1col': {
        'name': 'Large — 80 × 50 mm',
        'roll_width': 84.0,
        'label_width': 80.0,
        'label_height': 50.0,
        'columns': 1,
        'gap_horizontal': 0.0,
        'gap_vertical': 3.0,
        'margin_left': 2.0,
        'margin_right': 2.0,
        'margin_top': 2.5,
        'margin_bottom': 2.5,
        'barcode_height': 18.0,
        'font_size': 'large',
    },
    '100x30_2col': {
        'name': 'Dual — 100 × 30 mm (2 Col)',
        'roll_width': 100.0,
        'label_width': 48.0,
        'label_height': 30.0,
        'columns': 2,
        'gap_horizontal': 2.0,
        'gap_vertical': 2.0,
        'margin_left': 1.0,
        'margin_right': 1.0,
        'margin_top': 1.5,
        'margin_bottom': 1.5,
        'barcode_height': 11.0,
        'font_size': 'normal',
    },
    '100x40_2col': {
        'name': 'Dual — 100 × 40 mm (2 Col)',
        'roll_width': 100.0,
        'label_width': 48.0,
        'label_height': 40.0,
        'columns': 2,
        'gap_horizontal': 2.0,
        'gap_vertical': 2.0,
        'margin_left': 1.0,
        'margin_right': 1.0,
        'margin_top': 2.0,
        'margin_bottom': 2.0,
        'barcode_height': 14.0,
        'font_size': 'normal',
    },
}


class PosRetailThermalLabelPreset(models.Model):
    _name = 'pos.retail.thermal.label.preset'
    _inherit = ['pos.load.mixin']
    _description = "POS Retail Thermal Label Preset & Format"
    _order = 'is_default desc, sequence, id'

    name = fields.Char(
        string="Preset Name",
        required=True,
        help="Display name for this label format, e.g. 'Standard — 50 × 30 mm'.",
    )
    preset_code = fields.Selection([
        ('40x20_1col', "Small — 40 × 20 mm"),
        ('50x25_1col', "Small — 50 × 25 mm"),
        ('50x30_1col', "Standard — 50 × 30 mm"),
        ('50x40_1col', "Standard — 50 × 40 mm"),
        ('60x30_1col', "Medium — 60 × 30 mm"),
        ('60x40_1col', "Medium — 60 × 40 mm"),
        ('70x40_1col', "Large — 70 × 40 mm"),
        ('80x50_1col', "Large — 80 × 50 mm"),
        ('100x30_2col', "Dual Standard — 100 × 30 mm (2 Col)"),
        ('100x40_2col', "Dual Medium — 100 × 40 mm (2 Col)"),
        ('custom', "Custom Dimensions"),
    ], string="Label Format Preset", default='50x30_1col', required=True)

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(
        string="Default Preset",
        default=False,
        help="Use this label format as the default across product screens and POS.",
    )
    company_id = fields.Many2one(
        'res.company',
        string="Branch / Company",
        help="Leave blank to make this preset available across all branches, or select a specific branch.",
    )

    # Physical Dimensions (all in millimeters)
    roll_width = fields.Float(
        string="Roll Width (mm)",
        required=True,
        default=54.0,
        help="Total physical width of the backing paper / label roll in mm.",
    )
    label_width = fields.Float(
        string="Label Width (mm)",
        required=True,
        default=50.0,
        help="Width of a single printable label in mm.",
    )
    label_height = fields.Float(
        string="Label Height (mm)",
        required=True,
        default=30.0,
        help="Height of a single printable label in mm.",
    )
    columns = fields.Integer(
        string="Labels Per Row (Columns)",
        required=True,
        default=1,
        help="1 for standard single rolls; 2 or 3 for multi-column rolls.",
    )
    gap_horizontal = fields.Float(
        string="Horizontal Gap (mm)",
        default=0.0,
        help="Gap between columns on multi-label rolls in mm.",
    )
    gap_vertical = fields.Float(
        string="Vertical Gap (mm)",
        default=2.0,
        help="Gap between successive label rows in mm.",
    )
    margin_left = fields.Float(string="Left Margin (mm)", default=2.0)
    margin_right = fields.Float(string="Right Margin (mm)", default=2.0)
    margin_top = fields.Float(string="Top Margin (mm)", default=1.5)
    margin_bottom = fields.Float(string="Bottom Margin (mm)", default=1.5)

    total_row_width = fields.Float(
        string="Total Required Width (mm)",
        compute='_compute_total_row_width',
        help="Calculated total width: (Label Width × Columns) + Gaps + Margins.",
    )

    # Barcode Configuration
    barcode_type = fields.Selection([
        ('code128', "Code 128 (Recommended — Alphanumeric)"),
        ('ean13', "EAN-13 (Standard Retail 13 Digits)"),
        ('ean8', "EAN-8 (Compact Retail 8 Digits)"),
        ('upca', "UPC-A (Standard Retail 12 Digits)"),
        ('code39', "Code 39 (Alphanumeric)"),
    ], string="Barcode Type", default='code128', required=True)
    barcode_height = fields.Float(
        string="Barcode Height (mm)",
        default=11.0,
        help="Height of the printed barcode in mm.",
    )
    barcode_fallback = fields.Selection([
        ('none', "Do Not Print Barcode"),
        ('sku', "Use Internal Code / SKU"),
        ('auto', "Generate Barcode Automatically"),
    ], string="Missing Barcode Action", default='sku', required=True,
       help="What to do if a product has no barcode defined.")

    # Product Content Display Toggles
    show_company_name = fields.Boolean(string="Store / Company Name", default=True)
    show_brand = fields.Boolean(string="Brand", default=False)
    show_product_name = fields.Boolean(string="Product Name", default=True)
    show_product_variant = fields.Boolean(string="Product Variant Attributes", default=True)
    show_sku = fields.Boolean(string="SKU / Internal Reference", default=True)
    show_barcode = fields.Boolean(string="Barcode Image", default=True)
    show_barcode_text = fields.Boolean(string="Barcode Text Number", default=True)
    show_price = fields.Boolean(string="Selling Price", default=True)
    show_uom = fields.Boolean(string="Unit of Measure (UoM)", default=True)
    show_product_code = fields.Boolean(string="Product Code", default=False)
    show_lot_number = fields.Boolean(string="Batch / Lot Number", default=False)

    # Text & Typography Formatting
    font_size = fields.Selection([
        ('small', "Compact / Small"),
        ('normal', "Standard / Medium"),
        ('large', "Prominent / Large"),
    ], string="Font Size", default='normal', required=True)
    text_align = fields.Selection([
        ('left', "Left"),
        ('center', "Center"),
        ('right', "Right"),
    ], string="Text Alignment", default='center', required=True)

    @api.depends('label_width', 'columns', 'gap_horizontal', 'margin_left', 'margin_right')
    def _compute_total_row_width(self):
        for rec in self:
            cols = max(1, rec.columns)
            h_gaps = rec.gap_horizontal * (cols - 1)
            rec.total_row_width = (rec.label_width * cols) + h_gaps + rec.margin_left + rec.margin_right

    @api.constrains('roll_width', 'label_width', 'columns', 'gap_horizontal', 'margin_left', 'margin_right', 'label_height')
    def _check_label_fit(self):
        """Strict validation: ensure configured label geometry physically fits the roll."""
        for rec in self:
            if rec.columns < 1:
                raise ValidationError(_("Number of labels per row (columns) must be at least 1."))
            if rec.label_width <= 0 or rec.label_height <= 0:
                raise ValidationError(_("Label width and height must be strictly positive."))
            if rec.roll_width <= 0:
                raise ValidationError(_("Roll width must be strictly positive."))

            total_width = (rec.label_width * rec.columns) + (rec.gap_horizontal * (rec.columns - 1)) + rec.margin_left + rec.margin_right
            if round(total_width, 2) > round(rec.roll_width, 2):
                raise ValidationError(_(
                    "These labels do not fit within the selected roll width.\n\n"
                    "• Configured Roll Width: %.2f mm\n"
                    "• Total Required Width: %.2f mm\n"
                    "  [ (%.2f mm width × %d cols) + %.2f mm gap + %.2f mm margins ]\n\n"
                    "Please reduce label width, margins, or column count so it fits the physical roll."
                ) % (
                    rec.roll_width,
                    total_width,
                    rec.label_width,
                    rec.columns,
                    rec.gap_horizontal * (rec.columns - 1),
                    rec.margin_left + rec.margin_right,
                ))

    @api.onchange('preset_code')
    def _onchange_preset_code(self):
        """Preload standard dimensions when preset is changed."""
        if self.preset_code and self.preset_code in PRESET_DEFAULTS:
            vals = PRESET_DEFAULTS[self.preset_code]
            self.update({
                'name': vals['name'],
                'roll_width': vals['roll_width'],
                'label_width': vals['label_width'],
                'label_height': vals['label_height'],
                'columns': vals['columns'],
                'gap_horizontal': vals['gap_horizontal'],
                'gap_vertical': vals['gap_vertical'],
                'margin_left': vals['margin_left'],
                'margin_right': vals['margin_right'],
                'margin_top': vals['margin_top'],
                'margin_bottom': vals['margin_bottom'],
                'barcode_height': vals['barcode_height'],
                'font_size': vals['font_size'],
            })

    def action_set_default(self):
        """Set as default preset for this company."""
        self.ensure_one()
        domain = []
        if self.company_id:
            domain = [('company_id', '=', self.company_id.id)]
        self.search(domain).write({'is_default': False})
        self.write({'is_default': True})
        return True

    def action_duplicate_preset(self):
        """Quick duplicate to customize a preset without modifying the standard preset."""
        self.ensure_one()
        copy_vals = {
            'name': f"{self.name} (Custom Copy)",
            'preset_code': 'custom',
            'is_default': False,
        }
        new_rec = self.copy(copy_vals)
        return {
            'name': _("Custom Thermal Label Preset"),
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': new_rec.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_print_test_label(self):
        """Open test print for calibration of gap and alignment."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/pos_retail/print_thermal_labels?preset_id={self.id}&test=1',
            'target': 'new',
        }

    @api.model
    def _load_pos_data_domain(self, data):
        return [('active', '=', True)]

    @api.model
    def _load_pos_data_fields(self, config):
        return ['id', 'name', 'preset_code', 'roll_width', 'label_width', 'label_height', 'columns', 'is_default']
