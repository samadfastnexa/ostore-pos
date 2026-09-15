# -*- coding: utf-8 -*-

import html
import math

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .thermal_barcode_generator import generate_barcode_svg


class PosRetailThermalLabelWizard(models.TransientModel):
    _name = 'pos.retail.thermal.label.wizard'
    _description = "POS Retail Thermal Label Printing Wizard"

    preset_id = fields.Many2one(
        'pos.retail.thermal.label.preset',
        string="Label Format / Preset",
        required=True,
        default=lambda self: self._default_preset_id(),
        help="Select standard thermal roll size or custom format.",
    )
    line_ids = fields.One2many(
        'pos.retail.thermal.label.wizard.line',
        'wizard_id',
        string="Product Label Lines",
    )

    roll_width = fields.Float(related='preset_id.roll_width', readonly=True)
    label_width = fields.Float(related='preset_id.label_width', readonly=True)
    label_height = fields.Float(related='preset_id.label_height', readonly=True)
    columns = fields.Integer(related='preset_id.columns', readonly=True)

    total_labels = fields.Integer(string="Total Labels", compute='_compute_totals')
    total_rows = fields.Integer(string="Roll Rows", compute='_compute_totals')
    preview_html = fields.Html(string="Label Preview", compute='_compute_preview_html', sanitize=False)

    @api.model
    def _default_preset_id(self):
        # 1. Check current POS config preference
        pos_session = self.env['pos.session'].search([('state', '=', 'opened'), ('user_id', '=', self.env.uid)], limit=1)
        if pos_session and pos_session.config_id.thermal_label_preset_id:
            return pos_session.config_id.thermal_label_preset_id.id
        # 2. Company default preset
        preset = self.env['pos.retail.thermal.label.preset'].search([
            ('is_default', '=', True),
            ('active', '=', True),
            '|', ('company_id', '=', False), ('company_id', 'in', self.env.companies.ids),
        ], limit=1)
        if preset:
            return preset.id
        # 3. Any active preset
        fallback = self.env['pos.retail.thermal.label.preset'].search([('active', '=', True)], limit=1)
        return fallback.id if fallback else False

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids') or []

        products = self.env['product.product']
        if active_model == 'product.template':
            products = self.env['product.product'].search([('product_tmpl_id', 'in', active_ids)])
        elif active_model == 'product.product':
            products = self.env['product.product'].browse(active_ids)

        lines = []
        for p in products:
            lines.append((0, 0, {
                'product_id': p.id,
                'barcode': p.barcode or '',
                'default_code': p.default_code or '',
                'price': p.lst_price,
                'quantity': 1,
            }))

        if lines:
            res['line_ids'] = lines
        return res

    @api.depends('line_ids.quantity', 'preset_id.columns')
    def _compute_totals(self):
        for rec in self:
            total_qty = sum(max(0, line.quantity) for line in rec.line_ids)
            cols = max(1, rec.columns or 1)
            rec.total_labels = total_qty
            rec.total_rows = math.ceil(total_qty / cols) if total_qty > 0 else 0

    @api.depends('preset_id', 'line_ids', 'line_ids.quantity', 'line_ids.barcode', 'line_ids.price')
    def _compute_preview_html(self):
        """Build interactive HTML preview demonstrating exact physical proportion."""
        for rec in self:
            if not rec.preset_id or not rec.line_ids:
                rec.preview_html = "<div class='text-muted p-3'>Select products and a preset to view preview.</div>"
                continue

            preset = rec.preset_id
            currency_symbol = self.env.company.currency_id.symbol or "Rs."

            # Collect expanded sequence of labels (up to first 6 labels for clean preview)
            label_items = []
            for line in rec.line_ids:
                qty = max(0, line.quantity)
                for _ in range(qty):
                    label_items.append({
                        'product_name': line.product_id.display_name,
                        'brand': line.product_id.product_tmpl_id.pos_retail_brand_id.name if hasattr(line.product_id.product_tmpl_id, 'pos_retail_brand_id') and line.product_id.product_tmpl_id.pos_retail_brand_id else '',
                        'sku': line.default_code or '',
                        'barcode': line.barcode or '',
                        'price': line.price,
                        'uom': line.product_id.uom_id.name or '',
                    })
                    if len(label_items) >= 6:
                        break
                if len(label_items) >= 6:
                    break

            if not label_items:
                rec.preview_html = "<div class='alert alert-warning'>All quantities are zero. Set quantity &gt; 0 to preview.</div>"
                continue

            cols = max(1, preset.columns)
            html_out = [
                f"<div style='background:#f1f5f9; padding:15px; border-radius:10px; border:1px solid #cbd5e1; overflow-x:auto;'>"
                f"<div style='margin-bottom:10px; font-weight:bold; color:#334155; font-size:0.85rem;'>"
                f"<i class='fa fa-eye text-primary me-1'></i>Physical Roll Preview ({preset.name}) — "
                f"Roll Width: {preset.roll_width:.1f}mm | Label: {preset.label_width:.1f} × {preset.label_height:.1f}mm | Columns: {preset.columns}"
                f"</div>"
                f"<div style='display:flex; flex-direction:column; gap:{preset.gap_vertical}mm; width:fit-content; margin:0 auto; background:#ffffff; padding:8px; border:1px dashed #94a3b8; box-shadow:0 4px 6px -1px rgba(0,0,0,0.1);'>"
            ]

            # Group items by rows
            for r_idx in range(0, len(label_items), cols):
                row_items = label_items[r_idx:r_idx + cols]
                html_out.append(
                    f"<div style='display:flex; flex-direction:row; width:{preset.roll_width}mm; height:{preset.label_height}mm; "
                    f"gap:{preset.gap_horizontal}mm; padding:{preset.margin_top}mm {preset.margin_right}mm {preset.margin_bottom}mm {preset.margin_left}mm; box-sizing:border-box;'>"
                )
                for item in row_items:
                    barcode_val = item['barcode'] or (item['sku'] if preset.barcode_fallback == 'sku' else '')
                    barcode_svg = ""
                    if preset.show_barcode and barcode_val:
                        barcode_svg = generate_barcode_svg(
                            barcode_val,
                            barcode_type=preset.barcode_type,
                            height_mm=preset.barcode_height,
                            show_text=preset.show_barcode_text,
                        )

                    align = preset.text_align or 'center'
                    font_size = "0.75rem" if preset.font_size == 'normal' else ("0.65rem" if preset.font_size == 'small' else "0.85rem")

                    html_out.append(
                        f"<div style='width:{preset.label_width}mm; height:100%; border:1px solid #e2e8f0; border-radius:4px; "
                        f"box-sizing:border-box; padding:2px; display:flex; flex-direction:column; justify-content:space-between; "
                        f"text-align:{align}; font-size:{font_size}; font-family:sans-serif; overflow:hidden; background:#ffffff;'>"
                    )

                    # Top: Company / Brand
                    top_text = []
                    if preset.show_company_name:
                        top_text.append(html.escape(self.env.company.name or ""))
                    if preset.show_brand and item['brand']:
                        top_text.append(html.escape(item['brand']))
                    if top_text:
                        html_out.append(f"<div style='font-size:0.6rem; color:#64748b; font-weight:600; text-transform:uppercase;'>{' • '.join(top_text)}</div>")

                    # Product Name
                    if preset.show_product_name:
                        html_out.append(f"<div style='font-weight:bold; color:#0f172a; line-height:1.1; max-height:2.4em; overflow:hidden;'>{html.escape(item['product_name'])}</div>")

                    # Barcode Vector Image
                    if barcode_svg:
                        html_out.append(f"<div style='display:flex; justify-content:center; margin:1px 0;'>{barcode_svg}</div>")
                    elif preset.show_barcode and not barcode_val:
                        html_out.append(f"<div style='font-size:0.65rem; color:#ef4444; font-style:italic;'>[No Barcode]</div>")

                    # Price & SKU Bottom Row
                    bottom_parts = []
                    if preset.show_sku and item['sku']:
                        bottom_parts.append(f"<span style='font-size:0.65rem; color:#64748b;'>SKU: {html.escape(item['sku'])}</span>")
                    if preset.show_price:
                        bottom_parts.append(f"<strong style='font-size:0.9rem; color:#15803d;'>{currency_symbol} {item['price']:,.2f}</strong>")
                    if preset.show_uom and item['uom']:
                        bottom_parts.append(f"<span style='font-size:0.6rem; color:#64748b;'>/{html.escape(item['uom'])}</span>")

                    if bottom_parts:
                        html_out.append(f"<div style='display:flex; justify-content:space-between; align-items:baseline; margin-top:auto;'>{' '.join(bottom_parts)}</div>")

                    html_out.append("</div>")

                # Handle odd columns on row (empty slot)
                if len(row_items) < cols:
                    for _ in range(cols - len(row_items)):
                        html_out.append(
                            f"<div style='width:{preset.label_width}mm; height:100%; border:1px dashed #cbd5e1; "
                            f"border-radius:4px; box-sizing:border-box; display:flex; align-items:center; justify-content:center; color:#94a3b8; font-size:0.65rem;'>[Empty Slot]</div>"
                        )

                html_out.append("</div>")

            if rec.total_labels > 6:
                html_out.append(f"<div style='text-align:center; font-size:0.75rem; color:#64748b; margin-top:8px;'>... and {rec.total_labels - 6} more label(s) in sequence.</div>")

            html_out.append("</div></div>")
            rec.preview_html = "".join(html_out)

    def action_print(self):
        """Open browser thermal printing URL."""
        self.ensure_one()
        if not self.total_labels:
            raise UserError(_("Please specify a quantity greater than zero for at least one product."))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/pos_retail/print_thermal_labels?wizard_id={self.id}',
            'target': 'new',
        }

    def action_test_print_one(self):
        """Print exactly 1 sample label to verify physical alignment."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/pos_retail/print_thermal_labels?wizard_id={self.id}&single=1',
            'target': 'new',
        }

    def action_set_qty_all(self, qty=1):
        self.ensure_one()
        self.line_ids.write({'quantity': qty})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class PosRetailThermalLabelWizardLine(models.TransientModel):
    _name = 'pos.retail.thermal.label.wizard.line'
    _description = "Thermal Label Wizard Line Item"

    wizard_id = fields.Many2one('pos.retail.thermal.label.wizard', ondelete='cascade', required=True)
    product_id = fields.Many2one('product.product', string="Product", required=True)
    product_tmpl_id = fields.Many2one(related='product_id.product_tmpl_id', readonly=True)
    product_name = fields.Char(related='product_id.display_name', readonly=True)
    barcode = fields.Char(string="Barcode")
    default_code = fields.Char(string="SKU / Ref")
    price = fields.Float(string="Selling Price", digits='Product Price')
    quantity = fields.Integer(string="Print Qty", default=1, required=True)
    on_hand_qty = fields.Float(related='product_id.qty_available', string="On Hand", readonly=True)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.barcode = self.product_id.barcode or ''
            self.default_code = self.product_id.default_code or ''
            self.price = self.product_id.lst_price or 0.0
