from odoo import _, api, fields, models
from odoo.exceptions import UserError


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
        'res.company', string="Branch",
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
