from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model_create_multi
    def create(self, vals_list):
        # Quick POS customer add: allow name OR phone (either optional, at least
        # one). When only a phone is given, name the partner after the phone so
        # it has a usable display name on the receipt. Scoped to the POS quick
        # form's context so normal partner creation is untouched.
        if self.env.context.get('pos_quick_customer'):
            for vals in vals_list:
                name = (vals.get('name') or '').strip()
                phone = (vals.get('phone') or '').strip()
                if not name and not phone:
                    raise UserError(_("Please enter a customer name or a phone number."))
                if not name and phone:
                    vals['name'] = phone
        return super().create(vals_list)

    birthday = fields.Date(string="Birthday")
    membership_level_id = fields.Many2one(
        'pos.membership.level', string="Membership Level", index=True,
        ondelete='set null',
    )

    mobile = fields.Char(string="Mobile")
    vendor_contact_person = fields.Char(string="Contact Person")
    supplierinfo_ids = fields.One2many(
        'product.supplierinfo', 'partner_id', string="Products Supplied",
    )
    products_supplied_count = fields.Integer(
        string="# Products Supplied", compute='_compute_products_supplied_count',
    )

    # --- POS purchase history (#14) --------------------------------------
    # Native already provides: pos_order_count, pos_order_ids, credit
    # (outstanding), total_invoiced, and loyalty.card.points. These fill the
    # remaining aggregates the customer profile should show.
    pos_history_currency_id = fields.Many2one(
        'res.currency', compute='_compute_pos_history', string="POS History Currency",
    )
    pos_total_spent = fields.Monetary(
        string="Total Spending (POS)", compute='_compute_pos_history',
        currency_field='pos_history_currency_id',
    )
    pos_avg_order_value = fields.Monetary(
        string="Average Order Value (POS)", compute='_compute_pos_history',
        currency_field='pos_history_currency_id',
    )
    pos_last_purchase_date = fields.Datetime(
        string="Last Purchase", compute='_compute_pos_history',
    )
    pos_sales_order_count = fields.Integer(
        string="POS Sales Orders", compute='_compute_pos_history',
    )
    pos_refund_total = fields.Monetary(
        string="Refunds Total (POS)", compute='_compute_pos_history',
        currency_field='pos_history_currency_id',
    )

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        # 'phone' is already loaded natively; add 'ref' so the receipt can show
        # a Customer ID. birthday/membership_level_id are for POS customer info.
        for fname in ('birthday', 'membership_level_id', 'ref'):
            if fname not in result:
                result.append(fname)
        return result

    @api.model
    def _load_pos_data_domain(self, data, config):
        # Keep staff out of the POS customer list: employee-linked partners are
        # cashiers/employees, not buyers, and shouldn't be selectable as the
        # customer on a sale (that's how a cashier's name ends up on an order).
        domain = super()._load_pos_data_domain(data, config)
        return domain + [('employee', '=', False)]

    def _compute_pos_history(self):
        company_currency = self.env.company.currency_id
        for partner in self:
            partner.pos_history_currency_id = company_currency
            partner.pos_total_spent = 0.0
            partner.pos_avg_order_value = 0.0
            partner.pos_last_purchase_date = False
            partner.pos_sales_order_count = 0
            partner.pos_refund_total = 0.0
        if not self.ids:
            return
        PosOrder = self.env['pos.order']
        base = [('partner_id', 'in', self.ids), ('state', 'in', ('paid', 'done', 'invoiced'))]
        # Sales (positive totals): spending, count, last purchase date.
        sales = PosOrder._read_group(
            base + [('amount_total', '>=', 0)],
            groupby=['partner_id'],
            aggregates=['amount_total:sum', '__count', 'date_order:max'],
        )
        sales_map = {p.id: (total, count, last) for p, total, count, last in sales}
        # Refunds / returns (negative totals).
        refunds = PosOrder._read_group(
            base + [('amount_total', '<', 0)],
            groupby=['partner_id'],
            aggregates=['amount_total:sum'],
        )
        refund_map = {p.id: total for p, total in refunds}
        for partner in self:
            total, count, last = sales_map.get(partner.id, (0.0, 0, False))
            partner.pos_total_spent = total
            partner.pos_sales_order_count = count
            partner.pos_avg_order_value = (total / count) if count else 0.0
            partner.pos_last_purchase_date = last
            partner.pos_refund_total = abs(refund_map.get(partner.id, 0.0))

    def _compute_products_supplied_count(self):
        counts = dict(self.env['product.supplierinfo']._read_group(
            domain=[('partner_id', 'in', self.ids)],
            groupby=['partner_id'],
            aggregates=['product_tmpl_id:count_distinct'],
        ))
        for partner in self:
            partner.products_supplied_count = counts.get(partner, 0)

    def action_view_supplierinfo(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Products Supplied"),
            'res_model': 'product.supplierinfo',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_view_outstanding_bills(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Outstanding Vendor Bills"),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [
                ('partner_id', 'child_of', self.id),
                ('move_type', 'in', ('in_invoice', 'in_refund')),
                ('payment_state', '!=', 'paid'),
            ],
            'context': {'default_move_type': 'in_invoice', 'default_partner_id': self.id},
        }
