from odoo import _, fields, models


class PosRetailLineDiscountLog(models.Model):
    _name = 'pos.retail.line.discount.log'
    _description = "POS Product-Line Discount Audit Log"
    _order = 'date desc, id desc'
    _rec_name = 'product_id'

    order_id = fields.Many2one(
        'pos.order',
        required=True,
        ondelete='cascade',
        index=True,
        help="The sale this line discount was recorded against.",
    )
    pos_order_ref = fields.Char(
        string="Order Reference",
        help="Receipt number snapshot so the record is readable after the order is removed.",
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='order_id.currency_id',
        store=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='order_id.company_id',
        store=True,
    )
    config_id = fields.Many2one(
        'pos.config',
        string="Branch / Register",
        required=True,
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string="Customer",
        help="Blank for walk-in sales.",
    )
    product_id = fields.Many2one(
        'product.product',
        string="Product",
        index=True,
        ondelete='set null',
    )
    product_name = fields.Char(
        string="Product Name",
        help="Name snapshot so the record survives product renames.",
    )
    cashier_id = fields.Many2one(
        'hr.employee',
        string="Cashier",
    )
    cashier_name = fields.Char(
        string="Cashier Name",
        help="Name snapshot.",
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string="Approving Manager",
        help="Set when the final price fell below the minimum selling price and "
             "a manager authenticated via PIN.",
    )
    manager_name = fields.Char(
        string="Manager Name",
        help="Name snapshot.",
    )

    # Price figures — all snapshots taken at the moment of sale.
    original_price = fields.Monetary(
        string="Original Unit Price",
        currency_field='currency_id',
        help="The product's price_unit BEFORE the line discount was applied.",
    )
    minimum_selling_price = fields.Monetary(
        string="Minimum Selling Price",
        currency_field='currency_id',
        help="Snapshot of the product's minimum_selling_price at the time of sale.",
    )
    discount_input_type = fields.Selection(
        [('percent', "Percentage"), ('fixed', "Fixed Amount")],
        string="Discount Entry Type",
        help="Whether the cashier entered the discount as a % or a flat amount.",
    )
    discount_percentage = fields.Float(
        string="Discount %",
        digits=(6, 2),
    )
    discount_amount = fields.Monetary(
        string="Discount Amount",
        currency_field='currency_id',
        help="Money taken off this line (positive figure).",
    )
    final_price = fields.Monetary(
        string="Final Unit Price",
        currency_field='currency_id',
        help="price_unit * (1 - discount / 100) — the price actually charged.",
    )
    below_minimum = fields.Boolean(
        string="Below Minimum",
        help="True when the final price was below the configured minimum and a manager override was required.",
    )
    reason = fields.Char(
        string="Reason",
        help="Free-text note the cashier entered to explain the discount.",
    )
    date = fields.Datetime(
        string="Date & Time",
        index=True,
        help="When the order containing this discounted line was validated.",
    )

    def _create_from_order(self, order):
        """Create one log record per discounted line in this order.

        Called from PosOrder._process_saved_order after the base class finishes
        (same pattern as pos.retail.discount.log._create_from_order).

        Only lines with discount > 0 and a positive quantity are logged.
        Refund lines and synthetic discount-product lines are skipped.
        """
        discount_product = order.config_id.discount_product_id
        records = []
        for line in order.lines:
            if not line.discount or line.qty <= 0:
                continue
            if discount_product and line.product_id.id == discount_product.id:
                continue

            original_price = line.price_unit
            discount_pct = line.discount
            discount_amount = original_price * discount_pct / 100.0
            final_price = original_price * (1.0 - discount_pct / 100.0)
            min_price = line.pos_retail_min_price or 0.0

            records.append({
                'order_id': order.id,
                'pos_order_ref': order.pos_reference or order.name,
                'config_id': order.config_id.id,
                'partner_id': order.partner_id.id if order.partner_id else False,
                'product_id': line.product_id.id,
                'product_name': line.product_id.display_name,
                'cashier_id': order.employee_id.id if order.employee_id else False,
                'cashier_name': order.cashier or '',
                'manager_id': line.pos_retail_line_discount_manager_id.id
                              if line.pos_retail_line_discount_manager_id else False,
                'manager_name': line.pos_retail_line_discount_manager_id.name or '',
                'original_price': original_price,
                'minimum_selling_price': min_price,
                'discount_input_type': line.pos_retail_line_discount_input_type or 'percent',
                'discount_percentage': discount_pct,
                'discount_amount': discount_amount,
                'final_price': final_price,
                'below_minimum': bool(
                    min_price and final_price < min_price - 0.001
                ),
                'reason': line.pos_retail_line_discount_reason or '',
                'date': order.date_order,
            })

        if records:
            return self.create(records)
        return self.browse()
