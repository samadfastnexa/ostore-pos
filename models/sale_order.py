from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # In-person / status-only customer approval of a POS quotation (no portal).
    pos_customer_approved = fields.Boolean(string="Customer Approved", copy=False)
    pos_approved_by = fields.Many2one('hr.employee', string="Approval Recorded By", copy=False)

    @api.model
    def _pos_retail_create_quotation(self, vals):
        """Create a draft sale.order (quotation) from a POS cart.

        `vals` (built client-side by the 'Save as Quotation' button):
            partner_id      -> the quotation customer (required)
            validity_date   -> optional YYYY-MM-DD
            approved        -> optional, mark customer-approved on creation
            approved_by     -> optional hr.employee id (the cashier)
            lines           -> [{product_id, qty, price_unit, discount, tax_ids}]
        Returns {id, name}.
        """
        partner_id = vals.get('partner_id')
        if not partner_id:
            raise UserError(_("Select a customer before saving a quotation."))
        if not vals.get('lines'):
            raise UserError(_("Add at least one product before saving a quotation."))

        order_lines = [
            (0, 0, {
                'product_id': line['product_id'],
                'product_uom_qty': line.get('qty', 1),
                'discount': line.get('discount', 0.0),
            })
            for line in vals['lines']
        ]
        order_vals = {'partner_id': partner_id, 'order_line': order_lines}
        if vals.get('validity_date'):
            order_vals['validity_date'] = vals['validity_date']
        if vals.get('approved'):
            order_vals['pos_customer_approved'] = True
            order_vals['pos_approved_by'] = vals.get('approved_by')

        order = self.create(order_vals)
        # Preserve the exact prices the cashier quoted at the till (sale.order.line
        # otherwise recomputes price_unit from the pricelist).
        for sol, line in zip(order.order_line, vals['lines']):
            if line.get('price_unit') is not None:
                sol.price_unit = line['price_unit']
        return {'id': order.id, 'name': order.name}

    def action_pos_customer_approved(self):
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid)], limit=1)
        self.write({
            'pos_customer_approved': True,
            'pos_approved_by': employee.id or False,
        })
