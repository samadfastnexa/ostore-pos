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
    counterpart_account_id = fields.Many2one(
        'account.account', string="Counterpart Account", required=True,
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]",
        help="The other side of the entry. For opening balances use an equity "
             "account; for waived amounts an expense account. Ask your "
             "accountant if unsure; the customer's balance changes the same "
             "way either way.",
    )
    journal_id = fields.Many2one(
        'account.journal', string="Journal", required=True,
        domain="[('type', '=', 'general')]",
        help="The book the entry is recorded in; the Miscellaneous journal is "
             "the normal choice. It decides where your accountant finds the "
             "entry and has no effect on the customer's balance.",
        default=lambda self: self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.env.company.id)], limit=1),
    )

    def action_confirm(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_("The amount must be positive; use the direction "
                              "field to choose whether the customer owes more or less."))
        receivable = self.partner_id.property_account_receivable_id
        if not receivable:
            raise UserError(_("This customer has no receivable account configured."))
        inc = self.direction == 'increase'
        move = self.env['account.move'].create({
            'move_type': 'entry',
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
