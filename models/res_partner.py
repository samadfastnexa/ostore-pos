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
    pos_loyalty_points = fields.Float(
        string="Loyalty Points", compute='_compute_pos_loyalty_points',
        help="Points this customer has earned on loyalty programmes. Gift card "
             "and store-credit balances are money rather than points, so they "
             "are deliberately not counted here.",
    )
    # Till-safe mirrors of the accounting figures. Core restricts `credit` and
    # `credit_limit` to the accounting groups at FIELD level, so a cashier
    # cannot read them at all -- yet the cashier is exactly who needs to know
    # what this customer owes before selling to them on account. These expose
    # those two numbers, and nothing else, computed with sudo.
    pos_outstanding_balance = fields.Monetary(
        string="Outstanding Balance", compute='_compute_pos_credit_figures',
        compute_sudo=True, currency_field='pos_history_currency_id',
        help="What this customer currently owes the shop.",
    )
    pos_credit_limit = fields.Monetary(
        string="Credit Limit", compute='_compute_pos_credit_figures',
        compute_sudo=True, currency_field='pos_history_currency_id',
        help="How much this customer may owe at once. Zero means no limit.",
    )
    pos_credit_available = fields.Monetary(
        string="Credit Available", compute='_compute_pos_credit_figures',
        compute_sudo=True, currency_field='pos_history_currency_id',
        help="Credit limit less what the customer already owes. Negative means "
             "they are already over their limit.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        # 'phone' is already loaded natively; add 'ref' so the receipt can show
        # a Customer ID. birthday/membership_level_id are for POS customer info.
        # The rest feed the in-POS customer profile card and the credit-limit
        # check on Customer Account payments.
        for fname in ('birthday', 'membership_level_id', 'ref',
                      'pos_total_spent', 'pos_avg_order_value',
                      'pos_last_purchase_date', 'pos_sales_order_count',
                      'pos_loyalty_points', 'pos_outstanding_balance',
                      'pos_credit_limit', 'pos_credit_available'):
            if fname not in result:
                result.append(fname)
        return result

    def _compute_pos_loyalty_points(self):
        """Points across all of the customer's loyalty/eWallet cards.

        Read in one grouped query rather than per partner: the customer list
        renders this for everyone on screen at once.
        """
        self.pos_loyalty_points = 0.0
        if not self.ids:
            return
        card = self.env['loyalty.card'].sudo()
        grouped = card._read_group(
            [('partner_id', 'in', self.ids),
             ('program_id.program_type', '=', 'loyalty')],
            ['partner_id'], ['points:sum'],
        )
        totals = {partner.id: points for partner, points in grouped}
        for partner in self:
            partner.pos_loyalty_points = totals.get(partner.id, 0.0)

    @api.depends('credit_limit', 'credit')
    def _compute_pos_credit_figures(self):
        for partner in self:
            balance = partner.credit or 0.0
            limit = partner.credit_limit or 0.0
            partner.pos_outstanding_balance = balance
            partner.pos_credit_limit = limit
            partner.pos_credit_available = limit - balance

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

    def action_view_customer_ledger(self):
        """This customer's running receivable ledger: every posted journal
        item that ever affected their balance (invoices/pay-later sales,
        refunds, payments they've made), newest first, with a running balance
        -- the detail behind the single "Outstanding Balance" (credit) figure
        already shown on the POS History tab. Domain is scoped to a single
        partner_id, which is what makes the running-balance column
        (account.move.line's own cumulated_balance, auto-computed via that
        model's search_fetch override) meaningful; mixing several customers'
        lines into one running total would not be. The newest-first order
        comes from the list view and is required for that column to read
        correctly; see the note in pos_retail_customer_ledger_views.xml.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Customer Ledger"),
            'res_model': 'account.move.line',
            'view_mode': 'list',
            'views': [(self.env.ref('pos_retail.pos_retail_customer_ledger_view_list').id, 'list')],
            'search_view_id': (self.env.ref('pos_retail.pos_retail_customer_ledger_view_search').id, 'search'),
            'domain': [
                ('partner_id', '=', self.id),
                ('account_id.account_type', '=', 'asset_receivable'),
                ('parent_state', '=', 'posted'),
                # Same company scope as the `credit` figure on the smart button
                # (see account/models/partner.py) -- without this, a user with
                # several companies enabled would see other companies' lines
                # mixed in, and cumulated_balance (computed with
                # bypass_access=True) would disagree with the button's number.
                ('company_id', 'child_of', self.env.company.root_id.id),
            ],
        }

    def action_receive_customer_payment(self):
        """Record money received from this customer: a pre-filled inbound
        payment. Once confirmed it posts to the receivable and the ledger and
        the Amount Owed figure drop accordingly.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Receive Payment"),
            'res_model': 'account.payment',
            'view_mode': 'form',
            'context': {
                'default_payment_type': 'inbound',
                'default_partner_type': 'customer',
                'default_partner_id': self.id,
            },
        }

    def action_open_ledger_adjustment(self):
        """Khata adjustment dialog: bring in an old paper-khata balance,
        waive an amount, or correct the balance -- via a real, posted journal
        entry (see pos.retail.ledger.adjustment for why history itself is
        never edited in place).
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Khata Adjustment"),
            'res_model': 'pos.retail.ledger.adjustment',
            'view_mode': 'form',
            'target': 'new',
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
