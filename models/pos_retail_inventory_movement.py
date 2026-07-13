from odoo import fields, models


class PosRetailInventoryMovement(models.Model):
    _name = 'pos.retail.inventory.movement'
    _description = "POS Inventory Movement (audit trail per completed sale)"
    _order = 'date desc, id desc'
    _rec_name = 'product_id'

    order_id = fields.Many2one('pos.order', required=True, ondelete='cascade', index=True)
    order_line_id = fields.Many2one('pos.order.line', ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True, index=True)

    sku = fields.Char(string="SKU")
    barcode = fields.Char(string="Barcode")
    qty_sold = fields.Float(string="Quantity Sold", digits='Product Unit')
    previous_stock = fields.Float(string="Previous Stock")
    current_stock = fields.Float(string="Current Stock")

    currency_id = fields.Many2one('res.currency', related='order_id.currency_id', store=True)
    company_id = fields.Many2one('res.company', related='order_id.company_id', store=True)

    cost_price = fields.Monetary(string="Cost Price", currency_field='currency_id')
    selling_price = fields.Monetary(string="Selling Price", currency_field='currency_id')
    discount_applied = fields.Float(string="Discount Applied (%)")
    final_selling_price = fields.Monetary(string="Final Selling Price", currency_field='currency_id')
    total_cost = fields.Monetary(string="Total Cost", currency_field='currency_id')
    total_revenue = fields.Monetary(string="Total Revenue", currency_field='currency_id')
    profit = fields.Monetary(string="Profit", currency_field='currency_id')

    cashier_id = fields.Many2one('hr.employee', string="Cashier")
    cashier_name = fields.Char(string="Cashier Name")
    partner_id = fields.Many2one('res.partner', string="Customer")
    config_id = fields.Many2one('pos.config', string="Branch", required=True, index=True)
    pos_order_ref = fields.Char(string="Order Reference")
    invoice_number = fields.Char(
        string="Invoice Number",
        help="Only populated when the order was actually invoiced. Most POS "
             "sales are not — use Order Reference as the universal receipt id.",
    )
    date = fields.Datetime(string="Date & Time", index=True)
    has_negative_stock_warning = fields.Boolean(string="Negative Stock", index=True)

    def _create_from_order_lines(self, lines, stock_before):
        """Create one movement row per order line. `stock_before` maps
        product_id -> qty_available snapshotted just before the stock move
        was validated. Tracked as a running value across lines so multiple
        lines for the same product within one order (e.g. different
        discounts) each see the correct "current stock" left after the
        earlier line(s), not a stale static snapshot."""
        running_stock = dict(stock_before)
        vals_list = []
        for line in lines:
            order = line.order_id
            product = line.product_id
            previous = running_stock.get(product.id, product.qty_available)
            qty = line.qty
            current = previous - qty
            running_stock[product.id] = current

            vals_list.append({
                'order_id': order.id,
                'order_line_id': line.id,
                'product_id': product.id,
                'sku': product.default_code,
                'barcode': product.barcode,
                'qty_sold': qty,
                'previous_stock': previous,
                'current_stock': current,
                'cost_price': (line.total_cost / qty) if qty else 0.0,
                'selling_price': line.price_unit,
                'discount_applied': line.discount,
                'final_selling_price': line.price_unit * (1 - line.discount / 100.0),
                'total_cost': line.total_cost,
                'total_revenue': line.price_subtotal,
                'profit': line.margin,
                'cashier_id': order.employee_id.id,
                'cashier_name': order.cashier,
                'partner_id': order.partner_id.id,
                'config_id': order.config_id.id,
                'pos_order_ref': order.pos_reference or order.name,
                'invoice_number': order.account_move.name if order.account_move else False,
                'date': order.date_order,
                'has_negative_stock_warning': current < 0,
            })
        return self.create(vals_list)
