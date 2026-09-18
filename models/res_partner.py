import datetime
import hashlib
import hmac
import pytz
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.addons.pos_retail.models.pos_retail_expense import PAYMENT_METHODS


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _format_datetime_pak(self, dt, include_time=True):
        """Format a UTC datetime/date into Pakistan Standard Time (PKT, UTC+5)."""
        if not dt:
            return ''
        user_tz = self.env.user.tz
        if not user_tz or user_tz in ('UTC', 'Etc/UTC', 'GMT'):
            tz_name = 'Asia/Karachi'
        else:
            tz_name = user_tz
        try:
            target_tz = pytz.timezone(tz_name)
        except Exception:
            target_tz = pytz.timezone('Asia/Karachi')

        if isinstance(dt, datetime.datetime):
            if not dt.tzinfo:
                utc_dt = pytz.utc.localize(dt)
            else:
                utc_dt = dt.astimezone(pytz.utc)
            local_dt = utc_dt.astimezone(target_tz)
            fmt = '%Y-%m-%d %H:%M' if include_time else '%Y-%m-%d'
            return local_dt.strftime(fmt)
        elif isinstance(dt, datetime.date):
            return dt.strftime('%Y-%m-%d')
        elif isinstance(dt, str):
            try:
                dt_obj = fields.Datetime.to_datetime(dt)
                if dt_obj:
                    return self._format_datetime_pak(dt_obj, include_time=include_time)
            except Exception:
                pass
            return dt[:16] if include_time else dt[:10]
        return str(dt)[:16] if include_time else str(dt)[:10]

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

    def unlink(self):
        # Core refuses to delete a partner that appears on a journal entry
        # (account/models/partner.py, _unlink_if_partner_in_account_move) and
        # says only "The partner cannot be deleted because it is used in
        # Accounting". That is correct -- deleting it would leave invoices with
        # no counterparty -- but it is a dead end for the person at the screen,
        # because the thing they actually want is to ARCHIVE the contact, and
        # nothing in the message tells them so.
        #
        # Done here rather than as another @api.ondelete because ondelete
        # methods have no guaranteed order between modules: whichever fires
        # first wins the message, and that would make the wording a coin toss.
        # unlink() runs before all of them.
        blocked = self.browse()
        if self.ids:
            groups = self.env['account.move'].sudo()._read_group(
                [('partner_id', 'in', self.ids), ('state', 'in', ['draft', 'posted'])],
                groupby=['partner_id'],
            )
            blocked = self.browse([group[0].id for group in groups])
        if blocked:
            raise UserError(_(
                "%(names)s cannot be deleted, because invoices, bills or "
                "payments are recorded against them. Deleting the contact "
                "would leave those entries with no customer or vendor on "
                "them.\n\n"
                "Hide the contact instead: open it, click the gear icon next "
                "to the name and choose Hide. It then disappears from the "
                "customer and vendor lists and from the POS, while the "
                "accounting history stays intact. You can unhide it at any "
                "time.",
                names=", ".join(blocked.mapped('display_name')),
            ))
        return super().unlink()

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
        # check on Customer Credit payments.
        for fname in ('birthday', 'membership_level_id', 'ref',
                      'pos_total_spent', 'pos_avg_order_value',
                      'pos_last_purchase_date', 'pos_sales_order_count',
                      'pos_loyalty_points', 'pos_outstanding_balance',
                      'pos_credit_limit', 'pos_credit_available',
                      'category_id', 'pos_retail_note'):
            if fname not in result:
                result.append(fname)
        return result

    def _get_pos_khata_breakdown(self):
        """Unified, FIFO-allocated customer credit and khata breakdown for a partner.

        Computes:
          1. Lifetime posted accounting receivable movements (invoices, debit notes, credit notes, payments)
          2. All un-invoiced POS orders (both open and closed sessions) where payment was on credit/khata
          3. Exact FIFO allocation of available customer payments against oldest credit debts
          4. Total purchases (charges/debit), total paid (credit), and net balance owed.
        """
        self.ensure_one()
        partner = self.sudo()
        currency = partner.currency_id or partner.company_id.currency_id or self.env.company.currency_id
        if not partner.id or not isinstance(partner.id, int):
            return {
                'partner': partner,
                'currency': currency,
                'cust_debit_total': 0.0,
                'cust_credit_total': 0.0,
                'cust_balance': 0.0,
                'total_owed': 0.0,
                'acc_debit': 0.0,
                'acc_credit': 0.0,
                'acc_balance': 0.0,
                'uninvoiced_sales_total': 0.0,
                'uninvoiced_cash_paid_total': 0.0,
                'uninvoiced_credit_debt_total': 0.0,
                'order_allocations': {},
                'advance_pool': 0.0,
            }

        def is_credit_pm(pm):
            if not pm:
                return False
            pm_sudo = pm.sudo()
            if pm_sudo.type == 'pay_later':
                return True
            name = (pm_sudo.name or '').strip().lower()
            return any(k in name for k in ('credit', 'khata', 'pay later', 'pay_later', 'udhar', 'customer account', 'on account'))

        # 1. Lifetime posted receivable entries in accounting
        rec_grouped = self.env['account.move.line'].sudo()._read_group(
            domain=[
                ('partner_id', '=', partner.id),
                ('account_id.account_type', '=', 'asset_receivable'),
                ('parent_state', '=', 'posted'),
            ],
            aggregates=('debit:sum', 'credit:sum'),
        )
        acc_debit, acc_credit = rec_grouped[0] if rec_grouped else (0.0, 0.0)
        acc_debit = round(acc_debit or 0.0, 2)
        acc_credit = round(acc_credit or 0.0, 2)
        acc_balance = round(acc_debit - acc_credit, 2)

        # 2. All un-invoiced POS orders (NOT cancelled, no account_move posted)
        # Note: We track all un-invoiced POS sales across all sessions (both open and closed).
        pos_orders = self.env['pos.order'].sudo().search(
            [('partner_id', '=', partner.id),
             ('state', '!=', 'cancel'),
             ('account_move', '=', False)],
            order='date_order asc, id asc',
        )

        uninvoiced_sales_total = 0.0
        uninvoiced_cash_paid_total = 0.0
        uninvoiced_credit_debt_total = 0.0
        uninvoiced_order_data = []

        for o in pos_orders:
            total = round(o.amount_total or 0.0, 2)
            if total <= 0:
                uninvoiced_sales_total += total
                uninvoiced_cash_paid_total += total
                continue

            credit_pms = [p for p in o.payment_ids if is_credit_pm(p.payment_method_id)]
            credit_amount = round(sum(p.amount for p in credit_pms), 2)
            if not credit_amount and hasattr(o, 'pos_retail_on_account') and o.pos_retail_on_account:
                credit_amount = round(o.pos_retail_on_account, 2)

            has_credit = credit_amount > 0.005 or bool(credit_pms)
            cash_paid = round(max(total - credit_amount, 0.0), 2) if has_credit else total
            initial_debt = credit_amount if has_credit else 0.0

            uninvoiced_sales_total += total
            uninvoiced_cash_paid_total += cash_paid
            uninvoiced_credit_debt_total += initial_debt

            uninvoiced_order_data.append({
                'order': o,
                'total': total,
                'cash_paid': cash_paid,
                'initial_debt': initial_debt,
                'has_credit': has_credit,
            })

        # 3. FIFO Payment Pool:
        # If acc_balance < 0, customer has unallocated payments/credits in accounting
        # that can settle un-invoiced POS orders oldest first.
        available_pool = round(max(-acc_balance, 0.0), 2)

        order_allocations = {}
        for item in uninvoiced_order_data:
            o_id = item['order'].id
            debt = item['initial_debt']
            if debt <= 0.005:
                order_allocations[o_id] = {
                    'residual': 0.0,
                    'paid': item['total'],
                    'status': 'paid',
                    'status_label': 'Fully Paid',
                }
                continue

            if available_pool >= debt:
                available_pool = round(available_pool - debt, 2)
                order_allocations[o_id] = {
                    'residual': 0.0,
                    'paid': item['total'],
                    'status': 'paid',
                    'status_label': 'Fully Paid',
                }
            elif available_pool > 0.005:
                allocated = available_pool
                available_pool = 0.0
                residual = round(debt - allocated, 2)
                paid = round(item['total'] - residual, 2)
                order_allocations[o_id] = {
                    'residual': residual,
                    'paid': paid,
                    'status': 'partial',
                    'status_label': 'Partially Paid',
                }
            else:
                residual = debt
                paid = round(item['total'] - residual, 2)
                status = 'unpaid' if paid <= 0.005 else 'partial'
                status_label = 'Unpaid' if paid <= 0.005 else 'Partially Paid'
                order_allocations[o_id] = {
                    'residual': residual,
                    'paid': paid,
                    'status': status,
                    'status_label': status_label,
                }

        # 4. Totals across EVERYTHING:
        cust_debit_total = round(acc_debit + uninvoiced_sales_total, 2)
        cust_credit_total = round(acc_credit + uninvoiced_cash_paid_total, 2)
        cust_balance = round(cust_debit_total - cust_credit_total, 2)

        return {
            'partner': partner,
            'currency': currency,
            'cust_debit_total': cust_debit_total,
            'cust_credit_total': cust_credit_total,
            'cust_balance': cust_balance,
            'total_owed': cust_balance,
            'acc_debit': acc_debit,
            'acc_credit': acc_credit,
            'acc_balance': acc_balance,
            'uninvoiced_sales_total': uninvoiced_sales_total,
            'uninvoiced_cash_paid_total': uninvoiced_cash_paid_total,
            'uninvoiced_credit_debt_total': uninvoiced_credit_debt_total,
            'order_allocations': order_allocations,
            'pos_orders': pos_orders,
            'advance_pool': available_pool,
        }

    @api.model
    def get_customer_payment_allocation(self, partner_id, amount):
        """Simulate or compute FIFO allocation of a payment amount against a customer's open debts.

        Used by both POS frontend (for live visible preview) and backend wizards.
        Returns:
          - lines: [ { name, date, previous_balance, applied_amount, remaining_balance, status, status_label } ]
          - previous_total_outstanding
          - payment_amount
          - new_total_outstanding
          - remaining_unallocated (advance)
        """
        partner = self.sudo().browse(int(partner_id)).exists()
        if not partner:
            return {
                'lines': [],
                'previous_total_outstanding': 0.0,
                'previous_total_outstanding_formatted': '0.00',
                'payment_amount': 0.0,
                'payment_amount_formatted': '0.00',
                'new_total_outstanding': 0.0,
                'new_total_outstanding_formatted': '0.00',
                'remaining_unallocated': 0.0,
                'remaining_unallocated_formatted': '0.00',
            }

        currency = partner.currency_id or partner.company_id.currency_id or self.env.company.currency_id
        breakdown = partner._get_pos_khata_breakdown()
        prev_total = breakdown['total_owed']
        amount = round(float(amount or 0.0), 2)

        # Collect all open items with positive residual in chronological order (oldest first: date asc, id asc)
        # 1. Posted receivable accounting invoice lines
        receivable_lines = self.env['account.move.line'].sudo().search([
            ('partner_id', '=', partner.id),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted'),
            ('debit', '>', 0),
        ], order='date asc, id asc')

        open_items = []
        for l in receivable_lines:
            res = round(abs(l.amount_residual), 2)
            if res > 0.005:
                ref = (l.move_id.pos_order_ids and (l.move_id.pos_order_ids[0].pos_reference or l.move_id.pos_order_ids[0].name)) or l.move_id.name or ''
                open_items.append({
                    'id': f"inv_{l.id}",
                    'name': ref,
                    'date': str(l.date),
                    'balance': res,
                    'total': round(l.debit, 2),
                })

        # 2. Un-invoiced POS orders
        pos_orders = breakdown.get('pos_orders') or self.env['pos.order'].sudo().search([
            ('partner_id', '=', partner.id),
            ('state', '!=', 'cancel'),
            ('account_move', '=', False),
        ], order='date_order asc, id asc')
        order_allocations = breakdown['order_allocations']
        for o in pos_orders:
            alloc = order_allocations.get(o.id, {})
            res = alloc.get('residual', 0.0)
            if res > 0.005:
                ref = o.pos_reference or o.name or ''
                date_str = self._format_datetime_pak(o.date_order, include_time=False)
                open_items.append({
                    'id': f"pos_{o.id}",
                    'name': ref,
                    'date': date_str,
                    'balance': res,
                    'total': round(o.amount_total or 0.0, 2),
                })

        # Sort all open items chronologically (oldest first)
        open_items.sort(key=lambda x: (x.get('date') or '', x.get('id') or ''))

        # FIFO allocation
        rem_payment = amount
        allocation_lines = []
        for item in open_items:
            prev_bal = item['balance']
            applied = round(min(rem_payment, prev_bal), 2)
            rem_bal = round(prev_bal - applied, 2)
            rem_payment = round(max(rem_payment - applied, 0.0), 2)

            if rem_bal <= 0.005:
                st = 'paid'
                st_label = 'Paid'
            elif applied > 0.005:
                st = 'partial'
                st_label = 'Balance'
            else:
                st = 'unpaid'
                st_label = 'Outstanding'

            allocation_lines.append({
                'name': item['name'],
                'date': item['date'],
                'previous_balance': prev_bal,
                'previous_balance_formatted': currency.format(prev_bal),
                'applied_amount': applied,
                'applied_amount_formatted': currency.format(applied),
                'remaining_balance': rem_bal,
                'remaining_balance_formatted': currency.format(rem_bal),
                'status': st,
                'status_label': st_label,
            })

        new_total = round(prev_total - (amount - rem_payment), 2)

        return {
            'lines': allocation_lines,
            'previous_total_outstanding': prev_total,
            'previous_total_outstanding_formatted': currency.format(prev_total),
            'payment_amount': amount,
            'payment_amount_formatted': currency.format(amount),
            'new_total_outstanding': new_total,
            'new_total_outstanding_formatted': currency.format(new_total),
            'remaining_unallocated': rem_payment,
            'remaining_unallocated_formatted': currency.format(rem_payment),
        }

    def get_pos_customer_history(self, limit=15):
        """Everything the cashier might want to know about a customer & vendor, in one call.

        Deliberately one round trip rather than several: it is triggered by a
        cashier tapping a button mid-sale on the POS screen, so latency is felt directly.
        The POS session only carries recent orders and nothing at all about
        payments, invoices or the ledger, so this has to come from the server;
        the caller is expected to handle being offline.

        Runs as sudo on purpose: a cashier legitimately needs to see what this
        customer owes, has bought, or vendor balances, but must not be given accounting
        rights to get it (core restricts those fields to the accounting groups).
        """
        self.ensure_one()
        partner = self.sudo()
        currency = (partner.company_id or self.env.company).currency_id

        def money(amount):
            amt = round(amount or 0.0, 2)
            return {'amount': amt, 'formatted': currency.format(amt)}

        # Complete FIFO breakdown across all orders and invoices
        breakdown = partner._get_pos_khata_breakdown()
        order_allocations = breakdown['order_allocations']
        cust_debit_total = breakdown['cust_debit_total']
        cust_credit_total = breakdown['cust_credit_total']
        cust_balance = breakdown['cust_balance']

        # --- POS sales, split into ordinary sales and refunds -------------
        orders = self.env['pos.order'].sudo().search(
            [('partner_id', '=', partner.id), ('state', '!=', 'cancel')],
            order='date_order desc, id desc', limit=200,
        )
        sales = orders.filtered(lambda o: o.amount_total >= 0)
        refunds = orders - sales

        def is_credit_pm(pm):
            if not pm:
                return False
            pm_sudo = pm.sudo()
            if pm_sudo.type == 'pay_later':
                return True
            name = (pm_sudo.name or '').strip().lower()
            return any(k in name for k in ('credit', 'khata', 'pay later', 'pay_later', 'udhar', 'customer account', 'on account'))

        def order_row(order):
            total = round(order.amount_total or 0.0, 2)
            move = order.account_move

            if move and move.amount_residual > 0.005:
                # Invoice exists and has an open residual balance
                residual = round(max(move.amount_residual, 0.0), 2)
                paid = round(max(total - residual, 0.0), 2)
                if abs(residual - total) <= 0.005 or paid <= 0.005:
                    status = 'unpaid'
                    status_label = 'Unpaid'
                else:
                    status = 'partial'
                    status_label = 'Partially Paid'
            elif move:
                paid = total
                residual = 0.0
                status = 'paid'
                status_label = 'Fully Paid'
            elif order.id in order_allocations:
                # Uninvoiced POS order with FIFO settlement
                alloc = order_allocations[order.id]
                residual = alloc['residual']
                paid = alloc['paid']
                status = alloc['status']
                status_label = alloc['status_label']
            elif order.state in ('paid', 'done'):
                paid = total
                residual = 0.0
                status = 'paid'
                status_label = 'Fully Paid'
            elif order.state == 'draft':
                paid = 0.0
                residual = total
                status = 'unpaid'
                status_label = 'Unpaid'
            else:
                paid = total
                residual = 0.0
                status = order.state
                status_label = order.state.capitalize()

            return {
                'id': order.id,
                'name': order.pos_reference or order.name,
                'receipt_number': order.pos_reference or order.name,
                'date': self._format_datetime_pak(order.date_order),
                'amount': total,
                'amount_formatted': currency.format(total),
                'paid_amount': paid,
                'paid_amount_formatted': currency.format(paid),
                'balance_amount': residual,
                'balance_amount_formatted': currency.format(residual),
                'payment_status': status,
                'payment_status_label': status_label,
                'state': order.state,
                'invoice': order.account_move.name or '',
                'cashier': order.employee_id.name or order.user_id.name or '',
            }

        # --- What they usually buy ---------------------------------------
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

        # --- Money owed and paid (Customer Receivable) -------------------
        receivable = self.env['account.move.line'].sudo().search(
            [('partner_id', '=', partner.id),
             ('account_id.account_type', '=', 'asset_receivable'),
             ('parent_state', '=', 'posted')],
            order='date desc, id desc', limit=limit,
        )
        payments, charges, open_invoices = [], [], []
        for line in receivable:
            debit = line.debit or 0.0
            credit = line.credit or 0.0
            amt = round(debit if debit > 0 else credit, 2)
            res = round(abs(line.amount_residual), 2)
            paid = round(max(amt - res, 0.0), 2)
            if res <= 0.005:
                status = 'paid'
                status_label = 'Fully Paid'
            elif abs(res - amt) <= 0.005:
                status = 'unpaid'
                status_label = 'Unpaid'
            else:
                status = 'partial'
                status_label = 'Partially Paid'

            linked_pos = line.move_id.pos_order_ids
            receipt_no = linked_pos and (linked_pos[0].pos_reference or linked_pos[0].name) or line.payment_id.name or line.move_id.name or ''
            memo_desc = line.payment_id.memo or line.name or ''

            row = {
                'id': line.id,
                'date': str(line.date),
                'ref': line.payment_id.name or line.move_id.name or '',
                'receipt_number': receipt_no,
                'label': memo_desc,
                'debit': debit,
                'credit': credit,
                'amount': amt,
                'amount_formatted': currency.format(amt),
                'paid_amount': paid,
                'paid_amount_formatted': currency.format(paid),
                'residual': res,
                'residual_formatted': currency.format(res),
                'payment_status': status,
                'payment_status_label': status_label,
            }
            (payments if credit > 0 else charges).append(row)
            if debit > 0 and res > 0.005:
                open_invoices.append(row)

        # Incorporate all un-invoiced POS orders that still have an outstanding residual
        uninvoiced_pos_orders = breakdown.get('pos_orders') or self.env['pos.order'].sudo().search(
            [('partner_id', '=', partner.id),
             ('state', '!=', 'cancel'),
             ('account_move', '=', False)],
            order='date_order asc, id asc',
        )
        uninvoiced_with_debt = uninvoiced_pos_orders.filtered(
            lambda o: not o.account_move and order_allocations.get(o.id, {}).get('residual', 0.0) > 0.005
        )
        for o in uninvoiced_with_debt:
            o_row = order_row(o)
            session_state_desc = 'Open Session' if o.session_id.state != 'closed' else 'Closed Session'
            open_invoices.append({
                'id': o.id,
                'date': o_row['date'],
                'ref': o_row['name'],
                'receipt_number': o_row['receipt_number'],
                'label': f'POS Order ({session_state_desc})',
                'debit': o_row['amount'],
                'credit': 0.0,
                'amount': o_row['amount'],
                'amount_formatted': o_row['amount_formatted'],
                'paid_amount': o_row['paid_amount'],
                'paid_amount_formatted': o_row['paid_amount_formatted'],
                'residual': o_row['balance_amount'],
                'residual_formatted': o_row['balance_amount_formatted'],
                'payment_status': o_row['payment_status'],
                'payment_status_label': o_row['payment_status_label'],
            })
        open_invoices.sort(key=lambda x: str(x.get('date') or ''), reverse=True)

        # --- Quotations still open ---------------------------------------
        quotations = []
        sale_order = self.env['sale.order'].sudo()
        for so in sale_order.search(
            [('partner_id', '=', partner.id), ('state', 'in', ('draft', 'sent'))],
            order='date_order desc', limit=limit,
        ):
            quotations.append({
                'name': so.name,
                'receipt_number': so.name,
                'date': self._format_datetime_pak(so.date_order),
                'amount_formatted': currency.format(so.amount_total),
                'state': so.state,
                'state_label': dict(so._fields['state'].selection).get(so.state, so.state) if hasattr(so, '_fields') else so.state,
            })

        # --- Vendor / Supplier history -----------------------------------
        # Purchase orders placed with this vendor.
        purchase_orders = []
        po_model = self.env['purchase.order'].sudo()
        for po in po_model.search(
            [('partner_id', 'child_of', partner.id)],
            order='date_order desc, id desc', limit=limit,
        ):
            purchase_orders.append({
                'id': po.id,
                'name': po.name,
                'receipt_number': po.name,
                'date': self._format_datetime_pak(po.date_order),
                'amount': po.amount_total,
                'amount_formatted': currency.format(po.amount_total),
                'state': po.state,
                'state_label': dict(po._fields['state'].selection).get(po.state, po.state) if hasattr(po, '_fields') else po.state,
            })

        # Payable journal lines: bills we owe the vendor and payments we've made.
        payable = self.env['account.move.line'].sudo().search(
            [('partner_id', '=', partner.id),
             ('account_id.account_type', '=', 'liability_payable'),
             ('parent_state', '=', 'posted')],
            order='date desc, id desc', limit=limit,
        )
        vendor_payments, vendor_bills, unpaid_bills = [], [], []
        for line in payable:
            debit = line.debit or 0.0    # payment made to vendor
            credit = line.credit or 0.0  # bill received from vendor
            amt = round(credit if credit > 0 else debit, 2)
            res = round(abs(line.amount_residual), 2)
            paid = round(max(amt - res, 0.0), 2)
            if res <= 0.005:
                status = 'paid'
                status_label = 'Fully Paid'
            elif abs(res - amt) <= 0.005:
                status = 'unpaid'
                status_label = 'Unpaid'
            else:
                status = 'partial'
                status_label = 'Partially Paid'

            row = {
                'id': line.id,
                'date': str(line.date),
                'ref': line.move_id.name or '',
                'receipt_number': line.move_id.name or '',
                'label': line.name or '',
                'debit': debit,
                'credit': credit,
                'amount': amt,
                'amount_formatted': currency.format(amt),
                'paid_amount': paid,
                'paid_amount_formatted': currency.format(paid),
                'residual': res,
                'residual_formatted': currency.format(res),
                'payment_status': status,
                'payment_status_label': status_label,
            }
            # debit on payable = payment made to vendor; credit = bill/charge
            (vendor_payments if debit > 0 else vendor_bills).append(row)
            if credit > 0 and res > 0.005:
                unpaid_bills.append(row)

        # Lifetime vendor payable aggregates
        pay_grouped = self.env['account.move.line'].sudo()._read_group(
            domain=[
                ('partner_id', '=', partner.id),
                ('account_id.account_type', '=', 'liability_payable'),
                ('parent_state', '=', 'posted'),
            ],
            aggregates=('debit:sum', 'credit:sum'),
        )
        vend_debit_total, vend_credit_total = pay_grouped[0] if pay_grouped else (0.0, 0.0)
        vend_debit_total = vend_debit_total or 0.0    # Total paid to vendor
        vend_credit_total = vend_credit_total or 0.0  # Total bills from vendor
        vend_balance = vend_credit_total - vend_debit_total  # Net amount shop owes vendor

        return {
            'partner_id': partner.id,
            'name': partner.name,
            'phone': partner.phone or partner.mobile or '',
            'email': partner.email or '',
            'street': partner.street or '',
            'city': partner.city or '',
            'category_names': [cat.name for cat in partner.category_id],
            'membership_name': partner.membership_level_id.name if hasattr(partner, 'membership_level_id') and partner.membership_level_id else '',
            'note': partner.pos_retail_note or '',
            # Customer Ledger / Khata
            'customer_debit': money(cust_debit_total),
            'customer_credit': money(cust_credit_total),
            'customer_balance': money(cust_balance),
            'outstanding': money(cust_balance),
            'credit_limit': partner.pos_credit_limit or 0.0,
            'credit_limit_formatted': currency.format(partner.pos_credit_limit or 0.0),
            'credit_available': round((partner.pos_credit_limit or 0.0) - cust_balance, 2) if partner.pos_credit_limit else 0.0,
            'credit_available_formatted': currency.format(round((partner.pos_credit_limit or 0.0) - cust_balance, 2)) if partner.pos_credit_limit else currency.format(0.0),
            'loyalty_points': round(partner.pos_loyalty_points or 0.0, 1),
            'total_spent': partner.pos_total_spent or 0.0,
            'total_spent_formatted': currency.format(partner.pos_total_spent or 0.0),
            'avg_order_value': partner.pos_avg_order_value or 0.0,
            'avg_order_value_formatted': currency.format(partner.pos_avg_order_value or 0.0),
            'sales_order_count': partner.pos_sales_order_count or len(sales),
            'last_purchase_date': self._format_datetime_pak(partner.pos_last_purchase_date, include_time=False) if partner.pos_last_purchase_date else '',
            # Requirement 6: Customer Summary Card indicators
            'total_sales_formatted': currency.format(partner.pos_total_spent or 0.0),
            'total_paid_formatted': currency.format(max(0.0, (partner.pos_total_spent or 0.0) - cust_balance)),
            'total_outstanding_formatted': currency.format(cust_balance),
            'outstanding_invoices_count': len(open_invoices),
            'oldest_outstanding_name': (sorted(open_invoices, key=lambda x: (x.get('date') or '', str(x.get('id') or '')))[0]['receipt_number'] or sorted(open_invoices, key=lambda x: (x.get('date') or '', str(x.get('id') or '')))[0]['ref']) if open_invoices else '',
            'oldest_outstanding_date': sorted(open_invoices, key=lambda x: (x.get('date') or '', str(x.get('id') or '')))[0]['date'] if open_invoices else '',
            'latest_transaction_name': (sales[0].pos_reference or sales[0].name) if sales else (receivable[0].move_id.name if receivable else ''),
            'latest_transaction_date': self._format_datetime_pak(sales[0].date_order) if sales else (str(receivable[0].date) if receivable else ''),
            'latest_transaction_amount': currency.format(sales[0].amount_total) if sales else (currency.format(receivable[0].debit or receivable[0].credit) if receivable else ''),
            # Customer history lines
            'sales': [order_row(o) for o in sales[:limit]],
            'sales_count': len(sales),
            'refunds': [order_row(o) for o in refunds[:limit]],
            'refunds_count': len(refunds),
            'credit_sales': [
                order_row(o) for o in sales.filtered(
                    lambda o: (hasattr(o, 'pos_retail_on_account') and o.pos_retail_on_account > 0.005) or
                              any(is_credit_pm(p.payment_method_id) for p in o.payment_ids))[:limit]
            ],
            'payments': payments,
            'charges': charges,
            'open_invoices': open_invoices,
            'quotations': quotations,
            'top_products': top_products,
            'last_basket': last_basket,
            'last_order_name': last_order.pos_reference or last_order.name or '',
            'last_order_date': self._format_datetime_pak(last_order.date_order) if last_order else '',
            'last_order_total': last_order and currency.format(last_order.amount_total) or '',
            # Vendor side
            'is_vendor': bool(partner.supplier_rank or purchase_orders or payable),
            'vendor_bills_total': money(vend_credit_total),
            'vendor_paid_total': money(vend_debit_total),
            'vendor_balance': money(vend_balance),
            'purchase_orders': purchase_orders,
            'purchase_orders_count': len(purchase_orders),
            'vendor_payments': vendor_payments,
            'vendor_bills': vendor_bills,
            'unpaid_bills': unpaid_bills,
            # Security token for public WhatsApp PDF statement access
            'ledger_token': hmac.new(
                (self.env['ir.config_parameter'].sudo().get_param('database.secret', 'pos_retail_khata')).encode('utf-8'),
                f'ledger_partner_{partner.id}'.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()[:16],
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
            breakdown = partner._get_pos_khata_breakdown()
            total_owed = breakdown['total_owed']
            limit = partner.credit_limit or 0.0
            partner.pos_outstanding_balance = total_owed
            partner.pos_credit_limit = limit
            partner.pos_credit_available = limit - total_owed

    @api.model
    def _load_pos_data_domain(self, data, config):
        domain = super()._load_pos_data_domain(data, config)
        return domain + self._pos_retail_buyer_domain(config)

    @api.model
    def _pos_retail_buyer_domain(self, config):
        """Contacts a cashier may pick as the buyer on a sale.

        Two kinds of contact are filtered out of the POS customer list:

        * employees -- cashiers and staff are not buyers, and leaving them
          selectable is how a cashier's own name ends up on someone's order;
        * pure suppliers -- a paint wholesaler or a pipe importer has no place
          in the list a cashier scrolls at the counter, and picking one by
          mistake files a retail sale against a payables account.

        "Pure" matters: a contact that both buys and supplies is kept, because
        plenty of trade counters sell to the same businesses they buy from.
        Contacts with neither rank are kept too -- that is every ordinary
        customer created at the till, which starts at rank zero until an
        invoice is posted.
        """
        return [
            ('employee', '=', False),
            '|', ('supplier_rank', '=', 0), ('customer_rank', '>', 0),
            # Own contacts, or genuinely shared ones -- but NOT the parent
            # company's. Odoo resolves a child company to its whole parent
            # chain, so a branch set up under the head office inherits the head
            # office's customer list: johar town was finding Cash & Carry's
            # customers by name as well as its own.
            '|', ('company_id', '=', False), ('company_id', '=', config.company_id.id),
        ]

    @api.model
    def get_new_partner(self, config_id, domain, offset):
        """Apply the same filter to the POS "Search Customers" box.

        Core searches the whole res.partner table here, deliberately bypassing
        _load_pos_data_domain so a cashier can reach a customer who was never
        preloaded -- which also means vendors and staff come back in the
        results however carefully the preloaded list was filtered.

        Only the search branch is narrowed. An empty domain is core's
        pagination path over get_limited_partners_loading, whose records have
        already been through the filtered preload.
        """
        if domain:
            config = self.env['pos.config'].browse(config_id)
            domain = list(domain) + self._pos_retail_buyer_domain(config)
        return super().get_new_partner(config_id, domain, offset)

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

    def action_open_khata_payment(self):
        """Take money against this customer's khata.

        Distinct from the adjustment dialog next to it: this one moves real
        money into the till or the bank, which an adjustment never does.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Receive Khata Payment"),
            'res_model': 'pos.retail.khata.payment',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.id},
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

    def action_view_outstanding_invoices(self):
        """View all open unpaid and partially-paid invoices and POS orders for this customer (Requirement 10)."""
        self.ensure_one()
        partner = self.sudo()
        breakdown = partner._get_pos_khata_breakdown()
        order_allocations = breakdown['order_allocations']

        # 1. Invoiced moves with residual
        moves = self.env['account.move'].search([
            ('partner_id', '=', partner.id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
        ])

        # 2. Uninvoiced POS orders with credit residual
        uninvoiced_pos = breakdown.get('pos_orders') or self.env['pos.order'].sudo().search([
            ('partner_id', '=', partner.id),
            ('state', '!=', 'cancel'),
            ('account_move', '=', False),
        ])
        orders_with_debt = uninvoiced_pos.filtered(
            lambda o: order_allocations.get(o.id, {}).get('residual', 0.0) > 0.005
        )

        if moves:
            list_view = self.env.ref('pos_retail.pos_retail_outstanding_invoices_list', raise_if_not_found=False)
            res = {
                'type': 'ir.actions.act_window',
                'name': _("Outstanding Invoices: %s", partner.name),
                'res_model': 'account.move',
                'view_mode': 'list,form',
                'domain': [('id', 'in', moves.ids)],
                'context': {'default_partner_id': self.id, 'create': False},
            }
            if list_view:
                res['views'] = [(list_view.id, 'list'), (False, 'form')]
            return res

        else:
            return {
                'type': 'ir.actions.act_window',
                'name': _("Outstanding Orders: %s", partner.name),
                'res_model': 'pos.order',
                'view_mode': 'list,form',
                'domain': [('id', 'in', orders_with_debt.ids)],
                'context': {'default_partner_id': self.id, 'create': False},
            }

    def pos_retail_khata_lines(self):
        """The customer's khata as a running statement, for the PDF report.

        Receivable journal items, posted only, oldest first, with a running
        balance -- the same lines _compute_pos_credit_figures sums into
        pos_outstanding_balance, so the statement's closing figure always
        matches the balance shown in the POS and on receipts. Scoped to the
        companies in the current environment, so a branch prints its own book.
        """
        self.ensure_one()
        raw_entries = []
        lines = self.env['account.move.line'].search([
            ('partner_id', '=', self.id),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted'),
            ('company_id', 'in', self.env.companies.ids),
        ], order='date, id')
        for line in lines:
            line_date = line.date or fields.Date.context_today(self)
            raw_entries.append({
                'date': line_date,
                'id': line.id,
                'name': line.move_id.name or line.name or '',
                'debit': line.debit or 0.0,
                'credit': line.credit or 0.0,
            })

        # Include un-invoiced POS orders that carry an outstanding balance
        breakdown = self.sudo()._get_pos_khata_breakdown()
        order_allocations = breakdown.get('order_allocations', {})
        pos_orders = self.env['pos.order'].sudo().search([
            ('partner_id', '=', self.id),
            ('state', '!=', 'cancel'),
            ('account_move', '=', False),
            ('company_id', 'in', self.env.companies.ids),
        ], order='date_order asc, id asc')
        for o in pos_orders:
            alloc = order_allocations.get(o.id, {})
            debt = alloc.get('residual', 0.0)
            if debt > 0.005:
                order_date = o.date_order.date() if (o.date_order and hasattr(o.date_order, 'date')) else (o.date_order or fields.Date.context_today(self))
                raw_entries.append({
                    'date': order_date,
                    'id': o.id,
                    'name': o.pos_reference or o.name or 'POS Order',
                    'debit': debt,
                    'credit': 0.0,
                })

        # Sort all entries chronologically
        raw_entries.sort(key=lambda r: (r['date'], r['id']))

        # Compute running balance
        rows = []
        balance = 0.0
        for entry in raw_entries:
            balance += entry['debit'] - entry['credit']
            rows.append({
                'date': entry['date'],
                'name': entry['name'],
                'debit': entry['debit'],
                'credit': entry['credit'],
                'balance': balance,
            })
        return rows

    def action_print_customer_ledger(self):
        """Directly open printer for Customer Ledger without downloading."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/pos_retail/print_report?report=pos_retail.report_customer_ledger&id={self.id}',
            'target': 'new',
        }

    def action_download_customer_ledger_pdf(self):
        """Download Customer Ledger PDF file."""
        self.ensure_one()
        return self.env.ref('pos_retail.action_report_customer_ledger').report_action(self)

