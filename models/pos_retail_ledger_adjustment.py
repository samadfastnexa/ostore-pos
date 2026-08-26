from odoo import _, api, fields, models
from odoo.exceptions import UserError


class PosRetailLedgerAdjustment(models.TransientModel):
    """Khata adjustment: change what a customer owes WITHOUT faking history.

    Posted ledger rows are immutable by design (core protects posted journal
    items; that is what makes the ledger trustworthy), so an adjustment is a
    NEW, properly balanced journal entry on the customer's receivable account:
    old debt brought in from a paper khata, an opening balance at migration,
    a waived amount, a correction. The ledger and the "Amount Owed" figure
    update the moment it posts, and the entry itself shows in the ledger with
    the given reason, so the trail stays complete.
    """
    _name = 'pos.retail.ledger.adjustment'
    _description = "Customer Ledger Adjustment"

    partner_id = fields.Many2one(
        'res.partner', string="Customer", required=True,
        default=lambda self: self.env.context.get('default_partner_id'),
        help="The customer whose outstanding balance is being corrected. The "
             "entry is posted against this customer's account, so it changes "
             "their Amount Owed and shows as a new line on their ledger.",
    )
    direction = fields.Selection(
        [
            ('increase', "Customer owes MORE (old debt / opening balance)"),
            ('decrease', "Customer owes LESS (waive / correction)"),
        ],
        required=True, default='increase',
        help="Choose 'owes MORE' to bring in a debt the system does not know "
             "about yet, such as a balance carried over from a paper khata; "
             "choose 'owes LESS' to waive an amount or correct one downwards. "
             "Either way a real accounting entry is posted and cannot be edited "
             "afterwards, so a mistake is put right by posting a second "
             "adjustment the other way.",
    )
    amount = fields.Monetary(
        required=True, currency_field='currency_id',
        help="How much to move the balance by, always typed in as a positive "
             "number. The direction above decides whether it is added to or "
             "taken off what the customer owes.",
    )
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id,
        help="Currency the amount above is measured in. It defaults to your "
             "company currency.",
    )
    date = fields.Date(
        required=True, default=fields.Date.context_today,
        help="The date the accounting entry is filed under. Use the day the debt "
             "really arose or was waived, because the ledger and your accounts "
             "are ordered by this date, not by when you keyed it in.",
    )
    reason = fields.Char(
        required=True,
        help="Shown on the ledger line and on the journal entry, e.g. "
             "\"Old khata balance brought forward\".",
    )
    company_id = fields.Many2one(
        'res.company', string="Branch",
        compute='_compute_company_id', store=True, readonly=False,
        help="Branch whose books the entry is posted in. Taken from the "
             "customer, since a customer belongs to one branch.",
    )
    counterpart_account_id = fields.Many2one(
        'account.account', string="Counterpart Account",
        compute='_compute_counterpart_account_id', store=True, readonly=False,
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]",
        help="The other side of the entry, filled in for you from the direction "
             "above: equity for a balance brought forward, an expense account "
             "for an amount written off. Change it only if your accountant asks "
             "you to; the customer's balance is the same either way.",
    )
    journal_id = fields.Many2one(
        'account.journal', string="Journal",
        compute='_compute_journal_id', store=True, readonly=False,
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        help="The book the entry is filed in. Filled in for you; it decides "
             "where your accountant finds the entry and has no effect on what "
             "the customer owes.",
    )

    @api.depends('partner_id')
    def _compute_company_id(self):
        for wizard in self:
            wizard.company_id = wizard.partner_id.company_id or self.env.company

    @api.depends('direction', 'company_id')
    def _compute_counterpart_account_id(self):
        """Pick the account the entry balances against, so nobody has to.

        Bringing an old khata forward is not income - the sale happened long
        ago, often before this system existed - so it lands against equity, the
        same place an opening balance goes. Writing an amount off IS a cost to
        the shop this year, so it lands against an expense account. Either way
        the customer's balance moves identically; the choice only decides where
        it shows in the accounts.
        """
        Account = self.env['account.account']
        for wizard in self:
            company = wizard.company_id or self.env.company
            accounts = Account.with_company(company)
            wanted = 'equity' if wizard.direction == 'increase' else 'expense'
            match = accounts.search([('account_type', '=', wanted)], limit=1)
            if not match:
                match = accounts.search([
                    ('account_type', 'not in', ('asset_receivable', 'liability_payable')),
                ], limit=1)
            wizard.counterpart_account_id = match

    @api.depends('company_id')
    def _compute_journal_id(self):
        """Prefer a miscellaneous journal over the POS one.

        Both are type 'general', and search() returns whichever was created
        first - which on this database is the Point of Sale journal. Filing a
        khata correction in the till's own journal muddles the day's takings
        with a back-office adjustment, so look for a Miscellaneous journal
        first and only fall back if the branch has none.
        """
        Journal = self.env['account.journal']
        for wizard in self:
            company = wizard.company_id or self.env.company
            base = [('type', '=', 'general'), ('company_id', '=', company.id)]
            match = (Journal.search(base + [('code', '=', 'MISC')], limit=1)
                     or Journal.search(base + [('name', 'ilike', 'miscellaneous')], limit=1)
                     or Journal.search(base + [('name', 'not ilike', 'point of sale')], limit=1)
                     or Journal.search(base, limit=1))
            wizard.journal_id = match

    def action_confirm(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_("The amount must be positive; use the direction "
                              "field to choose whether the customer owes more or less."))
        receivable = self.partner_id.property_account_receivable_id
        if not receivable:
            raise UserError(_("This customer has no receivable account configured."))
        inc = self.direction == 'increase'
        move = self.env['account.move'].with_company(self.company_id or self.env.company).create({
            'move_type': 'entry',
            'company_id': (self.company_id or self.env.company).id,
            'journal_id': self.journal_id.id,
            'date': self.date,
            'ref': self.reason,
            'line_ids': [
                (0, 0, {
                    'partner_id': self.partner_id.id,
                    'account_id': receivable.id,
                    'name': self.reason,
                    'debit': self.amount if inc else 0.0,
                    'credit': 0.0 if inc else self.amount,
                }),
                (0, 0, {
                    'partner_id': self.partner_id.id,
                    'account_id': self.counterpart_account_id.id,
                    'name': self.reason,
                    'debit': 0.0 if inc else self.amount,
                    'credit': self.amount if inc else 0.0,
                }),
            ],
        })
        move.action_post()
        # Straight back to the ledger, where the new row is now visible.
        return self.partner_id.action_view_customer_ledger()
