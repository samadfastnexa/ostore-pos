from odoo import fields, models


class PosRetailDiscountLog(models.Model):
    _name = 'pos.retail.discount.log'
    _description = "POS Order Discount & Round-Off Audit Log"
    _order = 'date desc, id desc'
    _rec_name = 'order_id'

    order_id = fields.Many2one(
        'pos.order',
        required=True,
        ondelete='cascade',
        index=True,
        help="The sale this discount or rounding was recorded against. If the "
             "sale is ever deleted, this audit row goes with it.",
    )
    pos_order_ref = fields.Char(
        string="Order Reference",
        help="The receipt number of the sale. Quote this to find the original "
             "transaction again.",
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

    partner_id = fields.Many2one(
        'res.partner',
        string="Customer",
        help="Who received the discount; blank means a walk-in sale with no "
             "customer recorded.",
    )
    cashier_id = fields.Many2one(
        'hr.employee',
        string="Cashier",
        help="The employee signed in at the till when the discount was given.",
    )
    cashier_name = fields.Char(
        string="Cashier Name",
        help="The cashier's name exactly as it was at the time of sale, kept as "
             "text so the record still reads correctly after staff are renamed "
             "or leave.",
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string="Approving Manager",
        help="The manager who authorised the discount. Blank means it went "
             "through without a manager sign-off, either because none was "
             "required or because the limit was not reached.",
    )
    manager_name = fields.Char(
        string="Manager Name",
        help="The approving manager's name as it was at the time, kept as text so "
             "the record still reads correctly after staff are renamed or leave.",
    )
    config_id = fields.Many2one(
        'pos.config',
        string="Branch",
        required=True,
        index=True,
        help="The till or shop that gave the discount, so you can see where "
             "money is being given away.",
    )

    original_amount = fields.Monetary(
        string="Original Amount",
        currency_field='currency_id',
        help="What the sale added up to before anything was taken off, tax "
             "included; captured when the sale was completed.",
    )
    discount_amount = fields.Monetary(
        string="Discount Amount",
        currency_field='currency_id',
        help="How much money came off the whole sale, tax included. Shown as a "
             "positive figure, so a larger number means a bigger giveaway.",
    )
    discount_percentage = fields.Float(
        string="Discount Percentage",
        help="The discount as a share of the original amount, worked out at the "
             "time of sale. Useful for spotting unusually generous deals.",
    )
    discount_input_type = fields.Selection(
        [('fixed', 'Fixed Amount'), ('percent', 'Percentage')],
        string="Discount Entry Type",
        help="How the cashier keyed the discount in, as a cash amount or as a "
             "percentage. The money taken off is the same either way; this only "
             "records the way it was entered.",
    )
    round_off_amount = fields.Monetary(
        string="Round-Off Amount",
        currency_field='currency_id',
        help="The small adjustment made to bring the total to an amount you can "
             "take in coins. Positive means the customer paid slightly more than "
             "the true total, negative slightly less.",
    )
    final_amount = fields.Monetary(
        string="Final Amount",
        currency_field='currency_id',
        help="What the customer was actually asked to pay, after the discount and "
             "the rounding.",
    )

    reason_id = fields.Many2one(
        'pos.retail.discount.reason',
        string="Discount Reason",
        help="The reason picked from your own list when the discount was given, "
             "for example damaged stock or a staff purchase.",
    )
    reason_notes = fields.Text(
        string="Reason Notes",
        help="Anything typed at the till to explain this particular discount, on "
             "top of the reason chosen from the list.",
    )

    date = fields.Datetime(
        string="Date & Time",
        index=True,
        help="When the sale was completed. Every figure on this row is a snapshot "
             "taken at this moment, not a live value.",
    )

    def _compute_order_discount_snapshot(self, order):
        """Derive discount/round-off figures from the order's own authoritative
        lines and native rounding config -- never trust client-reported amounts
        for the numbers that matter for audit purposes."""
        discount_product = order.config_id.discount_product_id
        discount_lines = order.lines.filtered(
            lambda l: discount_product and l.product_id.id == discount_product.id
        )
        other_lines = order.lines - discount_lines

        original_amount = sum(other_lines.mapped('price_subtotal_incl'))
        discount_amount = -sum(discount_lines.mapped('price_subtotal_incl'))
        discount_percentage = (discount_amount / original_amount * 100) if original_amount else 0.0

        rounded_total = order._get_rounded_amount(order.amount_total, force_round=True)
        round_off_amount = rounded_total - order.amount_total

        return {
            'original_amount': original_amount,
            'discount_amount': discount_amount,
            'discount_percentage': discount_percentage,
            'round_off_amount': round_off_amount,
            'final_amount': rounded_total,
        }

    def _create_from_order(self, order):
        snapshot = self._compute_order_discount_snapshot(order)
        if not snapshot['discount_amount'] and not snapshot['round_off_amount']:
            return self.browse()
        return self.create({
            'order_id': order.id,
            'pos_order_ref': order.pos_reference or order.name,
            'partner_id': order.partner_id.id,
            'cashier_id': order.employee_id.id,
            'cashier_name': order.cashier,
            'manager_id': order.discount_manager_id.id,
            'manager_name': order.discount_manager_id.name,
            'config_id': order.config_id.id,
            'discount_input_type': order.discount_input_type,
            'reason_id': order.discount_reason_id.id,
            'reason_notes': order.discount_reason_notes,
            'date': order.date_order,
            **snapshot,
        })
