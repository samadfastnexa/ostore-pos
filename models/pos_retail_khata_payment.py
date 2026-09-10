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
            company = wizard.company_id or self.env.company
            wizard.amount_owed = wizard.partner_id.with_company(company).credit

    @api.depends('amount_owed')
    def _compute_amount(self):
        # Clearing the whole balance is the common case; a part payment is the
        # cashier typing over it.
        for wizard in self:
            wizard.amount = wizard.amount_owed

    @api.depends('company_id')
    def _compute_journal_id(self):
        Journal = self.env['account.journal']
        for wizard in self:
            company = wizard.company_id or self.env.company
            base = [('company_id', '=', company.id)]
            wizard.journal_id = (
                Journal.search(base + [('type', '=', 'cash')], limit=1)
                or Journal.search(base + [('type', '=', 'bank')], limit=1)
            )

    @api.model
    def pos_retail_settle_from_pos(self, partner_id, amount, employee_id,
                                   journal_id=False, memo=False):
        """Take a khata payment at the till, in the middle of a queue.

        The shop's objection to doing this in the back office was practical
        and correct: a customer settling their udhaar is standing at the
        counter with people behind them, and the cashier is not going to open
        a second browser and sign in.

        WHOSE PERMISSION IS CHECKED, and why it is not the obvious one. Every
        call from a till arrives as the TILL ACCOUNT, because that is who the
        browser is signed in as -- one shared login for the device. Checking
        the caller would therefore give the same answer for every person who
        ever stands at that counter. So the check is against the EMPLOYEE who
        is logged in at the till, through the permission their own user
        carries in the Roles & Permissions catalogue.

        That also means hiding the button in the browser is not the control.
        The button is a courtesy; this method is the control, and it refuses
        an employee without the permission no matter how the call arrives.

        The record itself is then created with sudo. The till account is a
        till, not a bookkeeper: it has no business holding rights over
        payments and journals, and granting them to it would hand every
        cashier those rights whether or not they were meant to have them.
        """
        employee = self.env['hr.employee'].sudo().browse(int(employee_id)).exists()
        if not employee:
            raise UserError(_("No cashier is logged in at this till."))
        # Asked of the catalogue, not of a fixed group name. The shop decides
        # which permission unlocks this button, and the server has to agree
        # with whatever they chose, or the check drifts away from the screen
        # and starts refusing people the shop believes it authorised.
        allowed_groups = self.env['pos.retail.access.permission'] \
            ._pos_retail_till_capability_groups().get('_can_khata') or []
        user = employee.user_id
        if not user or not set(user.all_group_ids.ids).intersection(allowed_groups):
            raise UserError(_(
                "%(name)s is not allowed to take khata payments.\n\n"
                "This is granted in Point of Sale > Configuration > Roles & "
                "Permissions, with the \"Adjust Customer Khata\" permission, "
                "and it applies to the cashier's own login rather than to this "
                "till.",
                name=employee.name,
            ))

        partner = self.env['res.partner'].sudo().browse(int(partner_id)).exists()
        if not partner:
            raise UserError(_("Choose the customer who is paying."))

        wizard = self.sudo().new({'partner_id': partner.id})
        wizard._compute_company_id()
        wizard._compute_journal_id()
        values = {
            'partner_id': partner.id,
            'company_id': wizard.company_id.id,
            'currency_id': wizard.currency_id.id,
            'amount': amount,
            'journal_id': int(journal_id) if journal_id else wizard.journal_id.id,
            'memo': memo or _("Khata payment at the till"),
        }
        if not values['journal_id']:
            raise UserError(_(
                "This branch has no cash or bank account set up, so there is "
                "nowhere to record the money."))

        record = self.sudo().create(values)
        # action_confirm returns an action meant for a back-office screen. The
        # till has no use for it, and the figure it does need -- what the
        # customer owes now -- is the whole point of the exercise.
        record.action_confirm()
        # Both fields, and a flush first.
        #
        # pos_outstanding_balance is computed from partner.credit, which is
        # itself computed from the ledger. Invalidating only the outer field
        # recomputed it from a `credit` that was still cached from before the
        # payment, so the till was told the customer owed exactly what they
        # owed a moment ago -- the one number the whole action exists to
        # change. The flush makes sure the payment and its reconciliation are
        # in the database before either is read back.
        self.env.flush_all()
        partner.invalidate_recordset(['credit', 'pos_outstanding_balance'])
        return {
            'partner_id': partner.id,
            'paid': record.amount,
            'balance': partner.sudo().pos_outstanding_balance,
        }

    def action_confirm(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_("Enter how much the customer handed over."))
        if not self.partner_id.property_account_receivable_id:
            raise UserError(_(
                "%(customer)s has no receivable account set, so there is nowhere "
                "to record the khata. Set one on the customer's Accounting tab.",
                customer=self.partner_id.display_name,
            ))
        company = self.company_id or self.env.company
        # Paying more than is owed is allowed on purpose: an advance against
        # future goods is ordinary in a khata shop, and it simply leaves the
        # customer in credit.
        payment = self.env['account.payment'].with_company(company).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'journal_id': self.journal_id.id,
            'date': self.date,
            'memo': self.memo or _("Khata payment"),
            'company_id': company.id,
        })
        payment.action_post()
        self._settle_oldest_first(payment)
        return self.partner_id.action_view_customer_ledger()

    def _settle_oldest_first(self, payment):
        """Match the payment against the oldest debts.

        Without this the payment posts correctly but sits unmatched, so the
        ledger shows a 5,000 debt AND a 5,000 payment both still open, and the
        customer looks like they still owe. Oldest-first is what a shopkeeper
        means by "he paid off his khata": the earliest goods clear first.
        """
        company = self.company_id or self.env.company
        receivable = self.partner_id.property_account_receivable_id
        lines = self.env['account.move.line'].search(
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
        try:
            lines.reconcile()
        except Exception:
            # A partial match, a currency edge case or an already-settled line
            # must never cost us the payment itself: it is posted and visible
            # either way, and can be matched by hand from the customer's
            # ledger. Failing loudly here would leave the cashier thinking the
            # money was never taken.
            pass
