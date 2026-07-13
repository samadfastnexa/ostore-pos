from odoo import fields, models


class PosRetailDiscountLog(models.Model):
    _name = 'pos.retail.discount.log'
    _description = "POS Order Discount & Round-Off Audit Log"
    _order = 'date desc, id desc'
    _rec_name = 'order_id'

    order_id = fields.Many2one('pos.order', required=True, ondelete='cascade', index=True)
    pos_order_ref = fields.Char(string="Order Reference")

    currency_id = fields.Many2one('res.currency', related='order_id.currency_id', store=True)
    company_id = fields.Many2one('res.company', related='order_id.company_id', store=True)

    partner_id = fields.Many2one('res.partner', string="Customer")
    cashier_id = fields.Many2one('hr.employee', string="Cashier")
    cashier_name = fields.Char(string="Cashier Name")
    manager_id = fields.Many2one('hr.employee', string="Approving Manager")
    manager_name = fields.Char(string="Manager Name")
    config_id = fields.Many2one('pos.config', string="Branch", required=True, index=True)

    original_amount = fields.Monetary(string="Original Amount", currency_field='currency_id')
    discount_amount = fields.Monetary(string="Discount Amount", currency_field='currency_id')
    discount_percentage = fields.Float(string="Discount Percentage")
    discount_input_type = fields.Selection(
        [('fixed', 'Fixed Amount'), ('percent', 'Percentage')],
        string="Discount Entry Type",
    )
    round_off_amount = fields.Monetary(string="Round-Off Amount", currency_field='currency_id')
    final_amount = fields.Monetary(string="Final Amount", currency_field='currency_id')

    reason_id = fields.Many2one('pos.retail.discount.reason', string="Discount Reason")
    reason_notes = fields.Text(string="Reason Notes")

    date = fields.Datetime(string="Date & Time", index=True)

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
