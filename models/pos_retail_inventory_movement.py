from odoo import fields, models


class PosRetailInventoryMovement(models.Model):
    _name = 'pos.retail.inventory.movement'
    _description = "POS Inventory Movement (audit trail per completed sale)"
    _order = 'date desc, id desc'
    _rec_name = 'product_id'

    order_id = fields.Many2one(
        'pos.order',
        required=True,
        ondelete='cascade',
        index=True,
        help="The completed sale that moved this item off your shelves. If the "
             "sale is ever deleted, this audit row goes with it.",
    )
    order_line_id = fields.Many2one(
        'pos.order.line',
        ondelete='cascade',
        help="The exact receipt line this row was taken from. It matters when the "
             "same item appears twice on one receipt, for example at two "
             "different discounts.",
    )
    product_id = fields.Many2one(
        'product.product',
        required=True,
        index=True,
        help="The item that was sold on this receipt line.",
    )

    sku = fields.Char(
        string="Product Code (SKU)",
        help="The product's internal reference as it stood on the day of the "
             "sale. Kept as plain text, so renaming or recoding the product "
             "later does not rewrite this old record.",
    )
    barcode = fields.Char(
        string="Barcode",
        help="The barcode the product carried when it was sold. Stored as plain "
             "text so the history stays accurate even if the barcode is changed "
             "afterwards.",
    )
    qty_sold = fields.Float(
        string="Quantity Sold",
        digits='Product Unit',
        help="How many units of this item left stock on this receipt line.",
    )
    previous_stock = fields.Float(
        string="Previous Stock",
        help="Stock on hand for this item immediately before this sale was rung "
             "up; captured at the moment of sale and never recalculated later.",
    )
    current_stock = fields.Float(
        string="Current Stock",
        help="Stock left for this item straight after this sale was deducted. It "
             "is a snapshot of that moment, so it will not match today's stock "
             "once further sales or deliveries happen.",
    )

    currency_id = fields.Many2one(
        'res.currency',
        related='order_id.currency_id',
        store=True,
        help="The currency the sale was taken in. All money figures on this row "
             "are recorded in it, so old records keep reading in the currency "
             "the customer actually paid.",
    )
    company_id = fields.Many2one(
        'res.company',
        related='order_id.company_id',
        store=True,
        help="The company that made the sale. It follows the receipt, so figures "
             "stay separated if you trade under more than one company.",
    )

    cost_price = fields.Monetary(
        string="Cost Price",
        currency_field='currency_id',
        help="What one unit cost you, taken from the product's cost on the day of "
             "the sale. This is the figure the profit below is worked out from.",
    )
    selling_price = fields.Monetary(
        string="Selling Price",
        currency_field='currency_id',
        help="The normal shelf price of one unit, before any discount was taken "
             "off on this sale.",
    )
    discount_applied = fields.Float(
        string="Discount Applied (%)",
        help="How much was knocked off this line, as a percentage of the shelf "
             "price. Zero means the item went out at full price.",
    )
    final_selling_price = fields.Monetary(
        string="Final Selling Price",
        currency_field='currency_id',
        help="What one unit actually sold for once the discount was applied; the "
             "price the customer really paid per unit.",
    )
    total_cost = fields.Monetary(
        string="Total Cost",
        currency_field='currency_id',
        help="What this whole line cost you: the unit cost multiplied by the "
             "quantity sold.",
    )
    total_revenue = fields.Monetary(
        string="Total Revenue",
        currency_field='currency_id',
        help="What the customer paid for this line after discount, before tax.",
    )
    profit = fields.Monetary(
        string="Profit",
        currency_field='currency_id',
        help="Revenue less cost for this line on its own, so what you made on "
             "this item. It takes no account of rent, wages or any discount "
             "given on the order as a whole.",
    )

    cashier_id = fields.Many2one(
        'hr.employee',
        string="Cashier",
        help="The employee signed in at the till when this item was sold.",
    )
    cashier_name = fields.Char(
        string="Cashier Name",
        help="The cashier's name exactly as it was at the time of sale, kept as "
             "text so the record still reads correctly after staff are renamed "
             "or leave.",
    )
    partner_id = fields.Many2one(
        'res.partner',
        string="Customer",
        help="Who bought this; blank means a walk-in sale with no customer "
             "recorded.",
    )
    config_id = fields.Many2one(
        'pos.config',
        string="Branch",
        required=True,
        index=True,
        help="The till or shop that made the sale, so you can compare what moves "
             "where.",
    )
    pos_order_ref = fields.Char(
        string="Order Reference",
        help="The receipt number of the sale. Quote this to find the original "
             "transaction again.",
    )
    invoice_number = fields.Char(
        string="Invoice Number",
        help="Only populated when the order was actually invoiced. Most POS "
             "sales are not — use Order Reference as the universal receipt id.",
    )
    date = fields.Datetime(
        string="Date & Time",
        index=True,
        help="When the sale was completed. Every figure on this row is a snapshot "
             "taken at this moment, not a live value.",
    )
    has_negative_stock_warning = fields.Boolean(
        string="Negative Stock",
        index=True,
        help="Ticked when this sale took the item below zero, meaning you sold "
             "more than the system believed you had. Usually points to a "
             "delivery not booked in or a counting mistake.",
    )

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
