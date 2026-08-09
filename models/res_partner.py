from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.addons.pos_retail.models.pos_retail_expense import PAYMENT_METHODS


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

    @api.model
    def get_import_templates(self):
        """Offer a supplier sheet on the Vendors Import screen.

        No supplier_rank column: the Vendors action carries
        default_supplier_rank=1 in its context, and base_import honours action
        defaults on the records it creates. Importing the same file from All
        Contacts would therefore make plain contacts instead of suppliers,
        which is why the guide says which menu to use.
        """
        return [{
            'label': _("Supplier List"),
            'template': '/pos_retail/import-template/vendor.xlsx',
        }]

    birthday = fields.Date(
        string="Birthday",
        help="The customer's date of birth, if they are happy to give it. Shown "
             "to the cashier at the till so you can greet regulars or run "
             "birthday offers.",
    )
    membership_level_id = fields.Many2one(
        'pos.membership.level', string="Membership Level", index=True,
        ondelete='set null',
        help="Which tier this customer belongs to, e.g. Silver or Gold. Leave "
             "empty for an ordinary walk-in customer with no membership.",
    )

    mobile = fields.Char(
        string="Mobile",
        help="Mobile number for this contact, kept apart from the main phone. "
             "This is usually the number that actually reaches a customer or a "
             "vendor's salesman.",
    )
    vendor_contact_person = fields.Char(
        string="Contact Person",
        help="The person you actually deal with at this vendor, e.g. the "
             "salesman who takes your order. Useful when the vendor record is a "
             "company rather than a person.",
    )

    # --- Vendor management ------------------------------------------------
    # Native already covers: name, company, phone, mobile, email, website,
    # VAT (tax registration), the whole address, supplier payment terms,
    # purchase currency, credit limit, outstanding payable (debit) and bank
    # accounts. These are the gaps.
    vendor_code = fields.Char(
        string="Vendor Code", copy=False, index='btree_not_null',
        help="Short code for this vendor, generated on demand. Kept separate "
             "from Reference, which is the customer-facing ID printed on "
             "receipts.",
    )
    vendor_licence_no = fields.Char(
        string="Business License No.",
        help="Trade or business licence number, where the vendor has one.",
    )
    vendor_payment_method = fields.Selection(
        PAYMENT_METHODS, string="Preferred Payment Method",
        help="How this vendor usually wants to be paid.",
    )
    vendor_lead_time = fields.Integer(
        string="Lead Time (Days)",
        help="Typical days between ordering and delivery. Used as the default "
             "for new product lines for this vendor; each product can override "
             "it, since a vendor may be quick on one item and slow on another.",
    )
    vendor_delivery_method = fields.Char(
        string="Delivery Method",
        help="How goods arrive, e.g. own transport, TCS, Leopard, collection.",
    )
    vendor_status = fields.Selection(
        [
            ('active', "Active"),
            ('inactive', "Inactive"),
            ('blacklisted', "Blacklisted"),
        ],
        string="Vendor Status", default='active', index=True, tracking=True,
        help="Blacklisted vendors cannot be put on new purchase orders. "
             "Inactive is a softer state: still selectable, but flagged as one "
             "you have stopped buying from.",
    )

    supplierinfo_ids = fields.One2many(
        'product.supplierinfo', 'partner_id', string="Products Supplied",
        help="Everything this vendor is set up to sell you, each line carrying "
             "their price, minimum order quantity and lead time for that item.",
    )
    products_supplied_count = fields.Integer(
        string="# Products Supplied", compute='_compute_products_supplied_count',
        help="How many different products this vendor is set up to supply. Zero "
             "means no product pricing has been linked to them yet.",
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
        help="Everything this customer has ever paid at the till, across every "
             "session since you started. Refunds are counted separately and are "
             "not deducted here.",
    )
    pos_avg_order_value = fields.Monetary(
        string="Average Order Value (POS)", compute='_compute_pos_history',
        currency_field='pos_history_currency_id',
        help="Their all-time till spending divided by the number of sales, so "
             "you can see the size of their typical basket at a glance.",
    )
    pos_last_purchase_date = fields.Datetime(
        string="Last Purchase", compute='_compute_pos_history',
        help="When this customer last bought something at the till. Blank means "
             "they have never bought from you, or only ever returned goods.",
    )
    pos_sales_order_count = fields.Integer(
        string="POS Sales Orders", compute='_compute_pos_history',
        help="How many separate till sales this customer has made, all time. "
             "Refunds are not included in this count.",
    )
    pos_refund_total = fields.Monetary(
        string="Refunds Total (POS)", compute='_compute_pos_history',
        currency_field='pos_history_currency_id',
        help="Total value of goods this customer has returned at the till, all "
             "time, shown as a positive amount. A high figure next to modest "
             "spending is worth a look.",
    )
    pos_loyalty_points = fields.Float(
        string="Loyalty Points", compute='_compute_pos_loyalty_points',
        help="Points this customer has earned on loyalty programmes. Gift card "
             "and store-credit balances are money rather than points, so they "
             "are deliberately not counted here.",
    )
    pos_retail_note = fields.Text(
        string="Counter Note",
        help="Shown to the cashier when this customer is selected, e.g. "
             "\"deliver to home\" or \"always needs an invoice\". Keep it short; "
             "it is read mid-sale.",
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
        # NOT "Credit Limit": account already owns that label on res.partner, and
        # two fields sharing one label makes Odoo warn at every install, breaks
        # label-based import matching (our import templates key off labels) and
        # gives exports two identical columns. Read-only mirror of the accounting
        # figure, only ever rendered inside the POS, so the suffix costs nothing.
        string="Credit Limit (Till)", compute='_compute_pos_credit_figures',
        compute_sudo=True, currency_field='pos_history_currency_id',
        help="How much this customer may owe at once, as enforced at the till. "
             "Mirrors the accounting Credit Limit. Zero means no limit.",
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
                      'pos_credit_limit', 'pos_credit_available',
                      'category_id', 'pos_retail_note'):
            if fname not in result:
                result.append(fname)
        return result

    def get_pos_customer_history(self, limit=12):
        """Everything the cashier might want to know about a customer, in one call.

        Deliberately one round trip rather than several: it is triggered by a
        cashier tapping a button mid-sale, so latency is felt directly. The
        POS session only carries recent orders, and nothing at all about
        payments, invoices or the ledger, so this has to come from the server;
        the caller is expected to handle being offline.

        Runs as sudo on purpose: a cashier legitimately needs to see what this
        customer owes and has bought, but must not be given accounting rights
        to get it (core restricts those fields to the accounting groups).
        """
        self.ensure_one()
        partner = self.sudo()
        currency = self.env.company.currency_id

        def money(amount):
            return {'amount': amount, 'formatted': currency.format(amount)}

        # --- POS sales, split into ordinary sales and refunds -------------
        # id desc breaks ties: several orders can share a timestamp on a busy
        # till, and "their last order" must be a single definite basket.
        orders = self.env['pos.order'].sudo().search(
            [('partner_id', '=', partner.id), ('state', '!=', 'cancel')],
            order='date_order desc, id desc', limit=200,
        )
        sales = orders.filtered(lambda o: o.amount_total >= 0)
        refunds = orders - sales

        def order_row(order):
            return {
                'id': order.id,
                'name': order.pos_reference or order.name,
                'date': order.date_order and str(order.date_order) or '',
                'amount': order.amount_total,
                'amount_formatted': currency.format(order.amount_total),
                'state': order.state,
                'invoice': order.account_move.name or '',
                'cashier': order.employee_id.name or order.user_id.name or '',
            }

        # --- What they usually buy ---------------------------------------
        # Counted by number of separate visits the product appeared in, not by
        # quantity: "bought milk 120 times" is what a cashier means, whereas
        # summing litres would rank one bulk purchase above a daily habit.
        lines = self.env['pos.order.line'].sudo().search(
            [('order_id', 'in', orders.ids), ('qty', '>', 0)],
        )
        product_stats = {}
        for line in lines:
            product = line.product_id
            if not product:
                continue
            stat = product_stats.setdefault(product.id, {
                'name': product.display_name, 'times': 0, 'qty': 0.0, 'spent': 0.0,
            })
            stat['times'] += 1
            stat['qty'] += line.qty
            stat['spent'] += line.price_subtotal_incl
        top_products = sorted(
            product_stats.values(), key=lambda s: (-s['times'], -s['spent']))[:8]
        for stat in top_products:
            stat['spent_formatted'] = currency.format(stat['spent'])

        # --- The last basket, for a one-tap repeat ------------------------
        last_order = sales[:1]
        last_basket = []
        if last_order:
            for line in last_order.lines:
                if line.qty <= 0 or not line.product_id:
                    continue
                last_basket.append({
                    'product_id': line.product_id.id,
                    'name': line.full_product_name or line.product_id.display_name,
                    'qty': line.qty,
                })

        # --- Money owed and paid -----------------------------------------
        receivable = self.env['account.move.line'].sudo().search(
            [('partner_id', '=', partner.id),
             ('account_id.account_type', '=', 'asset_receivable'),
             ('parent_state', '=', 'posted')],
            order='date desc, id desc', limit=limit,
        )
        payments, charges, open_invoices = [], [], []
        for line in receivable:
            row = {
                'date': str(line.date),
                'ref': line.move_id.name or '',
                'label': line.name or '',
                'debit': line.debit,
                'credit': line.credit,
                'amount_formatted': currency.format(line.credit or line.debit),
                'residual': line.amount_residual,
            }
            (payments if line.credit else charges).append(row)
            if line.debit and line.amount_residual:
                open_invoices.append(dict(
                    row, residual_formatted=currency.format(line.amount_residual)))

        # --- Quotations still open ---------------------------------------
        quotations = []
        sale_order = self.env['sale.order'].sudo()
        for so in sale_order.search(
            [('partner_id', '=', partner.id), ('state', 'in', ('draft', 'sent'))],
            order='date_order desc', limit=limit,
        ):
            quotations.append({
                'name': so.name,
                'date': so.date_order and str(so.date_order) or '',
                'amount_formatted': currency.format(so.amount_total),
                'state': so.state,
            })

        return {
            'partner_id': partner.id,
            'sales': [order_row(o) for o in sales[:limit]],
            'sales_count': len(sales),
            'refunds': [order_row(o) for o in refunds[:limit]],
            'refunds_count': len(refunds),
            'credit_sales': [
                order_row(o) for o in sales.filtered(
                    lambda o: any(p.payment_method_id.type == 'pay_later'
                                  for p in o.payment_ids))[:limit]
            ],
            'payments': payments,
            'charges': charges,
            'open_invoices': open_invoices,
            'quotations': quotations,
            'top_products': top_products,
            'last_basket': last_basket,
            'last_order_name': last_order.pos_reference or last_order.name or '',
            'last_order_date': last_order.date_order and str(last_order.date_order) or '',
            'last_order_total': last_order and currency.format(last_order.amount_total) or '',
            'outstanding': money(partner.credit or 0.0),
        }

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

    def action_generate_vendor_code(self):
        """Give each vendor a code, skipping any that already has one.

        Never overwrites: a code may already be printed on the vendor's
        paperwork or used in their own system.
        """
        sequence = self.env['ir.sequence']
        for partner in self:
            if not partner.vendor_code:
                partner.vendor_code = sequence.next_by_code('pos.retail.vendor.code')
        return True

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
