import datetime
import pytz
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .res_company import TRADING_COMPANY_DOMAIN


class PosRetailKhataPayment(models.TransientModel):
    """Receive money against a customer's khata.

    Kept separate from pos.retail.ledger.adjustment on purpose, because the two
    are different events that happen to move the balance in the same direction:

      * an ADJUSTMENT changes what is owed without money moving -- an old paper
        balance brought forward, or an amount waived. Waiving is a cost to the
        shop, so it lands against an expense account.
      * a PAYMENT is cash or bank actually received. It has to increase the till
        or the bank AND reduce what is owed. Booking it as a waiver, which is
        what the adjustment wizard would do, understates takings and overstates
        expenses by the same amount.

    Built on account.payment rather than a hand-rolled journal entry so it
    reconciles against the customer's open items, appears in the cash or bank
    journal like any other receipt, and can be reversed the normal way.
    """
    _name = 'pos.retail.khata.payment'
    _description = "Receive Khata Payment"

    partner_id = fields.Many2one(
        'res.partner', string="Customer", required=True,
        default=lambda self: self.env.context.get('default_partner_id'),
        help="The customer handing over the money. The payment is set against "
             "their account and their Amount Owed drops immediately.",
    )
    company_id = fields.Many2one(
        'res.company', string="Branch", domain=TRADING_COMPANY_DOMAIN,
        compute='_compute_company_id', store=True, readonly=False, precompute=True,
        help="Branch receiving the money. Taken from the customer, since a "
             "customer belongs to one branch.",
    )
    currency_id = fields.Many2one(
        'res.currency', compute='_compute_company_id', store=True, readonly=False,
        precompute=True)
    amount_owed = fields.Monetary(
        string="Currently Owes", compute='_compute_amount_owed',
        currency_field='currency_id',
        help="What this customer owes right now, across every unpaid sale and "
             "adjustment.",
    )
    amount = fields.Monetary(
        string="Amount Received", required=True, currency_field='currency_id',
        compute='_compute_amount', store=True, readonly=False, precompute=True,
        help="How much the customer is handing over. Defaults to clearing the "
             "whole khata; type a smaller figure for a part payment.",
    )
    journal_id = fields.Many2one(
        'account.journal', string="Received In", required=True,
        compute='_compute_journal_id', store=True, readonly=False, precompute=True,
        domain="[('type', 'in', ('cash', 'bank')), ('company_id', '=', company_id)]",
        help="Cash if the money went into the drawer, or the bank account it "
             "was transferred to.",
    )
    date = fields.Date(
        required=True, default=fields.Date.context_today,
        help="The day the money was received. The ledger is ordered by this "
             "date, not by when it was keyed in.",
    )
    memo = fields.Char(
        string="Note",
        help="Optional. Shown on the ledger line, for instance a receipt number.",
    )

    allocation_line_ids = fields.One2many(
        'pos.retail.khata.payment.line', 'wizard_id',
        string="Payment Allocation", compute='_compute_allocation_lines',
    )
    remaining_customer_balance = fields.Monetary(
        string="Remaining Customer Balance", compute='_compute_allocation_lines',
        currency_field='currency_id',
    )

    @api.depends('partner_id')
    def _compute_company_id(self):
        for wizard in self:
            company = wizard.partner_id.company_id or self.env.company
            wizard.company_id = company
            wizard.currency_id = company.currency_id

    @api.depends('partner_id', 'company_id')
    def _compute_amount_owed(self):
        for wizard in self:
            if not wizard.partner_id:
                wizard.amount_owed = 0.0
                continue
            wizard.amount_owed = wizard.partner_id.pos_outstanding_balance

    @api.depends('amount_owed')
    def _compute_amount(self):
        # Clearing the whole balance is the common case; a part payment is the
        # cashier typing over it.
        for wizard in self:
            wizard.amount = wizard.amount_owed

    @api.depends('partner_id', 'amount')
    def _compute_allocation_lines(self):
        for wizard in self:
            if not wizard.partner_id:
                wizard.allocation_line_ids = False
                wizard.remaining_customer_balance = 0.0
                continue
            alloc = self.env['res.partner'].get_customer_payment_allocation(wizard.partner_id.id, wizard.amount or 0.0)
            lines = []
            for item in alloc.get('lines', []):
                lines.append((0, 0, {
                    'name': item['name'],
                    'date': item['date'],
                    'previous_balance': item['previous_balance'],
                    'applied_amount': item['applied_amount'],
                    'remaining_balance': item['remaining_balance'],
                    'status': item['status'],
                }))
            wizard.allocation_line_ids = lines
            wizard.remaining_customer_balance = alloc.get('new_total_outstanding', 0.0)

    @api.depends('company_id')
    def _compute_journal_id(self):
        Journal = self.env['account.journal'].sudo()
        for wizard in self:
            company = wizard.company_id or self.env.company
            base = [('company_id', '=', company.id)]
            wizard.journal_id = (
                Journal.search(base + [('type', '=', 'cash')], limit=1)
                or Journal.search(base + [('type', '=', 'bank')], limit=1)
            )

    @api.model
    def get_pos_payment_journals(self, company_id=False):
        """Return available cash and bank payment methods for settlement."""
        company = self.env['res.company'].sudo().browse(int(company_id)) if company_id else self.env.company
        domain = [('type', 'in', ('cash', 'bank'))]
        if company:
            c_ids = [company.id]
            if company.parent_id:
                c_ids.append(company.parent_id.id)
            domain.append(('company_id', 'in', c_ids))
        journals = self.env['account.journal'].sudo().search(domain, order='type desc, name asc')
        return [
            {
                'id': j.id,
                'name': j.name,
                'type': j.type,
                'is_cash': j.type == 'cash',
            }
            for j in journals
        ]

    @api.model
    def pos_retail_settle_from_pos(self, partner_id, amount, employee_id,
                                   journal_id=False, memo=False, payment_date=False):
        """Take a khata payment at the till, in the middle of a queue.

        The shop's objection to doing this in the back office was practical
        and correct: a customer settling their udhaar is standing at the
        counter with people behind them, and the cashier is not going to open
        a second browser and sign in.
        """
        employee = self.env['hr.employee'].sudo().browse(int(employee_id)).exists() if employee_id else False
        user = (employee and employee.user_id) or self.env.user
        allowed = (
            any(user.has_group(g) for g in ('base.group_system', 'point_of_sale.group_pos_manager')) or
            self.env['pos.retail.access.permission']._pos_retail_user_has_till_capability(user, '_can_khata')
        )
        if not allowed:
            emp_name = employee.name if employee else user.name
            raise UserError(_(
                "%(name)s is not allowed to take khata payments.\n\n"
                "This is granted in Point of Sale > Configuration > Roles & "
                "Permissions, with the \"Adjust Customer Khata\" permission, "
                "and it applies to the cashier's own login rather than to this "
                "till.",
                name=emp_name,
            ))

        partner = self.env['res.partner'].sudo().browse(int(partner_id)).exists()
        if not partner:
            raise UserError(_("Choose the customer who is paying."))

        # Compute deterministic FIFO allocation preview before posting
        alloc = self.env['res.partner'].get_customer_payment_allocation(partner.id, amount)

        wizard = self.sudo().new({'partner_id': partner.id})
        wizard._compute_company_id()
        wizard._compute_journal_id()

        target_journal_id = False
        if journal_id:
            pm = self.env['pos.payment.method'].sudo().browse(int(journal_id)).exists()
            if pm and pm.journal_id:
                target_journal_id = pm.journal_id.id
            else:
                j = self.env['account.journal'].sudo().browse(int(journal_id)).exists()
                if j:
                    target_journal_id = j.id

        values = {
            'partner_id': partner.id,
            'company_id': wizard.company_id.id,
            'currency_id': wizard.currency_id.id,
            'amount': amount,
            'date': payment_date or fields.Date.context_today(self),
            'journal_id': target_journal_id or wizard.journal_id.id,
            'memo': memo or _("Khata payment at the till"),
        }
        if not values['journal_id']:
            raise UserError(_(
                "This branch has no cash or bank account set up, so there is "
                "nowhere to record the money."))

        record = self.sudo().create(values)
        created_payment = record._action_confirm_payment()
        self.env.flush_all()
        partner.invalidate_recordset(['credit', 'pos_outstanding_balance'])
        new_balance = partner.sudo().pos_outstanding_balance
        currency = record.currency_id or partner.currency_id or self.env.company.currency_id
        return {
            'payment_id': created_payment.id if created_payment else False,
            'payment_name': created_payment.name if created_payment else '',
            'partner_id': partner.id,
            'partner_name': partner.name,
            'partner_phone': partner.phone or partner.mobile or '',
            'paid': record.amount,
            'paid_formatted': currency.format(record.amount),
            'previous_balance': alloc['previous_total_outstanding'],
            'previous_balance_formatted': alloc['previous_total_outstanding_formatted'],
            'new_balance': new_balance,
            'new_balance_formatted': currency.format(new_balance),
            'allocations': alloc.get('lines', []),
            'journal_name': record.journal_id.name or '',
            'memo': record.memo or '',
            'date': str(record.date),
            'datetime': pytz.utc.localize(datetime.datetime.utcnow()).astimezone(pytz.timezone('Asia/Karachi')).strftime('%Y-%m-%d %H:%M:%S'),
            'cashier_name': employee.name if employee else user.name,
            'branch_name': record.company_id.name or '',
        }

    def _action_confirm_payment(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_("Enter how much the customer handed over."))
        if not self.partner_id.property_account_receivable_id:
            raise UserError(_(
                "%(customer)s has no receivable account set, so there is nowhere "
                "to record the khata. Set one on the customer's Accounting tab.",
                customer=self.partner_id.display_name,
            ))
        journal = self.journal_id.sudo()
        company = journal.company_id or self.company_id or self.env.company
        payment = self.env['account.payment'].sudo().with_company(company).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'journal_id': journal.id,
            'date': self.date,
            'memo': self.memo or _("Khata payment"),
            'company_id': company.id,
        })
        payment.sudo().action_post()
        self._settle_oldest_first(payment)
        return payment

    def action_confirm(self):
        self._action_confirm_payment()
        return self.partner_id.action_view_customer_ledger()

    def _settle_oldest_first(self, payment):
        """Match the payment against the oldest debts.

        Without this the payment posts correctly but sits unmatched, so the
        ledger shows a 5,000 debt AND a 5,000 payment both still open, and the
        customer looks like they still owe. Oldest-first is what a shopkeeper
        means by "he paid off his khata": the earliest goods clear first.
        """
        company = payment.company_id or self.company_id or self.env.company
        receivable = self.partner_id.property_account_receivable_id
        lines = self.env['account.move.line'].sudo().search(
            [
                ('partner_id', '=', self.partner_id.id),
                ('account_id', '=', receivable.id),
                ('parent_state', '=', 'posted'),
                ('reconciled', '=', False),
                ('company_id', '=', company.id),
            ],
            order='date, id',
        )
        if len(lines) < 2:
            return
        has_debit = any(l.debit > 0 for l in lines)
        has_credit = any(l.credit > 0 for l in lines)
        if not (has_debit and has_credit):
            return
        try:
            lines.sudo().reconcile()
        except Exception:
            # A partial match, a currency edge case or an already-settled line
            # must never cost us the payment itself: it is posted and visible
            # either way, and can be matched by hand from the customer's
            # ledger. Failing loudly here would leave the cashier thinking the
            # money was never taken.
            pass


class PosRetailKhataPaymentLine(models.TransientModel):
    _name = 'pos.retail.khata.payment.line'
    _description = "Khata Payment Allocation Line"
    _order = 'id asc'

    wizard_id = fields.Many2one('pos.retail.khata.payment', string="Wizard", ondelete='cascade')
    name = fields.Char(string="Invoice / Order", readonly=True)
    date = fields.Char(string="Date", readonly=True)
    currency_id = fields.Many2one('res.currency', related='wizard_id.currency_id')
    previous_balance = fields.Monetary(string="Previous Balance", readonly=True, currency_field='currency_id')
    applied_amount = fields.Monetary(string="Applied", readonly=True, currency_field='currency_id')
    remaining_balance = fields.Monetary(string="Remaining", readonly=True, currency_field='currency_id')
    status = fields.Selection([
        ('paid', "Paid"),
        ('partial', "Balance"),
        ('unpaid', "Outstanding"),
    ], string="Status", readonly=True)
