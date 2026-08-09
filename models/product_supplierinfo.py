from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductSupplierinfo(models.Model):
    _inherit = 'product.supplierinfo'

    is_preferred = fields.Boolean(
        string="Preferred Vendor",
        help="When set, this vendor is picked first by Odoo's automatic vendor "
             "selection (new PO lines, reordering rules, Replenish) ahead of "
             "price/sequence.",
    )
    # The vendor's own barcode for this item, which is often NOT the barcode
    # the shop sells under: a wholesaler's carton label differs from the
    # retail EAN on the unit. Kept separate from product_barcode below, which
    # is a related read of our own product's code.
    vendor_barcode = fields.Char(
        string="Vendor Barcode",
        help="Barcode printed on the goods as the vendor ships them, when it "
             "differs from your own.",
    )
    default_order_qty = fields.Float(
        string="Default Order Quantity", digits='Product Unit of Measure',
        help="Quantity to suggest when ordering this item from this vendor. "
             "Must be at least the minimum order quantity.",
    )

    last_purchase_price = fields.Monetary(
        string="Last Purchase Price", currency_field='currency_id',
        compute='_compute_last_purchase', store=True, readonly=True, copy=False,
        help="Unit price you actually paid on the most recent confirmed order "
             "from this vendor for this item. Filled in automatically; zero "
             "means you have never bought it from them.",
    )
    last_purchase_date = fields.Date(
        string="Last Purchase Date",
        compute='_compute_last_purchase', store=True, readonly=True, copy=False,
        help="When that last confirmed order was placed, so you can see how old "
             "the price above is before relying on it.",
    )
    current_stock = fields.Float(
        string="Current Stock", compute='_compute_current_stock',
        help="How much of this item you have on the shelf right now, whoever it "
             "came from. Shown here to help you decide whether to reorder.",
    )
    total_purchased_qty = fields.Float(
        string="Total Purchased Quantity", compute='_compute_total_purchased_qty',
        help="Everything you have ever bought of this item from this vendor on "
             "confirmed orders. A good measure of how much you really rely on "
             "them.",
    )
    product_display_name = fields.Char(related='product_tmpl_id.name', string="Product")
    product_image = fields.Image(related='product_tmpl_id.image_128', string="Image")
    product_sku = fields.Char(related='product_tmpl_id.default_code', string="Product Code (SKU)")
    product_barcode = fields.Char(related='product_tmpl_id.barcode', string="Barcode")
    product_active = fields.Boolean(related='product_tmpl_id.active', string="Active")

    @api.depends('product_id.qty_available', 'product_tmpl_id.qty_available')
    def _compute_current_stock(self):
        for rec in self:
            rec.current_stock = (rec.product_id or rec.product_tmpl_id).qty_available

    @api.depends('partner_id', 'product_id', 'product_tmpl_id')
    def _compute_total_purchased_qty(self):
        for rec in self:
            # product_uom_qty, not product_qty: the latter is in each PO
            # line's OWN unit, so two cartons of twelve and five loose units
            # would add up to seven. product_uom_qty is core's conversion of
            # the same quantity into the product's unit.
            rec.total_purchased_qty = sum(
                rec._matching_purchase_order_lines().mapped('product_uom_qty')
            )

    @api.depends('partner_id', 'product_id', 'product_tmpl_id')
    def _compute_last_purchase(self):
        for rec in self:
            last_line = rec._matching_purchase_order_lines(limit=1)
            rec.last_purchase_price = rec._pos_retail_line_unit_cost(last_line)
            rec.last_purchase_date = last_line.order_id.date_order.date() if last_line else False

    def _pos_retail_line_unit_cost(self, line):
        """What one unit of the PRODUCT really cost on that purchase line.

        A purchase line's price_unit is per the line's own unit of measure and
        in the order's own currency, and it ignores any discount agreed on the
        line. Copying it straight across is how a carton of twelve bought for
        6000 turns into a cost of 6000 per litre, and how a USD price gets
        displayed as rupees. This does the same three conversions core does
        when it writes a cost back (purchase_stock's _get_stock_move_price_unit):
        discount, then unit, then currency.
        """
        self.ensure_one()
        if not line:
            return 0.0
        price = getattr(line, 'price_unit_discounted', line.price_unit)
        product = self.product_id or self.product_tmpl_id
        target_uom = product.uom_id
        if line.product_uom_id and target_uom and line.product_uom_id != target_uom:
            price = line.product_uom_id._compute_price(price, target_uom)
        order_currency = line.order_id.currency_id
        target_currency = self.currency_id or self.env.company.currency_id
        if order_currency and target_currency and order_currency != target_currency:
            price = order_currency._convert(
                price, target_currency,
                self.company_id or self.env.company,
                line.order_id.date_order.date() if line.order_id.date_order else None,
            )
        return price

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

    @api.constrains('default_order_qty', 'min_qty')
    def _check_default_order_qty(self):
        """A default order below the vendor's minimum would be rejected by the
        vendor, so catch it here rather than at the vendor's counter."""
        for rec in self:
            if rec.default_order_qty and rec.min_qty and rec.default_order_qty < rec.min_qty:
                raise ValidationError(_(
                    "Default order quantity (%(default)s) is below %(vendor)s's "
                    "minimum of %(minimum)s for this product.",
                    default=rec.default_order_qty,
                    vendor=rec.partner_id.display_name,
                    minimum=rec.min_qty,
                ))
