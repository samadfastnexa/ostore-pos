from werkzeug import urls

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
        self._pos_retail_apply_quoted_prices(order, vals['lines'])
        # A quotation handed to the customer is 'sent'; one saved to finish
        # later stays 'draft'. Both are quotations, but only one has been
        # given out, and the back office needs to tell them apart.
        if not vals.get('draft'):
            order.state = 'sent'
        return self._pos_retail_quote_summary(order)

    @api.model
    def _pos_retail_apply_quoted_prices(self, order, lines):
        """Force the prices the cashier actually quoted.

        sale.order.line recomputes price_unit from the pricelist on create,
        which would silently change the figure the customer was told.
        """
        for sol, line in zip(order.order_line, lines):
            if line.get('price_unit') is not None:
                sol.price_unit = line['price_unit']

    @api.model
    def _pos_retail_quote_summary(self, order):
        return {
            'id': order.id,
            'name': order.name,
            'state': order.state,
            'partner_name': order.partner_id.name or '',
            'amount_total': order.amount_total,
            'date': order.date_order and str(order.date_order) or '',
            'validity_date': order.validity_date and str(order.validity_date) or '',
            'approved': order.pos_customer_approved,
            'line_count': len(order.order_line),
        }

    @api.model
    def _pos_retail_search_quotations(self, partner_id=None, limit=30):
        """Open quotations the till may duplicate or update.

        Confirmed orders are excluded: once an order is confirmed it is no
        longer a quotation, and rewriting it from a POS cart would rewrite a
        commitment the customer has already accepted.
        """
        domain = [('state', 'in', ('draft', 'sent'))]
        if partner_id:
            domain.append(('partner_id', '=', partner_id))
        orders = self.search(domain, order='date_order desc, id desc', limit=limit)
        return [self._pos_retail_quote_summary(o) for o in orders]

    @api.model
    def _pos_retail_duplicate_quotation(self, order_id):
        """Copy an existing quotation into a fresh draft.

        Uses Odoo's own copy(), so anything a quotation carries that the POS
        cart never knew about (delivery terms, fiscal position, custom fields
        from other modules) travels with it.
        """
        source = self.browse(order_id)
        if not source.exists():
            raise UserError(_("That quotation no longer exists."))
        copy = source.copy()
        # A duplicate has not been given to anyone yet, and its approval
        # belongs to the original.
        copy.write({'state': 'draft', 'pos_customer_approved': False,
                    'pos_approved_by': False})
        return self._pos_retail_quote_summary(copy)

    @api.model
    def _pos_retail_update_quotation(self, order_id, vals):
        """Replace an existing quotation's lines with the current POS cart.

        Replace rather than append: the cashier has rebuilt the basket in
        front of the customer, so the cart IS the new quote. Appending would
        silently double every line the customer already had.
        """
        order = self.browse(order_id)
        if not order.exists():
            raise UserError(_("That quotation no longer exists."))
        if order.state not in ('draft', 'sent'):
            raise UserError(_(
                "%(name)s is already confirmed and can no longer be changed "
                "from the till. Duplicate it instead.", name=order.name))
        if not vals.get('lines'):
            raise UserError(_("Add at least one product before updating a quotation."))

        order.order_line.unlink()
        order.write({
            'order_line': [
                (0, 0, {
                    'product_id': line['product_id'],
                    'product_uom_qty': line.get('qty', 1),
                    'discount': line.get('discount', 0.0),
                })
                for line in vals['lines']
            ],
        })
        self._pos_retail_apply_quoted_prices(order, vals['lines'])
        if vals.get('validity_date'):
            order.validity_date = vals['validity_date']
        if vals.get('partner_id') and vals['partner_id'] != order.partner_id.id:
            order.partner_id = vals['partner_id']
        # The quote changed, so any previous customer approval no longer
        # refers to what this document now says.
        if order.pos_customer_approved:
            order.write({'pos_customer_approved': False, 'pos_approved_by': False})
        return self._pos_retail_quote_summary(order)

    def _pos_retail_quote_qr_url(self):
        """Barcode-controller URL for a QR of this quotation's portal link.

        Built here rather than in the template because the value has to be
        percent-encoded (a portal URL carries '?', '&' and '=' of its own,
        which would otherwise terminate the barcode query string early and
        produce a QR of a truncated link).
        """
        self.ensure_one()
        target = f"{self.get_base_url()}{self.get_portal_url()}"
        params = urls.url_encode({
            'barcode_type': 'QR',
            'value': target,
            'width': 180,
            'height': 180,
            'quiet': 0,
        })
        return f"/report/barcode/?{params}"

    def action_pos_customer_approved(self):
        employee = self.env['hr.employee'].search(
            [('user_id', '=', self.env.uid)], limit=1)
        self.write({
            'pos_customer_approved': True,
            'pos_approved_by': employee.id or False,
        })
