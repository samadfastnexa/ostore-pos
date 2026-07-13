from odoo import api, fields, models


class ProductSupplierinfo(models.Model):
    _inherit = 'product.supplierinfo'

    is_preferred = fields.Boolean(
        string="Preferred Vendor",
        help="When set, this vendor is picked first by Odoo's automatic vendor "
             "selection (new PO lines, reordering rules, Replenish) ahead of "
             "price/sequence.",
    )
    last_purchase_price = fields.Monetary(
        string="Last Purchase Price", currency_field='currency_id',
        compute='_compute_last_purchase', store=True, readonly=True, copy=False,
    )
    last_purchase_date = fields.Date(
        string="Last Purchase Date",
        compute='_compute_last_purchase', store=True, readonly=True, copy=False,
    )
    current_stock = fields.Float(
        string="Current Stock", compute='_compute_current_stock',
    )
    total_purchased_qty = fields.Float(
        string="Total Purchased Qty", compute='_compute_total_purchased_qty',
    )
    product_display_name = fields.Char(related='product_tmpl_id.name', string="Product")
    product_image = fields.Image(related='product_tmpl_id.image_128', string="Image")
    product_sku = fields.Char(related='product_tmpl_id.default_code', string="SKU")
    product_barcode = fields.Char(related='product_tmpl_id.barcode', string="Barcode")
    product_active = fields.Boolean(related='product_tmpl_id.active', string="Active")

    @api.depends('product_id.qty_available', 'product_tmpl_id.qty_available')
    def _compute_current_stock(self):
        for rec in self:
            rec.current_stock = (rec.product_id or rec.product_tmpl_id).qty_available

    @api.depends('partner_id', 'product_id', 'product_tmpl_id')
    def _compute_total_purchased_qty(self):
        for rec in self:
            rec.total_purchased_qty = sum(
                rec._matching_purchase_order_lines().mapped('product_qty')
            )

    @api.depends('partner_id', 'product_id', 'product_tmpl_id')
    def _compute_last_purchase(self):
        for rec in self:
            last_line = rec._matching_purchase_order_lines(limit=1)
            rec.last_purchase_price = last_line.price_unit if last_line else 0.0
            rec.last_purchase_date = last_line.order_id.date_order.date() if last_line else False

    def _matching_purchase_order_lines(self, limit=None):
        self.ensure_one()
        if not self.partner_id:
            return self.env['purchase.order.line']
        domain = [
            ('order_id.partner_id', 'child_of', self.partner_id.commercial_partner_id.id),
            ('order_id.state', '=', 'purchase'),
        ]
        if self.product_id:
            domain.append(('product_id', '=', self.product_id.id))
        else:
            domain.append(('product_id.product_tmpl_id', '=', self.product_tmpl_id.id))
        # Sorted in Python (not via search(order=...)): ordering through a
        # related field like `order_id.date_order` isn't valid SQL-order syntax
        # in this ORM (that dotted syntax is reserved for Properties fields).
        lines = self.env['purchase.order.line'].search(domain)
        lines = lines.sorted(key=lambda l: (l.order_id.date_order, l.id), reverse=True)
        return lines[:limit] if limit else lines

    def action_open_product(self):
        self.ensure_one()
        product = self.product_id or self.product_tmpl_id
        return {
            'type': 'ir.actions.act_window',
            'res_model': product._name,
            'res_id': product.id,
            'view_mode': 'form',
            'target': 'current',
        }

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered('is_preferred')._enforce_single_preferred()
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get('is_preferred'):
            self.filtered('is_preferred')._enforce_single_preferred()
        return res

    def _enforce_single_preferred(self):
        for rec in self:
            self.search([
                ('product_tmpl_id', '=', rec.product_tmpl_id.id),
                ('is_preferred', '=', True),
                ('id', '!=', rec.id),
            ]).write({'is_preferred': False})
